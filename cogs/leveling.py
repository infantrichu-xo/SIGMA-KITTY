"""
XP-based leveling system. Members earn XP from chatting (with a per-user
cooldown so spamming messages doesn't grind levels), and can automatically
be given a role whenever they reach a level you've configured.

Set it all up with /panel -> Leveling: toggle it on/off, set an
announcement channel for level-ups, and map roles to specific levels
(e.g. "Level 5" role at level 5, "Level 10" role at level 10, etc).
Multiple level-role mappings stack -- reaching a new configured level adds
that role without removing earlier ones.

XP curve: total XP needed to REACH level `n` is 5*n^2 + 50*n + 100 (a
common, gently-escalating curve -- level 5 needs 475 XP, level 10 needs
1100, level 20 needs 3100, etc).
"""

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import guild_config, xp_store

XP_MIN, XP_MAX = 15, 25
XP_COOLDOWN_SECONDS = 60


def xp_for_level(level: int) -> int:
    """Total cumulative XP required to REACH this level."""
    return 5 * level * level + 50 * level + 100


def level_for_xp(xp: int) -> int:
    level = 0
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


def get_xp(guild_id: int, user_id: int) -> int:
    return xp_store.get_guild_key(guild_id, str(user_id), 0)


def set_xp(guild_id: int, user_id: int, xp: int):
    xp_store.set_guild_key(guild_id, str(user_id), max(0, xp))


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldowns: dict[tuple[int, int], float] = {}

    async def _maybe_award_role(self, member: discord.Member, new_level: int):
        level_roles = guild_config.get_guild_key(member.guild.id, "level_roles", {})
        role_id = level_roles.get(str(new_level))
        if not role_id:
            return
        role = member.guild.get_role(role_id)
        if role is None or role in member.roles:
            return
        if role >= member.guild.me.top_role:
            return  # can't assign due to role hierarchy -- silently skip
        try:
            await member.add_roles(role, reason=f"Reached level {new_level}")
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not guild_config.get_guild_key(message.guild.id, "leveling_enabled", True):
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        last = self._cooldowns.get(key)
        if last and now - last < XP_COOLDOWN_SECONDS:
            return
        self._cooldowns[key] = now

        gid, uid = message.guild.id, message.author.id
        old_level = level_for_xp(get_xp(gid, uid))
        new_xp = get_xp(gid, uid) + random.randint(XP_MIN, XP_MAX)
        set_xp(gid, uid, new_xp)
        new_level = level_for_xp(new_xp)

        if new_level > old_level:
            await self._maybe_award_role(message.author, new_level)
            announce_id = guild_config.get_guild_key(gid, "levelup_channel_id")
            channel = message.guild.get_channel(announce_id) if announce_id else message.channel
            if channel is None:
                channel = message.channel
            embed = discord.Embed(
                description=f"🎉 {message.author.mention} leveled up to **level {new_level}**!",
                color=discord.Color.gold(),
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    @app_commands.command(name="rank", description="Check your (or someone else's) level and XP")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        xp = get_xp(interaction.guild.id, member.id)
        level = level_for_xp(xp)
        current_floor = xp_for_level(level)
        next_floor = xp_for_level(level + 1)
        into_level = xp - current_floor
        needed = next_floor - current_floor
        pct = into_level / needed if needed else 0
        bar_len = 20
        filled = round(bar_len * pct)
        bar = "█" * filled + "░" * (bar_len - filled)

        embed = discord.Embed(title=f"⭐ {member.display_name}'s Rank", color=discord.Color.gold())
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="Total XP", value=str(xp), inline=True)
        embed.add_field(name="Progress to next level", value=f"`{bar}` {into_level}/{needed} XP", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ranks", description="See the highest-level members in this server")
    async def ranks(self, interaction: discord.Interaction):
        data = xp_store.get_guild(interaction.guild.id)
        entries = [(int(k), v) for k, v in data.items() if k.isdigit()]
        entries.sort(key=lambda kv: kv[1], reverse=True)

        if not entries:
            await interaction.response.send_message("Nobody has any XP yet.", ephemeral=True)
            return

        medals = ["🥇", "🥈", "🥉"]
        bar_len = 10
        lines = []
        for i, (uid, xp) in enumerate(entries[:10]):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            level = level_for_xp(xp)
            floor, ceiling = xp_for_level(level), xp_for_level(level + 1)
            pct = (xp - floor) / (ceiling - floor) if ceiling > floor else 0
            filled = round(bar_len * pct)
            bar = "▰" * filled + "▱" * (bar_len - filled)

            if i == 0:
                prefix = medals[0]
                lines.append(f"{prefix} **{name}** — Lvl **{level}**\n`{bar}` {xp:,} XP")
            elif i < 3:
                prefix = medals[i]
                lines.append(f"{prefix} **{name}** — Lvl **{level}** • {xp:,} XP")
            else:
                lines.append(f"`#{i + 1:>2}` **{name}** — Lvl **{level}** • {xp:,} XP")

        embed = discord.Embed(
            title=f"🏆 {interaction.guild.name} Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        top_member = interaction.guild.get_member(entries[0][0])
        if top_member:
            embed.set_author(name=f"👑 {top_member.display_name} is on top", icon_url=top_member.display_avatar.url)

        # If the requester isn't in the top 10, show their own placement too.
        requester_ids = [uid for uid, _ in entries[:10]]
        if interaction.user.id not in requester_ids:
            for i, (uid, xp) in enumerate(entries):
                if uid == interaction.user.id:
                    embed.add_field(
                        name="Your rank",
                        value=f"`#{i + 1}` **{interaction.user.display_name}** — Lvl **{level_for_xp(xp)}** • {xp:,} XP",
                        inline=False,
                    )
                    break

        embed.set_footer(text=f"{len(entries)} ranked member(s) • use /rank to see your full progress")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
