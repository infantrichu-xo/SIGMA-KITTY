"""
Shared helper for locating an ffmpeg binary, for use by any cog that plays
audio (Music, TTS).

Tries, in order:
  1. FFMPEG_PATH in .env, if you want to pin an exact path
  2. `ffmpeg` on the system PATH (normal installs, and most Pterodactyl-based
     panels -- Wispbyte included -- ship ffmpeg preinstalled in the
     Python/discord.py egg's container image, so this is usually all you need)
  3. A static ffmpeg binary bundled by the `imageio-ffmpeg` pip package --
     no root/admin access, no apt/choco/manual download needed. This is the
     fallback that matters on hosts like Wispbyte where you can't install
     system packages yourself: `pip install imageio-ffmpeg` (already in
     requirements.txt) downloads a working ffmpeg binary into site-packages
     the first time it's used.

Call get_ffmpeg_path() and pass the result as `executable=` to
discord.FFmpegPCMAudio(...).
"""

import os
import shutil

_cached_path: str | None = None


def get_ffmpeg_path() -> str:
    global _cached_path
    if _cached_path:
        return _cached_path

    env_path = os.getenv("FFMPEG_PATH")
    if env_path and os.path.isfile(env_path):
        _cached_path = env_path
        return _cached_path

    which_path = shutil.which("ffmpeg")
    if which_path:
        _cached_path = which_path
        return _cached_path

    try:
        import imageio_ffmpeg
        _cached_path = imageio_ffmpeg.get_ffmpeg_exe()
        return _cached_path
    except Exception as e:
        raise RuntimeError(
            "Couldn't find ffmpeg. Install it and put it on PATH, set "
            "FFMPEG_PATH in .env to an exact path, or make sure "
            "`imageio-ffmpeg` is installed (it's in requirements.txt) so a "
            "bundled static binary can be used instead -- no admin/root "
            "needed."
        ) from e
