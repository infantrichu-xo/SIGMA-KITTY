"""
Standard moderation commands: kick, ban, unban, timeout/mute, warn, clear.
"""

import datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import warns_store, guild_config

# Actions an offense preset (configured in /panel -> Moderation -> Warn
# Offenses) can automatically apply on top of logging the warning.
OFFENSE_ACTIONS = ["none", "timeout", "kick", "ban"]


def get_offenses(guild_id: int) -> list[dict]:
    """Each offense: {'name', 'reason', 'action' in OFFENSE_ACTIONS, 'duration'
    (timeout minutes, only used when action == 'timeout')}."""
    return guild_config.get_guild_key(guild_id, "warn_offenses", [])


def find_offense(guild_id: int, name: str) -> dict | None:
    name = (name or "").strip().lower()
    for o in get_offenses(guild_id):
        if o["name"].strip().lower() == name:
            return o
    return None


async def _log(guild: discord.Guild, embed: discord.Embed):
    log_channel_id = guild_config.get_guild_key(guild.id, "log_channel_id")
    if not log_channel_id:
        return
    channel = guild.get_channel(log_channel_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setlogchannel", description="Set the channel used for moderation/security logs")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_config.set_guild_key(interaction.guild.id, "log_channel_id", channel.id)
        await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.")

    @app_commands.command(name="kick", description="Kick a member")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ You can't kick someone with an equal/higher role.", ephemeral=True)
            return
        await member.kick(reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"👢 Kicked **{member}**. Reason: {reason}")
        await _log(interaction.guild, discord.Embed(
            title="Member kicked", color=discord.Color.orange(),
            description=f"**Member:** {member} (`{member.id}`)\n**By:** {interaction.user}\n**Reason:** {reason}"))

    @app_commands.command(name="ban", description="Ban a member")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given", delete_days: int = 0):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ You can't ban someone with an equal/higher role.", ephemeral=True)
            return
        await member.ban(reason=f"{interaction.user}: {reason}", delete_message_days=max(0, min(delete_days, 7)))
        await interaction.response.send_message(f"🔨 Banned **{member}**. Reason: {reason}")
        await _log(interaction.guild, discord.Embed(
            title="Member banned", color=discord.Color.red(),
            description=f"**Member:** {member} (`{member.id}`)\n**By:** {interaction.user}\n**Reason:** {reason}"))

    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str):
        try:
            user = discord.Object(id=int(user_id))
            await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user}")
            await interaction.response.send_message(f"✅ Unbanned user ID `{user_id}`.")
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("❌ Couldn't find a ban for that user ID.", ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout (mute) a member for a number of minutes")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason given"):
        duration = datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"🔇 Timed out **{member}** for {minutes} minute(s). Reason: {reason}")
        await _log(interaction.guild, discord.Embed(
            title="Member timed out", color=discord.Color.orange(),
            description=f"**Member:** {member} (`{member.id}`)\n**By:** {interaction.user}\n**Duration:** {minutes}m\n**Reason:** {reason}"))

    @app_commands.command(name="untimeout", description="Remove a timeout from a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None, reason=f"Untimed out by {interaction.user}")
        await interaction.response.send_message(f"🔊 Removed timeout from **{member}**.")

    @app_commands.command(name="warn", description="Warn a member for a preset offense, or a custom reason")
    @app_commands.describe(
        offense="Pick a preset offense (configured in /panel -> Moderation), or type a custom reason",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, offense: str = "No reason given"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ You can't warn someone with an equal/higher role.", ephemeral=True)
            return

        preset = find_offense(interaction.guild.id, offense)
        reason = preset["reason"] if preset else offense

        warns = warns_store.get_guild_key(interaction.guild.id, str(member.id), [])
        warns.append({
            "reason": reason,
            "offense": preset["name"] if preset else None,
            "by": interaction.user.id,
            "at": datetime.datetime.utcnow().isoformat(),
        })
        warns_store.set_guild_key(interaction.guild.id, str(member.id), warns)

        action_note = ""
        if preset and preset.get("action") not in (None, "none"):
            action = preset["action"]
            try:
                if action == "timeout":
                    minutes = int(preset.get("duration") or 10)
                    await member.timeout(datetime.timedelta(minutes=minutes),
                                          reason=f"Auto-action for offense '{preset['name']}' by {interaction.user}")
                    action_note = f" and timed out for {minutes}m"
                elif action == "kick":
                    await member.kick(reason=f"Auto-action for offense '{preset['name']}' by {interaction.user}")
                    action_note = " and kicked"
                elif action == "ban":
                    await member.ban(reason=f"Auto-action for offense '{preset['name']}' by {interaction.user}")
                    action_note = " and banned"
            except discord.Forbidden:
                action_note = " (⚠️ couldn't apply the auto-action -- check my role position/permissions)"

        await interaction.response.send_message(
            f"⚠️ Warned **{member}** ({len(warns)} total){action_note}. Reason: {reason}"
        )
        await _log(interaction.guild, discord.Embed(
            title="Member warned", color=discord.Color.yellow(),
            description=(
                f"**Member:** {member} (`{member.id}`)\n**By:** {interaction.user}\n"
                f"**Offense:** {preset['name'] if preset else 'custom'}\n**Reason:** {reason}\n"
                f"**Auto-action:** {preset['action'] if preset else 'none'}{action_note}\n"
                f"**Total warns:** {len(warns)}"
            )))

    @warn.autocomplete("offense")
    async def warn_offense_autocomplete(self, interaction: discord.Interaction, current: str):
        offenses = get_offenses(interaction.guild.id)
        current = (current or "").lower()
        matches = [o["name"] for o in offenses if current in o["name"].lower()]
        return [app_commands.Choice(name=n, value=n) for n in matches[:25]]

    @app_commands.command(name="warnings", description="View a member's warnings")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = warns_store.get_guild_key(interaction.guild.id, str(member.id), [])
        if not warns:
            await interaction.response.send_message(f"{member} has no warnings.", ephemeral=True)
            return
        lines = [f"**{i+1}.** {w['reason']} — <@{w['by']}> ({w['at'][:10]})" for i, w in enumerate(warns)]
        embed = discord.Embed(title=f"Warnings for {member}", description="\n".join(lines), color=discord.Color.yellow())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        warns_store.set_guild_key(interaction.guild.id, str(member.id), [])
        await interaction.response.send_message(f"✅ Cleared warnings for **{member}**.")

    @app_commands.command(name="purge", description="Bulk delete messages in this channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} message(s).", ephemeral=True)

    @app_commands.command(name="lock", description="Lock a text channel so @everyone can't send messages")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "No reason given"):
        channel = channel or interaction.channel
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"🔒 Locked {channel.mention}. Reason: {reason}")
        await _log(interaction.guild, discord.Embed(
            title="Text channel locked", color=discord.Color.orange(),
            description=f"**Channel:** {channel.mention}\n**By:** {interaction.user}\n**Reason:** {reason}"))

    @app_commands.command(name="unlock", description="Unlock a text channel, restoring @everyone's send-messages permission")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        channel = channel or interaction.channel
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None  # reset to whatever it inherits from category/server defaults
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {interaction.user}")
        await interaction.response.send_message(f"🔓 Unlocked {channel.mention}.")
        await _log(interaction.guild, discord.Embed(
            title="Text channel unlocked", color=discord.Color.green(),
            description=f"**Channel:** {channel.mention}\n**By:** {interaction.user}"))

    @app_commands.command(name="lockvc", description="Lock a voice channel so @everyone can't join")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lockvc(self, interaction: discord.Interaction, channel: discord.VoiceChannel = None, reason: str = "No reason given"):
        channel = channel or (interaction.user.voice.channel if interaction.user.voice else None)
        if channel is None:
            await interaction.response.send_message(
                "❌ Specify a voice channel, or join one first.", ephemeral=True)
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"🔒 Locked voice channel **{channel.name}**. Reason: {reason}")
        await _log(interaction.guild, discord.Embed(
            title="Voice channel locked", color=discord.Color.orange(),
            description=f"**Channel:** {channel.name}\n**By:** {interaction.user}\n**Reason:** {reason}"))

    @app_commands.command(name="unlockvc", description="Unlock a voice channel, restoring @everyone's connect permission")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlockvc(self, interaction: discord.Interaction, channel: discord.VoiceChannel = None):
        channel = channel or (interaction.user.voice.channel if interaction.user.voice else None)
        if channel is None:
            await interaction.response.send_message(
                "❌ Specify a voice channel, or join one first.", ephemeral=True)
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {interaction.user}")
        await interaction.response.send_message(f"🔓 Unlocked voice channel **{channel.name}**.")
        await _log(interaction.guild, discord.Embed(
            title="Voice channel unlocked", color=discord.Color.green(),
            description=f"**Channel:** {channel.name}\n**By:** {interaction.user}"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
