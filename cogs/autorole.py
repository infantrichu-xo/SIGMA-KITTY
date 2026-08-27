"""
Automatically gives new members a configured role when they join, plus a
bulk /roleall command to add/remove a role for every current member.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from config import guild_config


class ConfirmRoleAllView(discord.ui.View):
    def __init__(self, invoker_id: int):
        super().__init__(timeout=30)
        self.invoker_id = invoker_id
        self.value: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return False
        return True

    async def _finish(self, interaction: discord.Interaction, value: bool):
        self.value = value
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, False)


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        role_id = guild_config.get_guild_key(member.guild.id, "autorole_id")
        if not role_id:
            return
        role = member.guild.get_role(role_id)
        if not role:
            return
        # Anti-raid may have this disabled temporarily during a raid lockdown
        if guild_config.get_guild_key(member.guild.id, "raid_lockdown", False):
            return
        try:
            await member.add_roles(role, reason="Autorole on join")
        except discord.Forbidden:
            pass

    @app_commands.command(name="autorole", description="Set the role automatically given to new members")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "❌ I can't assign that role — it's above (or equal to) my highest role. "
                "Move my role above it in Server Settings > Roles.",
                ephemeral=True,
            )
            return
        guild_config.set_guild_key(interaction.guild.id, "autorole_id", role.id)
        await interaction.response.send_message(f"✅ New members will now automatically receive {role.mention}.")

    @app_commands.command(name="autorole-off", description="Disable autorole")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_off(self, interaction: discord.Interaction):
        guild_config.set_guild_key(interaction.guild.id, "autorole_id", None)
        await interaction.response.send_message("✅ Autorole disabled.")

    @app_commands.command(name="roleall", description="Add or remove a role for every member in the server")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(
        role="The role to add or remove",
        action="Add the role to everyone, or remove it from everyone",
        include_bots="Also include bot accounts (default: no)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add to everyone", value="add"),
        app_commands.Choice(name="Remove from everyone", value="remove"),
    ])
    async def roleall(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        action: app_commands.Choice[str],
        include_bots: bool = False,
    ):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "❌ I can't manage that role — it's above (or equal to) my highest role. "
                "Move my role above it in Server Settings > Roles.",
                ephemeral=True,
            )
            return
        if role.is_default():
            await interaction.response.send_message("❌ You can't add/remove @everyone.", ephemeral=True)
            return

        members = interaction.guild.members
        if not include_bots:
            members = [m for m in members if not m.bot]

        will_change = [
            m for m in members
            if (action.value == "add") != (role in m.roles)
        ]

        if not will_change:
            await interaction.response.send_message(
                f"Nothing to do — every relevant member already {'has' if action.value == 'add' else 'lacks'} {role.mention}.",
                ephemeral=True,
            )
            return

        verb = "add" if action.value == "add" else "remove"
        prep = "to" if action.value == "add" else "from"
        confirm_view = ConfirmRoleAllView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ This will **{verb}** {role.mention} {prep} **{len(will_change)}** member(s). "
            f"Large servers can take a while (Discord rate limits role edits) and this can't be undone in bulk. Continue?",
            view=confirm_view,
        )
        await confirm_view.wait()
        if not confirm_view.value:
            await interaction.edit_original_response(content="Cancelled.", view=None)
            return

        total = len(will_change)
        done = failed = 0
        await interaction.edit_original_response(content=f"⏳ Working... 0/{total}", view=None)

        for i, member in enumerate(will_change, 1):
            try:
                if action.value == "add":
                    await member.add_roles(role, reason=f"/roleall by {interaction.user}")
                else:
                    await member.remove_roles(role, reason=f"/roleall by {interaction.user}")
                done += 1
            except discord.HTTPException:
                failed += 1
            if i % 10 == 0 or i == total:
                try:
                    await interaction.edit_original_response(content=f"⏳ Working... {i}/{total}")
                except discord.HTTPException:
                    pass
            await asyncio.sleep(0.25)  # stay gentle on rate limits for big member lists

        summary = f"✅ Done — {verb}ed {role.mention} {prep} **{done}** member(s)."
        if failed:
            summary += f" Failed on {failed} (likely missing permissions or higher role)."
        await interaction.edit_original_response(content=summary)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
