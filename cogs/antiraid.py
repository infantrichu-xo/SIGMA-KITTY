"""
Anti-raid: watches the rate of new joins. If too many members join within a
short window (a "raid"), the server is automatically locked down:
 - verification level bumped to `highest`
 - new joins younger than a configurable account-age are kicked
 - alert posted to the log channel
Mods can end the lockdown manually with /raidmode off.

Defaults (overridable with /antiraid config):
 - JOIN_THRESHOLD joins within JOIN_WINDOW seconds triggers lockdown
 - Minimum account age required to stay, during a raid
"""

import datetime
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import guild_config

DEFAULT_JOIN_THRESHOLD = 6     # number of joins...
DEFAULT_JOIN_WINDOW = 10       # ...within this many seconds triggers a raid
DEFAULT_MIN_ACCOUNT_AGE_HOURS = 24  # accounts younger than this get kicked during lockdown


class AntiRaid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> list[timestamps]
        self.recent_joins: dict[int, list[float]] = {}

    def _cfg(self, guild_id: int, key: str, default):
        return guild_config.get_guild_key(guild_id, key, default)

    async def _log(self, guild: discord.Guild, embed: discord.Embed):
        log_channel_id = guild_config.get_guild_key(guild.id, "log_channel_id")
        if not log_channel_id:
            return
        channel = guild.get_channel(log_channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        now = time.time()
        window = self._cfg(guild.id, "raid_join_window", DEFAULT_JOIN_WINDOW)
        threshold = self._cfg(guild.id, "raid_join_threshold", DEFAULT_JOIN_THRESHOLD)

        joins = self.recent_joins.setdefault(guild.id, [])
        joins.append(now)
        # drop old timestamps outside the window
        joins[:] = [t for t in joins if now - t <= window]

        already_locked = guild_config.get_guild_key(guild.id, "raid_lockdown", False)

        # During an active lockdown, kick suspiciously new accounts
        if already_locked:
            min_age_hours = self._cfg(guild.id, "raid_min_account_age_hours", DEFAULT_MIN_ACCOUNT_AGE_HOURS)
            age = datetime.datetime.now(datetime.timezone.utc) - member.created_at
            if age < datetime.timedelta(hours=min_age_hours):
                try:
                    await member.kick(reason="Anti-raid lockdown: account too new")
                    await self._log(guild, discord.Embed(
                        title="🛡️ Anti-raid kicked new-account joiner",
                        description=f"{member} (`{member.id}`) — account age {age}",
                        color=discord.Color.red()))
                except discord.Forbidden:
                    pass
            return

        if len(joins) >= threshold:
            await self._trigger_lockdown(guild, len(joins), window)

    async def _trigger_lockdown(self, guild: discord.Guild, join_count: int, window: int):
        guild_config.set_guild_key(guild.id, "raid_lockdown", True)
        try:
            await guild.edit(verification_level=discord.VerificationLevel.highest,
                              reason="Anti-raid: possible raid detected")
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="🚨 RAID DETECTED",
            description=(
                f"{join_count} members joined within {window}s.\n"
                f"Verification level raised to **highest** and new-account "
                f"kicking is now active.\nUse `/raidmode off` once things "
                f"calm down."
            ),
            color=discord.Color.dark_red(),
        )
        await self._log(guild, embed)

    raidmode = app_commands.Group(name="raidmode", description="Manually control raid lockdown")

    @raidmode.command(name="on", description="Manually enable raid lockdown")
    @app_commands.checks.has_permissions(administrator=True)
    async def raidmode_on(self, interaction: discord.Interaction):
        await self._trigger_lockdown(interaction.guild, 0, 0)
        await interaction.response.send_message("🚨 Raid lockdown manually enabled.")

    @raidmode.command(name="off", description="Disable raid lockdown")
    @app_commands.checks.has_permissions(administrator=True)
    async def raidmode_off(self, interaction: discord.Interaction):
        guild_config.set_guild_key(interaction.guild.id, "raid_lockdown", False)
        try:
            await interaction.guild.edit(verification_level=discord.VerificationLevel.medium,
                                          reason="Anti-raid lockdown lifted")
        except discord.Forbidden:
            pass
        await interaction.response.send_message("✅ Raid lockdown disabled, verification level restored to medium.")

    @app_commands.command(name="antiraid-config", description="Configure anti-raid thresholds")
    @app_commands.checks.has_permissions(administrator=True)
    async def antiraid_config(
        self,
        interaction: discord.Interaction,
        join_threshold: int | None = None,
        join_window_seconds: int | None = None,
        min_account_age_hours: int | None = None,
    ):
        if join_threshold is not None:
            guild_config.set_guild_key(interaction.guild.id, "raid_join_threshold", join_threshold)
        if join_window_seconds is not None:
            guild_config.set_guild_key(interaction.guild.id, "raid_join_window", join_window_seconds)
        if min_account_age_hours is not None:
            guild_config.set_guild_key(interaction.guild.id, "raid_min_account_age_hours", min_account_age_hours)

        cfg = guild_config.get_guild(interaction.guild.id)
        await interaction.response.send_message(
            f"✅ Anti-raid config:\n"
            f"- Join threshold: {cfg.get('raid_join_threshold', DEFAULT_JOIN_THRESHOLD)}\n"
            f"- Window: {cfg.get('raid_join_window', DEFAULT_JOIN_WINDOW)}s\n"
            f"- Min account age (during lockdown): {cfg.get('raid_min_account_age_hours', DEFAULT_MIN_ACCOUNT_AGE_HOURS)}h"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiRaid(bot))
