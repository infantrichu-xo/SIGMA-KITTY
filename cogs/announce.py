"""
/message -- lets staff post a formatted embed announcement to any channel.

Opens a modal so the message body can be multiple lines. The body is sent
as an embed description, so Discord's normal markdown works in it:
headings (# / ## / ###), **bold**, *italic*, and [masked links](url) --
the last of which needs the bot to have the "Embed Links" permission in
the target channel, same as any other embed.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class AnnounceModal(discord.ui.Modal, title="Send a message"):
    msg_title = discord.ui.TextInput(label="Title (optional)", required=False, max_length=256)
    body = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        placeholder="Supports **bold**, # headings, and [masked links](https://...)",
    )

    def __init__(self, channel: discord.abc.GuildChannel, color: discord.Color):
        super().__init__()
        self.channel = channel
        self.color = color

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(description=str(self.body.value), color=self.color)
        if self.msg_title.value:
            embed.title = str(self.msg_title.value)
        try:
            await self.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ I don't have permission to send/embed messages in {self.channel.mention} -- "
                "check my role has **View Channel**, **Send Messages**, and **Embed Links** there.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"✅ Sent to {self.channel.mention}.", ephemeral=True)


class Announce(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="message", description="Send a formatted embed message to a channel")
    @app_commands.describe(
        channel="Channel to post the message in",
        color="Embed side color (hex, e.g. #5865F2) -- defaults to blurple",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def message(self, interaction: discord.Interaction, channel: discord.TextChannel, color: str = None):
        embed_color = discord.Color.blurple()
        if color:
            try:
                embed_color = discord.Color(int(color.lstrip("#"), 16))
            except ValueError:
                await interaction.response.send_message("❌ Color must be a hex code like `#5865F2`.", ephemeral=True)
                return
        await interaction.response.send_modal(AnnounceModal(channel, embed_color))


async def setup(bot: commands.Bot):
    await bot.add_cog(Announce(bot))
