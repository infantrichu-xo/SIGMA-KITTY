"""
Text-to-speech: joins your voice channel and reads the chat aloud.

 - /tts   toggles TTS. First run: joins your current voice channel and
          starts reading new messages from the channel you ran it in,
          announced as "<username> says: <message>". Run it again (in the
          same server) to stop and disconnect.

Uses edge-tts (Microsoft Edge's free, no-API-key TTS engine) with a fast,
confident female voice, then plays the result through the same voice
connection the Music cog manages, so TTS and music share one connection per
guild instead of fighting over two. If music is currently playing when a
message is read, the track is swapped out for the TTS clip and swapped back
in afterward, so the song isn't skipped -- just briefly interrupted.

Spam is skipped automatically:
 - bot messages
 - messages that are empty once links/mentions/emoji are stripped out
 - a message identical to that author's last one, repeated within
   DUPLICATE_WINDOW seconds (copy-paste/spam floods)

Requires: pip install edge-tts mutagen  (mutagen reads the mp3's exact
duration without needing ffprobe -- only the ffmpeg binary itself is
needed, for playback, and that's resolved via ffmpeg_utils so it works
even on hosts like Wispbyte where you can't apt-install/pip-install
ffmpeg system-wide -- see requirements.txt / imageio-ffmpeg)
"""

import asyncio
import os
import re
import tempfile
import time

import discord
from discord import app_commands
from discord.ext import commands
import edge_tts
from mutagen.mp3 import MP3

from config import guild_config
from ffmpeg_utils import get_ffmpeg_path

MAX_READ_CHARS = 200
DUPLICATE_WINDOW = 10  # seconds -- skip a repeated identical message from the same author within this window

# Fast, confident US-English female voice. Full list: `edge-tts --list-voices`
TTS_VOICE = "en-US-AriaNeural"
TTS_RATE = "+35%"  # noticeably faster than natural speaking pace, per-guild adjustable via /panel

_MENTION_RE = re.compile(r"<@!?\d+>|<@&\d+>|<#\d+>")
_URL_RE = re.compile(r"https?://\S+")
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")


class TTS(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.locks: dict[int, asyncio.Lock] = {}
        # guild_id -> text channel id currently being read aloud
        self.active: dict[int, int] = {}
        # (guild_id, author_id) -> (last_text, last_time), for dupe/spam skipping
        self._last_msg: dict[tuple[int, int], tuple[str, float]] = {}

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        return self.locks.setdefault(guild_id, asyncio.Lock())

    def _music_state(self, guild_id: int):
        cog = self.bot.get_cog("Music")
        if cog is None:
            return None
        return cog.state_for(guild_id)

    def _is_spam(self, guild_id: int, author_id: int, text: str) -> bool:
        key = (guild_id, author_id)
        now = time.monotonic()
        last = self._last_msg.get(key)
        self._last_msg[key] = (text, now)
        if last is None:
            return False
        last_text, last_time = last
        return text == last_text and (now - last_time) < DUPLICATE_WINDOW

    async def _speak(self, guild: discord.Guild, channel: discord.VoiceChannel, text: str):
        """Core TTS playback. Connects if needed, speaks `text`, and if
        music was playing, resumes it afterward. Serialized per-guild."""
        state = self._music_state(guild.id)
        if state is None:
            raise RuntimeError("Music system isn't loaded (TTS shares its voice connection).")

        async with self._lock_for(guild.id):
            if state.voice_client is None or not state.voice_client.is_connected():
                state.voice_client = await channel.connect(reconnect=True, self_deaf=True)
            vc = state.voice_client

            fd, path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            try:
                rate = guild_config.get_guild_key(guild.id, "tts_rate", TTS_RATE)
                voice = guild_config.get_guild_key(guild.id, "tts_voice", TTS_VOICE)
                communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
                await communicate.save(path)

                try:
                    duration = MP3(path).info.length
                except Exception:
                    duration = 3.0  # safe-ish fallback if the mp3 can't be read for some reason

                tts_source = discord.FFmpegPCMAudio(path, executable=get_ffmpeg_path())

                was_playing = vc.is_playing() or vc.is_paused()
                old_source = vc.source if was_playing else None

                if was_playing:
                    vc.source = tts_source  # atomically pauses, swaps, resumes
                else:
                    vc.play(tts_source)

                await asyncio.sleep(duration + 0.3)

                if was_playing and old_source is not None:
                    vc.source = old_source
                else:
                    vc.stop()
                tts_source.cleanup()
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

    # ---------------------------------------------------------------- /tts
    @app_commands.command(name="tts", description="Join your voice channel and read this channel's chat aloud (run again to stop)")
    async def tts(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        # Already active in this guild -> toggle off
        if guild_id in self.active:
            channel_id = self.active.pop(guild_id)
            state = self._music_state(guild_id)
            if state and state.voice_client and state.voice_client.is_connected():
                await state.voice_client.disconnect()
            embed = discord.Embed(
                title="🔇 TTS stopped",
                description=f"Stopped reading <#{channel_id}> and left voice.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Join a voice channel first.", ephemeral=True)
            return

        state = self._music_state(guild_id)
        if state is None:
            await interaction.response.send_message("⚠️ Music system isn't loaded (TTS shares its voice connection).", ephemeral=True)
            return

        await interaction.response.defer()
        channel = interaction.user.voice.channel
        try:
            if state.voice_client is None or not state.voice_client.is_connected():
                state.voice_client = await channel.connect(reconnect=True, self_deaf=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Couldn't join voice: {e}")
            return

        self.active[guild_id] = interaction.channel.id
        embed = discord.Embed(
            title="🗣️ TTS started",
            description=(
                f"Joined {channel.mention} and reading {interaction.channel.mention} aloud.\n"
                f"Run `/tts` again to stop."
            ),
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        channel_id = self.active.get(guild_id)
        if channel_id is None or message.channel.id != channel_id:
            return

        state = self._music_state(guild_id)
        if state is None or state.voice_client is None or not state.voice_client.is_connected():
            self.active.pop(guild_id, None)  # got disconnected some other way -- stop tracking
            return

        text = _URL_RE.sub("", message.content)
        text = _MENTION_RE.sub("", text)
        text = _EMOJI_RE.sub("", text)
        text = text.strip()

        if len(text) < 2:
            return  # nothing worth saying (empty, or just a link/mention/emoji)
        if self._is_spam(guild_id, message.author.id, text):
            return  # skip -- same message repeated too soon

        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "..."

        announced = f"{message.author.display_name} says {text}"

        try:
            await self._speak(message.guild, state.voice_client.channel, announced)
        except Exception:
            pass  # don't spam the channel with TTS errors on every message


async def setup(bot: commands.Bot):
    await bot.add_cog(TTS(bot))
