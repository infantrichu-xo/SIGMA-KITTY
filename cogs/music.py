"""
Music playback with a 24/7 mode (bot stays connected to a voice channel and
auto-reconnects if disconnected), high-quality audio, and support for any
link yt-dlp understands (YouTube, SoundCloud, Bandcamp, Vimeo, Twitch clips,
direct audio/video file URLs, and 1000+ other sites), plus Spotify links.

Spotify's API does not allow direct audio streaming for bots, so Spotify
track/playlist/album links are resolved via Spotipy (metadata only: track
name + artist), and each track is then searched for and streamed at the
highest available bitrate from YouTube using yt-dlp. Any other supported
link (or a plain search term) is streamed directly.

Audio quality notes:
  - yt-dlp is told to prefer the highest-bitrate audio-only stream
    (Opus/WebM when available, since that's what Discord's voice pipeline
    natively uses -- no lossy re-encode needed on the way in).
  - ffmpeg is pinned to 48kHz/stereo, the exact format Discord voice expects,
    avoiding an extra resample step.
  - The actual ceiling on outgoing quality is the voice channel's bitrate
    (Server Settings -> Overview, or per-channel). Boosted servers support
    up to 384kbps; an unboosted server caps around 96kbps. The bot can't
    raise this itself -- only server boosts / channel bitrate settings can.

Requires:
  - ffmpeg installed on the host machine (not a pip package)
  - pip install yt-dlp spotipy PyNaCl
  - SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in .env (optional, only needed
    for Spotify links -- everything else works without it)
"""

import asyncio
import os
import re

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

from config import guild_config
from ffmpeg_utils import get_ffmpeg_path

SPOTIFY_TRACK_RE = re.compile(r"open\.spotify\.com/track/([A-Za-z0-9]+)")
SPOTIFY_PLAYLIST_RE = re.compile(r"open\.spotify\.com/playlist/([A-Za-z0-9]+)")
SPOTIFY_ALBUM_RE = re.compile(r"open\.spotify\.com/album/([A-Za-z0-9]+)")

# Prefer the highest-bitrate audio-only stream; fall back progressively.
# "bestaudio[abr>0]" ranks by actual bitrate rather than yt-dlp's format-id
# ordering, so we consistently grab the best-sounding stream on offer.
YTDL_OPTS = {
    "format": "bestaudio[abr>0]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}
# -ar 48000 -ac 2: match Discord voice's native 48kHz/stereo pipeline exactly
# so ffmpeg isn't doing a lossy resample on top of the source codec.
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -ar 48000 -ac 2 -loglevel warning",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)
# Separate instance for playlist probing: extract_flat keeps it fast (no
# per-video metadata fetch) when we just need the list of URLs.
ytdl_flat = yt_dlp.YoutubeDL({**YTDL_OPTS, "extract_flat": True, "noplaylist": False})




_spotify_client_cache = None


def get_spotify_client(force_fresh: bool = False):
    """Lazily build a Spotipy client. Returns None if creds aren't configured.

    IMPORTANT: as of Spotify's Nov 2024 API changes, playlist/album lookups
    (unlike single-track lookups) NO LONGER WORK with app-only "Client
    Credentials" auth -- Spotify now returns 401 "Valid user authentication
    required" for those endpoints even with a perfectly valid, freshly
    issued app token. There is no way around this without a real user
    login: a one-time browser authorization that produces a refresh token,
    which is what SPOTIFY_REFRESH_TOKEN below is for. Run
    `python get_spotify_refresh_token.py` once to generate it (see
    README.md). Track lookups alone would still work with just
    Client Credentials, but since playlists/albums need user auth anyway,
    we use it for everything once it's configured.
    """
    global _spotify_client_cache
    cid = os.getenv("SPOTIFY_CLIENT_ID")
    secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        return None
    if _spotify_client_cache is not None and not force_fresh:
        return _spotify_client_cache

    import spotipy
    refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")
    if refresh_token:
        from spotipy.oauth2 import SpotifyOAuth
        redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
        cache_handler = spotipy.MemoryCacheHandler()
        auth_manager = SpotifyOAuth(
            client_id=cid,
            client_secret=secret,
            redirect_uri=redirect_uri,
            scope="playlist-read-private playlist-read-collaborative",
            cache_handler=cache_handler,
            open_browser=False,
        )
        # Seed the cache with the saved refresh token so spotipy can mint
        # (and later auto-renew) access tokens without any browser prompt.
        token_info = auth_manager.refresh_access_token(refresh_token)
        cache_handler.save_token_to_cache(token_info)
        _spotify_client_cache = spotipy.Spotify(auth_manager=auth_manager)
        return _spotify_client_cache

    # No refresh token configured -- fall back to Client Credentials. This
    # still works for single-track links, but playlist/album links will
    # 401 (see docstring above).
    from spotipy.oauth2 import SpotifyClientCredentials
    auth_manager = SpotifyClientCredentials(
        client_id=cid,
        client_secret=secret,
        cache_handler=spotipy.MemoryCacheHandler(),
    )
    _spotify_client_cache = spotipy.Spotify(auth_manager=auth_manager)
    return _spotify_client_cache


class GuildMusicState:
    """Per-guild queue + 24/7 flag + currently playing track."""
    def __init__(self):
        self.queue: list[dict] = []      # each: {"title", "search", "requester"}
        self.now_playing: dict | None = None
        self.stay_247 = False
        self.text_channel: discord.abc.Messageable | None = None
        self.voice_client: discord.VoiceClient | None = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def state_for(self, guild_id: int) -> GuildMusicState:
        return self.states.setdefault(guild_id, GuildMusicState())

    # --------------------------------------------------------- link parsing
    async def resolve_spotify_link(self, url: str, retry_on_401: bool = False) -> list[str]:
        """Return a list of 'search query' strings ("Artist - Track") for a
        Spotify track/playlist/album URL. Empty list if unresolvable."""
        sp = get_spotify_client(force_fresh=retry_on_401)
        if sp is None:
            raise RuntimeError(
                "Spotify support isn't configured. Set SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET in .env (get them free at "
                "https://developer.spotify.com/dashboard)."
            )

        loop = asyncio.get_event_loop()

        try:
            if m := SPOTIFY_TRACK_RE.search(url):
                track = await loop.run_in_executor(None, sp.track, m.group(1))
                return [f"{track['artists'][0]['name']} - {track['name']}"]

            if m := SPOTIFY_PLAYLIST_RE.search(url):
                queries = []
                results = await loop.run_in_executor(
                    None, lambda: sp.playlist_items(m.group(1), additional_types=("track",))
                )
                # playlist_items only returns a page (100 tracks) at a time --
                # follow "next" so playlists bigger than that aren't silently
                # truncated.
                while results:
                    for item in results.get("items", []):
                        t = item.get("track")
                        # Skip local files / unavailable tracks / podcast
                        # episodes -- they don't have a usable artist list and
                        # would otherwise raise a KeyError and abort the
                        # whole playlist.
                        if t and t.get("artists"):
                            queries.append(f"{t['artists'][0]['name']} - {t['name']}")
                    if results.get("next"):
                        results = await loop.run_in_executor(None, sp.next, results)
                    else:
                        results = None
                return queries

            if m := SPOTIFY_ALBUM_RE.search(url):
                queries = []
                results = await loop.run_in_executor(None, sp.album_tracks, m.group(1))
                while results:
                    queries.extend(
                        f"{t['artists'][0]['name']} - {t['name']}"
                        for t in results.get("items", [])
                        if t.get("artists")
                    )
                    if results.get("next"):
                        results = await loop.run_in_executor(None, sp.next, results)
                    else:
                        results = None
                return queries
        except RuntimeError:
            raise
        except Exception as e:
            status = getattr(e, "http_status", None)
            if status == 401 and not retry_on_401:
                get_spotify_client(force_fresh=True)
                return await self.resolve_spotify_link(url, retry_on_401=True)
            if status == 401:
                if os.getenv("SPOTIFY_REFRESH_TOKEN"):
                    raise RuntimeError(
                        "Spotify lookup failed: 401 Unauthorized even with user "
                        "auth configured. Your SPOTIFY_REFRESH_TOKEN may have been "
                        "revoked -- re-run `python get_spotify_refresh_token.py` to "
                        "generate a new one and update .env."
                    )
                raise RuntimeError(
                    "Spotify lookup failed: 401 Unauthorized. As of Spotify's Nov "
                    "2024 API changes, playlist/album lookups require a real user "
                    "login, not just an app token -- Client Credentials alone can't "
                    "do this anymore. Run `python get_spotify_refresh_token.py` "
                    "once to authorize the bot and get a SPOTIFY_REFRESH_TOKEN, "
                    "then add it to .env and restart the bot. See README.md for "
                    "details."
                )
            if status == 404:
                raise RuntimeError(
                    "Couldn't find that on Spotify. Make sure the playlist is "
                    "public (not private) -- auto-generated ones like Discover "
                    "Weekly or Release Radar can't be read this way either."
                )
            if status == 403:
                raise RuntimeError(
                    "Spotify refused that request (403) -- this usually means "
                    "the playlist is private or region-restricted."
                )
            raise RuntimeError(f"Spotify lookup failed: {e}")

        return []

    async def resolve_generic_playlist(self, url: str) -> list[str] | None:
        """If `url` is a playlist on any yt-dlp-supported site (YouTube,
        SoundCloud, Bandcamp, etc.), return a list of individual track URLs
        to queue. Returns None if it's a single track (caller should just
        queue `url` directly)."""
        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(None, lambda: ytdl_flat.extract_info(url, download=False))
        except Exception:
            return None
        if info and "entries" in info:
            urls = []
            for entry in info["entries"]:
                if not entry:
                    continue
                # extract_flat entries usually have "url" (id or full url)
                u = entry.get("url") or entry.get("webpage_url")
                if u:
                    urls.append(u)
            return urls
        return None

    # ------------------------------------------------------------ playback
    def _play_next(self, guild: discord.Guild):
        state = self.state_for(guild.id)
        vc = state.voice_client
        if vc is None:
            return

        if not state.queue:
            state.now_playing = None
            if not state.stay_247:
                asyncio.run_coroutine_threadsafe(vc.disconnect(), self.bot.loop)
            return

        track = state.queue.pop(0)
        state.now_playing = track

        def after_play(error):
            if error:
                print(f"Player error: {error}")
            self._play_next(guild)

        try:
            try:
                info = ytdl.extract_info(track["search"], download=False)
            except yt_dlp.utils.DownloadError:
                # Retry once with a looser format string in case the
                # preferred (highest-bitrate) format wasn't available.
                info = yt_dlp.YoutubeDL({**YTDL_OPTS, "format": "bestaudio/best"}).extract_info(
                    track["search"], download=False
                )
            if "entries" in info:
                info = info["entries"][0]
            source = discord.FFmpegPCMAudio(info["url"], executable=get_ffmpeg_path(), **FFMPEG_OPTS)
            vc.play(discord.PCMVolumeTransformer(source, volume=0.5), after=after_play)
            abr = info.get("abr")
            quality_note = f" ({abr:.0f}kbps source)" if abr else ""
            if state.text_channel:
                asyncio.run_coroutine_threadsafe(
                    state.text_channel.send(
                        f"🎶 Now playing: **{info.get('title', track['search'])}**{quality_note}"
                    ),
                    self.bot.loop,
                )
           except Exception as e:
            
            import traceback
            traceback.print_exc()

            if state.text_channel:
                asyncio.run_coroutine_threadsafe(
                    state.text_channel.send(
                        f"⚠️ Couldn't play `{track['search']}`:\n"
                        f"`{type(e).__name__}: {e}`"
                    ),
                    self.bot.loop,
                )

            self._play_next(guild)
    # -------------------------------------------------------------- commands
    @app_commands.command(name="join", description="Join your voice channel and stay 24/7")
    async def join(self, interaction: discord.Interaction, stay_247: bool = True):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Join a voice channel first.", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        state = self.state_for(interaction.guild.id)

        if state.voice_client and state.voice_client.is_connected():
            await state.voice_client.move_to(channel)
        else:
            state.voice_client = await channel.connect(reconnect=True, self_deaf=True)

        state.stay_247 = stay_247
        state.text_channel = interaction.channel
        guild_config.set_guild_key(interaction.guild.id, "music_247", stay_247)

        await interaction.response.send_message(
            f"🔊 Joined **{channel.name}**" + (" — staying 24/7." if stay_247 else ".")
        )

    @app_commands.command(name="leave", description="Disconnect from voice and clear the queue")
    async def leave(self, interaction: discord.Interaction):
        state = self.state_for(interaction.guild.id)
        state.stay_247 = False
        state.queue.clear()
        if state.voice_client:
            await state.voice_client.disconnect()
            state.voice_client = None
        await interaction.response.send_message("👋 Disconnected.")

    @app_commands.command(name="play", description="Play from a search term, or any YouTube/SoundCloud/Spotify/etc. link")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("❌ Join a voice channel first.")
            return

        state = self.state_for(interaction.guild.id)
        state.text_channel = interaction.channel

        if state.voice_client is None or not state.voice_client.is_connected():
            state.voice_client = await interaction.user.voice.channel.connect(reconnect=True, self_deaf=True)
            state.stay_247 = guild_config.get_guild_key(interaction.guild.id, "music_247", False)

        if "open.spotify.com" in query:
            try:
                queries = await self.resolve_spotify_link(query)
            except RuntimeError as e:
                await interaction.followup.send(f"❌ {e}")
                return
            if not queries:
                await interaction.followup.send("❌ Couldn't resolve that Spotify link.")
                return
            for q in queries:
                state.queue.append({"title": q, "search": f"ytsearch:{q} audio", "requester": interaction.user.id})
            await interaction.followup.send(f"✅ Queued **{len(queries)}** track(s) from Spotify.")

        elif query.startswith("http") and any(marker in query for marker in ("list=", "/sets/", "/album/", "playlist")):
            # Looks like a playlist on YouTube, SoundCloud, Bandcamp, etc.
            urls = await self.resolve_generic_playlist(query)
            if urls:
                for u in urls:
                    state.queue.append({"title": u, "search": u, "requester": interaction.user.id})
                await interaction.followup.send(f"✅ Queued **{len(urls)}** track(s) from that playlist.")
            else:
                state.queue.append({"title": query, "search": query, "requester": interaction.user.id})
                await interaction.followup.send(f"✅ Queued: **{query}**")

        else:
            # Any single yt-dlp-supported link (YouTube, SoundCloud,
            # Bandcamp, Vimeo, direct audio file URL, etc.) or a search term.
            search = query if query.startswith("http") else f"ytsearch:{query}"
            state.queue.append({"title": query, "search": search, "requester": interaction.user.id})
            await interaction.followup.send(f"✅ Queued: **{query}**")

        if not state.voice_client.is_playing() and not state.voice_client.is_paused():
            self._play_next(interaction.guild)

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        state = self.state_for(interaction.guild.id)
        if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
            state.voice_client.stop()  # triggers after_play -> _play_next
            await interaction.response.send_message("⏭️ Skipped.")
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction):
        state = self.state_for(interaction.guild.id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.pause()
            await interaction.response.send_message("⏸️ Paused.")
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction):
        state = self.state_for(interaction.guild.id)
        if state.voice_client and state.voice_client.is_paused():
            state.voice_client.resume()
            await interaction.response.send_message("▶️ Resumed.")
        else:
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue_cmd(self, interaction: discord.Interaction):
        state = self.state_for(interaction.guild.id)
        lines = []
        if state.now_playing:
            lines.append(f"**Now playing:** {state.now_playing['title']}")
        if state.queue:
            lines.append("\n**Up next:**")
            lines += [f"{i+1}. {t['title']}" for i, t in enumerate(state.queue[:15])]
        if not lines:
            lines = ["Queue is empty."]
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="stop", description="Stop playback and clear the queue (stays in VC if 24/7)")
    async def stop(self, interaction: discord.Interaction):
        state = self.state_for(interaction.guild.id)
        state.queue.clear()
        if state.voice_client:
            state.voice_client.stop()
        await interaction.response.send_message("⏹️ Stopped and cleared the queue.")

    # ------------------------------------------------------- 24/7 reconnect
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if member.id != self.bot.user.id:
            return
        # We were disconnected (kicked, connection dropped, etc.)
        if before.channel is not None and after.channel is None:
            state = self.states.get(member.guild.id)
            if state and state.stay_247 and before.channel:
                await asyncio.sleep(3)
                try:
                    state.voice_client = await before.channel.connect(reconnect=True, self_deaf=True)
                except discord.ClientException:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
