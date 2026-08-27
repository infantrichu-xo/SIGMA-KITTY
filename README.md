# All-in-one Moderation / Music / Gambling Discord Bot

A single `discord.py` bot with:

- **Moderation** — kick, ban, unban, timeout, warnings, purge, mod-log channel.
  `/warn` supports customizable offense presets (configure in `/panel` ->
  Moderation -> Warn Offenses) that each auto-apply a timeout/kick/ban on
  top of logging the warning, or just type a free-text reason as before.
- **Tickets** — members click a button to open a private ticket channel
  with staff. Configure the category, support role, and log channel in
  `/panel` -> Tickets, then use **Send ticket panel here** to post the
  open-a-ticket button in any channel.
- **`/message`** — post a formatted embed announcement to any channel via
  a modal (title + multi-line body). Supports Discord markdown in the
  body: `#`/`##` headings, `**bold**`, and `[masked links](url)`.
- **Word filter** — deletes messages containing any word listed in `bad.txt`
  (same folder as `main.py`); manage the list live with `/badword`
- **Autorole** — automatically gives new members a configured role, plus
  `/roleall` to bulk add/remove a role for every existing member
- **Anti-raid** — detects join floods, locks the server (raises verification
  level, kicks brand-new accounts) until you turn it off
- **Anti-nuke** — watches the audit log for mass channel/role deletes, mass
  bans/kicks, and webhook spam by non-whitelisted users, and reacts by
  stripping their dangerous roles (or banning, if configured)
- **24/7 music** — joins a voice channel and stays connected, plays audio
  from **any link `yt-dlp` supports** (YouTube, SoundCloud, Bandcamp, Vimeo,
  direct audio/video file URLs, and 1000+ other sites) **and Spotify
  track/playlist/album links**, at the highest available source bitrate
  (Spotify links are resolved to track names via Spotify's API, then
  streamed from YouTube — Spotify doesn't allow bots to stream its audio
  directly). Playlists on YouTube/SoundCloud/Bandcamp are auto-expanded and
  queued track-by-track.
- **Text-to-speech** — `/tts <text>` speaks aloud in your voice channel
  (works alongside music: the current track is briefly swapped out and
  swapped back in, not skipped). By default, the bot also automatically
  reads aloud whatever's typed in a voice channel's own built-in text chat
  while it's connected there (toggle with `/tts-vcchat`), plus you can add
  one extra separate text channel to read via `/tts-autoread`
- **Gambling mini-games** — play-money economy with `/coinflip`, `/dice`,
  `/slots`, `/blackjack`, `/balance`, `/daily`. Optionally restrict the
  four betting games to one channel via `/panel` -> Economy.
- **Voice Master (join-to-create)** — set a trigger voice channel in
  `/panel` -> Voice Master; anyone who joins it instantly gets their own
  new voice channel and is moved into it, with full owner controls via
  `/voice lock|unlock|limit|name|permit|reject|transfer|claim`. The channel
  is deleted automatically once everyone leaves it.

All commands are slash commands. Config/state is stored in small JSON files
under `data/` (no external database needed).

## 1. Requirements

- Python 3.10+
- **ffmpeg** installed and on your system PATH (required for music/TTS playback)
  - Windows: download from https://ffmpeg.org/download.html and add to PATH
  - macOS: `brew install ffmpeg`
  - Debian/Ubuntu: `sudo apt install ffmpeg`
- **davey** (installed via `requirements.txt`) — Discord's newer mandatory
  end-to-end voice encryption (DAVE protocol). Without it, joining voice
  channels fails with `RuntimeError: davey library needed in order to use
  voice`. It's a compiled package with prebuilt wheels, so a normal
  `pip install` handles it.

## 2. Install

```bash
cd discord-bot
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:

- `DISCORD_TOKEN` — from the [Discord Developer Portal](https://discord.com/developers/applications) → your application → **Bot** → Reset Token
- `DEV_GUILD_ID` *(optional)* — your test server's ID, for instant slash-command sync while developing
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` *(optional)* — only needed if you want `/play` to accept `open.spotify.com` links. Free at the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). These alone are enough for single **track** links.
- `SPOTIFY_REFRESH_TOKEN` *(optional, but required for playlist/album links)* — Spotify's Nov 2024 API changes now require a real user login to look up a playlist's or album's tracks; an app-only token 401s. Generate this once:
  1. In your Spotify dashboard app → **Edit Settings**, add the Redirect URI `http://127.0.0.1:8888/callback`
  2. Run `python get_spotify_refresh_token.py` — it opens a browser, you log in with Spotify and click Agree, then it prints a refresh token
  3. Paste that into `.env` as `SPOTIFY_REFRESH_TOKEN` and restart the bot

  You only need to do this once — the bot silently renews the token itself from then on.

### Required Discord Developer Portal settings

Under your application → **Bot**:
- Enable **Server Members Intent**
- Enable **Message Content Intent**

Under **OAuth2 → URL Generator**, select scope `bot` and `applications.commands`,
and permissions at minimum: Manage Roles, Kick Members, Ban Members,
Moderate Members, Manage Messages, Manage Guild (for verification-level
changes), Connect, Speak, View Channels, Send Messages, Read Message History.
Use the generated URL to invite the bot.

**Role position matters:** for autorole/anti-nuke role-stripping to work,
the bot's own role must be positioned *above* any role it needs to
manage in Server Settings → Roles.

## 4. Customize the word filter

Edit `bad.txt` (plain text, one word/phrase per line, `#` for comments) or
manage it live in Discord with `/badword add`, `/badword remove`,
`/badword list`, `/badword reload`.

## 5. Run

```bash
python main.py
```

## 6. Control panel

Run **`/panel`** in your server (needs **Manage Server** permission) for a
click-through dashboard covering every feature below — no need to remember
command syntax. It's a set of buttons/dropdowns/forms attached to one
message: Moderation, Autorole, Word Filter, Anti-Raid, Anti-Nuke, Music,
Economy, Bot Profile, and Text-to-Speech each get their own page with a
"◀ Back" button. The panel expires
after 3 minutes of inactivity — just run `/panel` again if that happens.

## 7. Quick command reference

Run `/help` in your server once the bot is online for a full in-Discord list.

| Category | Commands |
|---|---|
| Moderation | `/kick` `/ban` `/unban` `/timeout` `/untimeout` `/warn` `/warnings` `/clearwarnings` `/purge` `/setlogchannel` |
| Autorole | `/autorole` `/autorole-off` `/roleall` |
| Word filter | `/badword list\|add\|remove\|reload` |
| Anti-raid | `/raidmode on\|off` `/antiraid-config` |
| Anti-nuke | `/antinuke config` `/antinuke whitelist-add\|whitelist-remove` |
| Music | `/join` `/leave` `/play` `/skip` `/pause` `/resume` `/queue` `/stop` |
| Text-to-Speech | `/tts` `/tts-vcchat` `/tts-autoread` |
| Gambling | `/balance` `/daily` `/coinflip` `/dice` `/slots` `/blackjack` |

## Notes & limitations

- This is a solid starting framework, not a hardened security product —
  anti-nuke/anti-raid reduce blast radius and react quickly, but nothing can
  fully prevent damage from a compromised owner account or a bot with more
  permissions than yours.
- Storage is flat JSON files (`data/*.json`) — fine for small/medium
  servers; move to a real database if you need high concurrency or run
  many shards.
- Gambling commands use a fake, server-local currency only — no real money
  is involved anywhere in this code.
- Music streams audio via `yt-dlp` + `ffmpeg`; you are responsible for
  complying with YouTube's, SoundCloud's, and Spotify's Terms of Service in
  how you deploy and use this feature.
- **Audio quality:** the bot requests the highest-bitrate source stream
  available and matches ffmpeg's output to Discord voice's native 48kHz
  stereo format (no extra resampling). The final ceiling is still your
  voice channel's bitrate — unboosted servers cap around 96kbps, boosted
  servers up to 384kbps. That's a Discord server setting, not something the
  bot can override.
