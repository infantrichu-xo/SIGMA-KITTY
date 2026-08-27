"""
Main entry point for the Discord bot.

Loads config/env, sets up intents, loads all cogs, and starts the bot.
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import bot_settings, GLOBAL_KEY
from cogs.tickets import TicketOpenView, TicketCloseView

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("PREFIX", "!")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------
# NOTE: "Server Members Intent" and "Message Content Intent" must ALSO be
# enabled for your bot in the Discord Developer Portal -> Bot -> Privileged
# Gateway Intents, or the bot will fail to connect / see message content.
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.moderation = True  # ban/unban audit events

ACTIVITY_TYPES = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}
STATUS_TYPES = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}


async def apply_saved_presence(bot: commands.Bot):
    """Applies the bio/presence saved via the /panel Bot Profile page, or a
    sensible default if nothing has been configured yet."""
    cfg = bot_settings.get_guild(GLOBAL_KEY)
    activity_type = ACTIVITY_TYPES.get(cfg.get("activity_type", "watching"), discord.ActivityType.watching)
    activity_text = cfg.get("activity_text", "over the server 👁️")
    status = STATUS_TYPES.get(cfg.get("status", "online"), discord.Status.online)
    await bot.change_presence(
        status=status,
        activity=discord.Activity(type=activity_type, name=activity_text),
    )


class ModBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(PREFIX),
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        # Load every cog in ./cogs
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        for filename in sorted(os.listdir(cogs_dir)):
            if filename.endswith(".py") and not filename.startswith("_"):
                ext = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(ext)
                    log.info("Loaded extension: %s", ext)
                except Exception:
                    log.exception("Failed to load extension %s", ext)

        # Re-register the ticket buttons as persistent views so they keep
        # working on messages sent before this restart (they're matched by
        # custom_id, not tied to a specific interaction/message object).
        self.add_view(TicketOpenView())
        self.add_view(TicketCloseView())

        # Sync slash commands globally. For instant per-guild sync during
        # development, set DEV_GUILD_ID in your .env.
        dev_guild_id = os.getenv("DEV_GUILD_ID")
        if dev_guild_id:
            guild = discord.Object(id=int(dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced slash commands to dev guild %s", dev_guild_id)
        else:
            await self.tree.sync()
            log.info("Synced slash commands globally (can take up to 1hr to propagate)")

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await apply_saved_presence(self)


bot = ModBot()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ You don't have permission to do that.")
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ Slow down, try again in {error.retry_after:.1f}s.")
        return
    log.exception("Unhandled command error", exc_info=error)
    try:
        await ctx.reply(f"⚠️ Something went wrong: `{error}`")
    except discord.HTTPException:
        pass


def main():
    if not TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
    asyncio.run(bot.start(TOKEN))


if __name__ == "__main__":
    main()
