"""
Lightweight JSON-backed per-guild configuration store.

Not a database -- fine for small/medium servers. Swap this out for
SQLite/Postgres if you need heavier concurrency.
"""

import json
import os
import threading

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

_LOCK = threading.Lock()


class JSONStore:
    """A tiny thread-safe wrapper around a JSON file of the form
    { "<guild_id>": { ...arbitrary settings... } }
    """

    def __init__(self, filename: str):
        self.path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(self.path):
            with open(self.path, "w") as f:
                json.dump({}, f)

    def _read(self) -> dict:
        with _LOCK:
            with open(self.path, "r") as f:
                return json.load(f)

    def _write(self, data: dict):
        with _LOCK:
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)

    def get_guild(self, guild_id: int) -> dict:
        data = self._read()
        return data.get(str(guild_id), {})

    def set_guild_key(self, guild_id: int, key: str, value):
        data = self._read()
        gid = str(guild_id)
        data.setdefault(gid, {})
        data[gid][key] = value
        self._write(data)

    def get_guild_key(self, guild_id: int, key: str, default=None):
        return self.get_guild(guild_id).get(key, default)

    def clear_guild(self, guild_id: int):
        data = self._read()
        data[str(guild_id)] = {}
        self._write(data)

    def all(self) -> dict:
        return self._read()


# Shared stores used across cogs
guild_config = JSONStore("guild_config.json")   # autorole, log channel, thresholds...
warns_store = JSONStore("warns.json")           # moderation warnings
economy_store = JSONStore("economy.json")       # gambling / currency balances
xp_store = JSONStore("xp.json")                 # leveling XP totals
bot_settings = JSONStore("bot_settings.json")   # bot-wide profile/presence (nickname is per-guild, status is global)

GLOBAL_KEY = 0  # pseudo "guild id" used for bot-wide (non-guild-specific) settings in bot_settings

ACTIVITY_TYPE_NAMES = ["playing", "watching", "listening", "competing"]
STATUS_NAMES = ["online", "idle", "dnd", "invisible"]
