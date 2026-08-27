import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pfp", description="Show a member's full-size profile picture")
    async def pfp(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        avatar = member.display_avatar.with_size(1024)
        embed = discord.Embed(title=f"{member.display_name}'s avatar", color=discord.Color.blurple())
        embed.set_image(url=avatar.url)
        embed.description = f"[Open full size]({avatar.url})"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="List everything this bot can do")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🤖 Bot commands", color=discord.Color.blurple())
        embed.add_field(name="🎛️ Control Panel", value=(
            "`/panel` — click-through UI for everything below, including bot nickname/status (needs Manage Server)"
        ), inline=False)
        embed.add_field(name="🛡️ Moderation", value=(
            "`/kick` `/ban` `/unban` `/timeout` `/untimeout`\n"
            "`/warn` `/warnings` `/clearwarnings` `/purge`\n"
            "`/lock` `/unlock` `/lockvc` `/unlockvc` `/setlogchannel`"
        ), inline=False)
        embed.add_field(name="🚪 Autorole", value="`/autorole` `/autorole-off` `/roleall`", inline=False)
        embed.add_field(name="🧹 Word filter", value=(
            "`/badword list|add|remove|reload` (reads/writes bad.txt)"
        ), inline=False)
        embed.add_field(name="🚨 Anti-raid", value="`/raidmode on|off` `/antiraid-config`", inline=False)
        embed.add_field(name="🛑 Anti-nuke", value=(
            "`/antinuke config` `/antinuke whitelist-add|whitelist-remove`"
        ), inline=False)
        embed.add_field(name="🎵 Music", value=(
            "`/join` `/leave` `/play <search term, link, or playlist link>`\n"
            "`/skip` `/pause` `/resume` `/queue` `/stop`"
        ), inline=False)
        embed.add_field(name="🎰 Gambling", value=(
            "`/balance` `/daily` (streak bonus) `/rob` `/leaderboard`\n"
            "`/coinflip` `/dice` `/slots` `/blackjack` — all animated"
        ), inline=False)
        embed.add_field(name="🗣️ Text-to-Speech", value=(
            "`/tts` — joins your voice channel and reads this channel's chat aloud (skips spam); run again to stop"
        ), inline=False)
        embed.add_field(name="⭐ Leveling", value=(
            "`/rank` `/ranks` — chat XP and levels; set up level roles in `/panel`"
        ), inline=False)
        embed.add_field(name="🔊 Voice Master", value=(
            "Join the trigger channel (set in `/panel` -> Voice Master) to get your own voice channel.\n"
            "`/voice lock|unlock|limit|name|permit|reject|transfer|claim`"
        ), inline=False)
        embed.add_field(name="🖼️ Utility", value="`/pfp` — full-size profile picture", inline=False)
        embed.set_footer(text="Most moderation/config commands require appropriate server permissions.")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
