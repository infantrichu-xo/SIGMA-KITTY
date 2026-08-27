"""
Ticket system. Fully configured through /panel -> Tickets:
  - category new ticket channels are created under
  - support role that can see every ticket
  - log channel for open/close events
  - a button to post the "open a ticket" panel message in any channel

Uses persistent views (custom_id-based, timeout=None) registered in
main.py on startup so the buttons keep working across bot restarts --
they are NOT tied to a single message/interaction like the /panel views.
"""

from __future__ import annotations

import datetime

import discord
from discord.ext import commands

from config import guild_config

OPEN_BUTTON_CUSTOM_ID = "tickets:open"
CLOSE_BUTTON_CUSTOM_ID = "tickets:close"


async def _log(guild: discord.Guild, embed: discord.Embed):
    log_id = guild_config.get_guild_key(guild.id, "ticket_log_channel_id")
    if not log_id:
        return
    channel = guild.get_channel(log_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


def _next_ticket_number(guild_id: int) -> int:
    n = guild_config.get_guild_key(guild_id, "ticket_counter", 0) + 1
    guild_config.set_guild_key(guild_id, "ticket_counter", n)
    return n


class TicketOpenView(discord.ui.View):
    """The persistent panel message members click to open a ticket."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.success, emoji="🎫",
                        custom_id=OPEN_BUTTON_CUSTOM_ID)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        cfg = guild_config.get_guild(guild.id)
        category_id = cfg.get("ticket_category_id")
        category = guild.get_channel(category_id) if category_id else None
        support_role_id = cfg.get("ticket_support_role_id")
        support_role = guild.get_role(support_role_id) if support_role_id else None

        if category is None:
            await interaction.response.send_message(
                "❌ Tickets aren't fully configured yet -- an admin needs to set the "
                "category in `/panel` → Tickets.", ephemeral=True
            )
            return

        open_tickets = cfg.get("open_tickets", {})
        existing_id = open_tickets.get(str(interaction.user.id))
        if existing_id and guild.get_channel(existing_id):
            await interaction.response.send_message(
                f"You already have an open ticket: <#{existing_id}>", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        number = _next_ticket_number(guild.id)
        channel_name = f"ticket-{number:04d}"
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket opened by {interaction.user} ({interaction.user.id})",
                reason=f"Ticket opened by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to create channels in that category -- "
                "check my role's permissions.", ephemeral=True
            )
            return

        open_tickets[str(interaction.user.id)] = channel.id
        guild_config.set_guild_key(guild.id, "open_tickets", open_tickets)

        welcome = discord.Embed(
            title=f"🎫 Ticket #{number:04d}",
            description=(
                f"Thanks for reaching out, {interaction.user.mention}! "
                f"{support_role.mention + ' ' if support_role else ''}"
                "will be with you shortly. Describe your issue below.\n\n"
                "Click **Close Ticket** when this is resolved."
            ),
            color=discord.Color.blurple(),
        )
        welcome.set_thumbnail(url=interaction.user.display_avatar.url)
        await channel.send(
            content=f"{interaction.user.mention}" + (f" {support_role.mention}" if support_role else ""),
            embed=welcome,
            view=TicketCloseView(),
        )
        await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)
        await _log(guild, discord.Embed(
            title="Ticket opened", color=discord.Color.green(),
            description=f"**Ticket:** {channel.mention}\n**Opened by:** {interaction.user} (`{interaction.user.id}`)",
        ))


class TicketCloseView(discord.ui.View):
    """Posted inside each ticket channel."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒",
                        custom_id=CLOSE_BUTTON_CUSTOM_ID)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        cfg = guild_config.get_guild(guild.id)
        support_role_id = cfg.get("ticket_support_role_id")
        support_role = guild.get_role(support_role_id) if support_role_id else None
        is_support = support_role in interaction.user.roles if support_role else False
        is_staff = interaction.user.guild_permissions.manage_guild or is_support

        opener_id = None
        open_tickets = cfg.get("open_tickets", {})
        for uid, cid in open_tickets.items():
            if cid == interaction.channel.id:
                opener_id = int(uid)
                break

        if not is_staff and interaction.user.id != opener_id:
            await interaction.response.send_message(
                "❌ Only the ticket opener or support staff can close this.", ephemeral=True
            )
            return

        await interaction.response.send_message("🔒 Closing this ticket in 5 seconds...")
        if opener_id is not None:
            open_tickets.pop(str(opener_id), None)
            guild_config.set_guild_key(guild.id, "open_tickets", open_tickets)

        await _log(guild, discord.Embed(
            title="Ticket closed", color=discord.Color.red(),
            description=f"**Ticket:** #{interaction.channel.name}\n**Closed by:** {interaction.user} (`{interaction.user.id}`)",
        ))
        await discord.utils.sleep_until(discord.utils.utcnow() + datetime.timedelta(seconds=5))
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
