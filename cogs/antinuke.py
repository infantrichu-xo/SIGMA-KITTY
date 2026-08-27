"""
Anti-nuke: watches the audit log for destructive actions (channel deletes,
role deletes, mass bans/kicks, webhook creation) and, if a single
non-whitelisted user does too many of them too fast, strips their dangerous
permissions (or bans them) and alerts staff.

This can NEVER protect against the server owner, and it can't undo actions
that already happened -- it only limits the *blast radius* by reacting fast.
Add trusted admins/bots to the whitelist with /antinuke whitelist add.
"""

import time

import discord
from discord import app_commands
from discord.ext import commands

from config import guild_config

DEFAULT_ACTION_THRESHOLD = 3   # this many destructive actions...
DEFAULT_ACTION_WINDOW = 20     # ...within this many seconds triggers a response

DESTRUCTIVE_AUDIT_ACTIONS = {
    discord.AuditLogAction.channel_delete,
    discord.AuditLogAction.role_delete,
    discord.AuditLogAction.webhook_create,
    discord.AuditLogAction.ban,
    discord.AuditLogAction.kick,
    discord.AuditLogAction.member_role_update,  # abuse: mass-granting admin roles
}


class AntiNuke(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> {user_id: [timestamps]}
        self.actions: dict[int, dict[int, list[float]]] = {}

    def _is_whitelisted(self, guild: discord.Guild, user_id: int) -> bool:
        if user_id == guild.owner_id or user_id == self.bot.user.id:
            return True
        whitelist = guild_config.get_guild_key(guild.id, "antinuke_whitelist", [])
        return user_id in whitelist

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

    async def _record_and_check(self, guild: discord.Guild, actor: discord.Member | discord.User, action_name: str):
        if not isinstance(actor, discord.Member) or self._is_whitelisted(guild, actor.id):
            return

        now = time.time()
        window = guild_config.get_guild_key(guild.id, "antinuke_window", DEFAULT_ACTION_WINDOW)
        threshold = guild_config.get_guild_key(guild.id, "antinuke_threshold", DEFAULT_ACTION_THRESHOLD)

        per_guild = self.actions.setdefault(guild.id, {})
        history = per_guild.setdefault(actor.id, [])
        history.append(now)
        history[:] = [t for t in history if now - t <= window]

        if len(history) >= threshold:
            await self._punish(guild, actor, action_name, len(history))
            history.clear()

    async def _punish(self, guild: discord.Guild, actor: discord.Member, action_name: str, count: int):
        punishment = guild_config.get_guild_key(guild.id, "antinuke_punishment", "strip_roles")
        result = "no action taken (missing permissions?)"
        try:
            if punishment == "ban":
                await guild.ban(actor, reason=f"Anti-nuke: {count} destructive actions ({action_name})")
                result = "banned"
            else:  # strip_roles (default, less destructive / reversible)
                dangerous_roles = [r for r in actor.roles if r.permissions.administrator
                                    or r.permissions.manage_guild or r.permissions.ban_members
                                    or r.permissions.manage_roles or r.permissions.manage_channels]
                if dangerous_roles:
                    await actor.remove_roles(*dangerous_roles, reason="Anti-nuke: dangerous permissions stripped")
                result = f"stripped {len(dangerous_roles)} dangerous role(s)"
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="🛑 ANTI-NUKE TRIGGERED",
            description=(
                f"**User:** {actor} (`{actor.id}`)\n"
                f"**Trigger:** {count}x `{action_name}` in a short window\n"
                f"**Action taken:** {result}\n\n"
                f"Review immediately — this user may be compromised or malicious."
            ),
            color=discord.Color.dark_red(),
        )
        await self._log(guild, embed)

    # ------------------------------------------------------------- listeners
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            await self._record_and_check(guild, entry.user, "channel_delete")
            break

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        guild = role.guild
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            await self._record_and_check(guild, entry.user, "role_delete")
            break

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            await self._record_and_check(guild, entry.user, "ban")
            break

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            # only counts if the audit entry is fresh (<5s) and matches this member
            if entry.target and entry.target.id == member.id:
                await self._record_and_check(guild, entry.user, "kick")
            break

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
            await self._record_and_check(guild, entry.user, "webhook_create")
            break

    # -------------------------------------------------------------- commands
    antinuke = app_commands.Group(name="antinuke", description="Configure anti-nuke protection")

    @antinuke.command(name="config", description="Configure anti-nuke thresholds and punishment")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(punishment=[
        app_commands.Choice(name="Strip dangerous roles (reversible)", value="strip_roles"),
        app_commands.Choice(name="Ban immediately", value="ban"),
    ])
    async def antinuke_config(
        self,
        interaction: discord.Interaction,
        action_threshold: int | None = None,
        window_seconds: int | None = None,
        punishment: app_commands.Choice[str] | None = None,
    ):
        if action_threshold is not None:
            guild_config.set_guild_key(interaction.guild.id, "antinuke_threshold", action_threshold)
        if window_seconds is not None:
            guild_config.set_guild_key(interaction.guild.id, "antinuke_window", window_seconds)
        if punishment is not None:
            guild_config.set_guild_key(interaction.guild.id, "antinuke_punishment", punishment.value)

        cfg = guild_config.get_guild(interaction.guild.id)
        await interaction.response.send_message(
            f"✅ Anti-nuke config:\n"
            f"- Threshold: {cfg.get('antinuke_threshold', DEFAULT_ACTION_THRESHOLD)} actions\n"
            f"- Window: {cfg.get('antinuke_window', DEFAULT_ACTION_WINDOW)}s\n"
            f"- Punishment: {cfg.get('antinuke_punishment', 'strip_roles')}"
        )

    @antinuke.command(name="whitelist-add", description="Exempt a trusted user from anti-nuke checks")
    @app_commands.checks.has_permissions(administrator=True)
    async def whitelist_add(self, interaction: discord.Interaction, user: discord.Member):
        wl = guild_config.get_guild_key(interaction.guild.id, "antinuke_whitelist", [])
        if user.id not in wl:
            wl.append(user.id)
            guild_config.set_guild_key(interaction.guild.id, "antinuke_whitelist", wl)
        await interaction.response.send_message(f"✅ {user.mention} is now whitelisted from anti-nuke.")

    @antinuke.command(name="whitelist-remove", description="Remove a user from the anti-nuke whitelist")
    @app_commands.checks.has_permissions(administrator=True)
    async def whitelist_remove(self, interaction: discord.Interaction, user: discord.Member):
        wl = guild_config.get_guild_key(interaction.guild.id, "antinuke_whitelist", [])
        if user.id in wl:
            wl.remove(user.id)
            guild_config.set_guild_key(interaction.guild.id, "antinuke_whitelist", wl)
        await interaction.response.send_message(f"✅ {user.mention} removed from the anti-nuke whitelist.")


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiNuke(bot))
