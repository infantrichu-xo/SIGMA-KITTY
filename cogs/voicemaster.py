"""
"Join to Create" temporary voice channels (a la VoiceMaster).

An admin picks one existing voice channel as the trigger (via /panel ->
Voice Master, or /voicemaster-setup). Whenever a member joins that trigger
channel, the bot instantly creates a brand new voice channel for them
(named from a template), moves them into it, and gives them owner controls
over it:

  /voice lock              -- stop new people from joining
  /voice unlock             -- allow anyone back in
  /voice limit <0-99>       -- cap how many people can join (0 = unlimited)
  /voice name <text>        -- rename the channel
  /voice permit <member>    -- let a specific member in even while locked
  /voice reject <member>    -- kick + block a specific member
  /voice claim              -- take ownership if the original owner left
  /voice transfer <member>  -- hand ownership to someone else in the channel

The channel is deleted automatically once everyone leaves it. Ownership is
tracked in memory only (like the rest of the panel's live state) -- if the
bot restarts while temp channels exist, they'll still get cleaned up once
they empty out, they just won't have an owner until someone runs
`/voice claim`.
"""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from config import guild_config

DEFAULT_NAME_TEMPLATE = "{user}'s Channel"


class VoiceMaster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # temp voice channel id -> current owner's member id
        self.owned: dict[int, int] = {}
        # channels currently mid-deletion, to avoid double-delete races
        self._deleting: set[int] = set()

    # ------------------------------------------------------------ helpers
    def is_temp_channel(self, channel_id: int) -> bool:
        return channel_id in self.owned

    def owner_of(self, channel_id: int) -> int | None:
        return self.owned.get(channel_id)

    async def _create_temp_channel(self, member: discord.Member, trigger: discord.VoiceChannel):
        guild = member.guild
        cfg = guild_config.get_guild(guild.id)

        category_id = cfg.get("vm_category_id")
        category = guild.get_channel(category_id) if category_id else trigger.category

        template = cfg.get("vm_name_template", DEFAULT_NAME_TEMPLATE)
        try:
            name = template.format(user=member.display_name)
        except (KeyError, IndexError):
            name = DEFAULT_NAME_TEMPLATE.format(user=member.display_name)
        name = name[:100] or f"{member.display_name}'s Channel"

        default_limit = int(cfg.get("vm_default_limit", 0) or 0)

        overwrites = dict(trigger.overwrites)
        overwrites[member] = discord.PermissionOverwrite(
            connect=True, manage_channels=True, move_members=True, mute_members=True, deafen_members=True
        )

        try:
            new_channel = await guild.create_voice_channel(
                name=name,
                category=category,
                user_limit=default_limit,
                overwrites=overwrites,
                reason=f"Join-to-create channel for {member}",
            )
        except discord.Forbidden:
            return

        self.owned[new_channel.id] = member.id

        try:
            await member.move_to(new_channel)
        except (discord.Forbidden, discord.HTTPException):
            # If we can't move them, don't leave an orphaned empty channel.
            self.owned.pop(new_channel.id, None)
            try:
                await new_channel.delete(reason="Failed to move member in")
            except discord.HTTPException:
                pass
            return

        try:
            await new_channel.send(
                embed=discord.Embed(
                    title="🔊 Your channel is ready",
                    description=(
                        f"{member.mention}, this channel is yours. Manage it with:\n"
                        "`/voice lock` · `/voice unlock` · `/voice limit` · `/voice name` · "
                        "`/voice permit` · `/voice reject` · `/voice transfer` · `/voice claim`"
                    ),
                    color=discord.Color.blurple(),
                )
            )
        except discord.HTTPException:
            pass

    async def _maybe_delete_empty(self, channel: discord.VoiceChannel):
        if channel.id not in self.owned or channel.id in self._deleting:
            return
        self._deleting.add(channel.id)
        try:
            # Short delay so a quick reconnect (e.g. brief connection blip)
            # doesn't nuke the channel from under someone.
            await asyncio.sleep(2)
            refreshed = channel.guild.get_channel(channel.id)
            if refreshed is None:
                self.owned.pop(channel.id, None)
                return
            if len(refreshed.members) == 0:
                self.owned.pop(refreshed.id, None)
                try:
                    await refreshed.delete(reason="Join-to-create channel emptied out")
                except discord.HTTPException:
                    pass
        finally:
            self._deleting.discard(channel.id)

    # ------------------------------------------------------------ listener
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        cfg = guild_config.get_guild(guild.id)
        trigger_id = cfg.get("vm_trigger_channel_id")

        # Joined the trigger channel -> spin up a new channel for them.
        if (
            cfg.get("vm_enabled")
            and trigger_id
            and after.channel is not None
            and after.channel.id == trigger_id
            and (before.channel is None or before.channel.id != trigger_id)
        ):
            await self._create_temp_channel(member, after.channel)

        # Left a temp channel -> delete it once it's empty.
        if before.channel is not None and before.channel.id in self.owned:
            if after.channel is None or after.channel.id != before.channel.id:
                await self._maybe_delete_empty(before.channel)

    # --------------------------------------------------------------- /voice
    voice = app_commands.Group(name="voice", description="Manage your join-to-create voice channel")

    def _current_owned_channel(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice or not member.voice.channel:
            return None
        channel = member.voice.channel
        return channel if channel.id in self.owned else None

    async def _require_owner(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        channel = self._current_owned_channel(interaction)
        if channel is None:
            await interaction.response.send_message(
                "❌ Join a channel created by the join-to-create system first.", ephemeral=True
            )
            return None
        if self.owned.get(channel.id) != interaction.user.id:
            await interaction.response.send_message(
                "❌ You're not the owner of this channel. Ask them to `/voice transfer` it, "
                "or use `/voice claim` if they've left.", ephemeral=True
            )
            return None
        return channel

    @voice.command(name="lock", description="Stop new members from joining your channel")
    async def voice_lock(self, interaction: discord.Interaction):
        channel = await self._require_owner(interaction)
        if channel is None:
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔒 Channel locked.")

    @voice.command(name="unlock", description="Let anyone join your channel again")
    async def voice_unlock(self, interaction: discord.Interaction):
        channel = await self._require_owner(interaction)
        if channel is None:
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 Channel unlocked.")

    @voice.command(name="limit", description="Cap how many members can join your channel (0 = unlimited)")
    async def voice_limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]):
        channel = await self._require_owner(interaction)
        if channel is None:
            return
        await channel.edit(user_limit=limit)
        await interaction.response.send_message(
            f"👥 User limit set to **{limit if limit else 'unlimited'}**."
        )

    @voice.command(name="name", description="Rename your channel")
    async def voice_name(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 100]):
        channel = await self._require_owner(interaction)
        if channel is None:
            return
        await channel.edit(name=name)
        await interaction.response.send_message(f"✏️ Renamed to **{name}**.")

    @voice.command(name="permit", description="Let a specific member join even while locked")
    async def voice_permit(self, interaction: discord.Interaction, member: discord.Member):
        channel = await self._require_owner(interaction)
        if channel is None:
            return
        overwrite = channel.overwrites_for(member)
        overwrite.connect = True
        await channel.set_permissions(member, overwrite=overwrite)
        await interaction.response.send_message(f"✅ {member.mention} can now join.")

    @voice.command(name="reject", description="Kick and block a specific member from your channel")
    async def voice_reject(self, interaction: discord.Interaction, member: discord.Member):
        channel = await self._require_owner(interaction)
        if channel is None:
            return
        overwrite = channel.overwrites_for(member)
        overwrite.connect = False
        await channel.set_permissions(member, overwrite=overwrite)
        if member.voice and member.voice.channel and member.voice.channel.id == channel.id:
            try:
                await member.move_to(None)
            except discord.HTTPException:
                pass
        await interaction.response.send_message(f"🚫 {member.mention} was removed and blocked.")

    @voice.command(name="transfer", description="Hand ownership of your channel to another member in it")
    async def voice_transfer(self, interaction: discord.Interaction, member: discord.Member):
        channel = await self._require_owner(interaction)
        if channel is None:
            return
        if not member.voice or not member.voice.channel or member.voice.channel.id != channel.id:
            await interaction.response.send_message(
                "❌ That member needs to be in the channel to receive ownership.", ephemeral=True
            )
            return
        self.owned[channel.id] = member.id
        overwrite = channel.overwrites_for(member)
        overwrite.connect = True
        overwrite.manage_channels = True
        overwrite.move_members = True
        await channel.set_permissions(member, overwrite=overwrite)
        await interaction.response.send_message(f"👑 Ownership transferred to {member.mention}.")

    @voice.command(name="claim", description="Claim ownership if the current owner has left")
    async def voice_claim(self, interaction: discord.Interaction):
        channel = self._current_owned_channel(interaction)
        if channel is None:
            await interaction.response.send_message(
                "❌ Join a channel created by the join-to-create system first.", ephemeral=True
            )
            return
        owner_id = self.owned.get(channel.id)
        owner_still_in = owner_id is not None and any(m.id == owner_id for m in channel.members)
        if owner_still_in:
            await interaction.response.send_message(
                "❌ The current owner is still in the channel.", ephemeral=True
            )
            return
        self.owned[channel.id] = interaction.user.id
        overwrite = channel.overwrites_for(interaction.user)
        overwrite.connect = True
        overwrite.manage_channels = True
        overwrite.move_members = True
        await channel.set_permissions(interaction.user, overwrite=overwrite)
        await interaction.response.send_message(f"👑 {interaction.user.mention} now owns this channel.")


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceMaster(bot))
