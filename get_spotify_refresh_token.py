"""
One-time setup script: authorizes this bot against YOUR Spotify account and
prints a refresh token to save in .env as SPOTIFY_REFRESH_TOKEN.

Why this is needed: as of Spotify's Nov 2024 API changes, looking up a
playlist's or album's tracks requires a real user login -- the simple
Client Credentials (app-only) auth that used to work for this no longer
does, even for public playlists. This script does that login ONCE, on
your machine, and gives the bot a long-lived refresh token so it never
needs you to log in again afterward (it silently renews itself).

Usage:
  1. pip install -r requirements.txt   (spotipy + python-dotenv)
  2. Make sure SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are already set
     in your .env (get them free at https://developer.spotify.com/dashboard).
  3. In that same Spotify dashboard app, click "Edit Settings" and add
     this exact Redirect URI:  http://127.0.0.1:8888/callback
     (or set SPOTIFY_REDIRECT_URI in .env to something else and add THAT
     instead -- they must match exactly).
  4. Run:  python get_spotify_refresh_token.py
     A browser tab opens -- log in with the Spotify account you want the
     bot to use, click Agree, then it'll redirect back and this script
     will print your refresh token.
  5. Copy that value into .env as SPOTIFY_REFRESH_TOKEN and restart the bot.

This only needs to be run once (or again if the token is ever revoked).
"""

import os

from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise SystemExit(
            "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET aren't set in .env yet -- "
            "set those first (see the docstring at the top of this file)."
        )

    sp_oauth = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope="playlist-read-private playlist-read-collaborative",
        open_browser=True,
    )

    print(f"Redirect URI in use: {REDIRECT_URI}")
    print("(this must be added exactly, under Edit Settings, in your Spotify "
          "dashboard app -- otherwise Spotify will refuse the login)\n")
    print("Opening your browser to log in with Spotify...")
    print("If it doesn't open automatically, or you're on a headless/remote "
          "machine, copy the URL it prints below into a browser yourself, "
          "log in, and then paste the FULL URL you get redirected to back "
          "here when prompted.\n")

    token_info = sp_oauth.get_access_token(as_dict=True)

    print("\n✅ Success! Add this line to your .env file:\n")
    print(f"SPOTIFY_REFRESH_TOKEN={token_info['refresh_token']}\n")
    print("Then restart the bot. Playlist and album links should work now.")


if __name__ == "__main__":
    main()
