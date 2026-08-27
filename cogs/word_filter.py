"""
Deletes messages containing words listed in bad.txt (same directory as
main.py). Supports live add/remove/reload via slash commands, and logs
deletions to a configured log channel.
"""

import os
import re

import discord
from discord import app_commands
from discord.ext import commands

from config import guild_config

BAD_WORDS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bad.txt")


def load_bad_words() -> set[str]:
    words = set()
    if not os.path.exists(BAD_WORDS_PATH):
        return words
    with open(BAD_WORDS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            words.add(line.lower())
    return words


def save_bad_words(words: set[str]):
    with open(BAD_WORDS_PATH, "w", encoding="utf-8") as f:
        f.write("# bad.txt - one blocked word/phrase per line, # = comment\n")
        for w in sorted(words):
            f.write(w + "\n")


class WordFilter(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bad_words: set[str] = load_bad_words()
        self._pattern: re.Pattern | None = None
        self._rebuild_pattern()

    def _rebuild_pattern(self):
        if not self.bad_words:
            self._pattern = None
            return
        # Whole-word / phrase match, case-insensitive. Escapes each entry so
        # things like "." or "*" in bad.txt aren't treated as regex.
        escaped = [re.escape(w) for w in self.bad_words]
        self._pattern = re.compile(
            r"(?<!\w)(" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE
        )

    def contains_bad_word(self, text: str) -> str | None:
        if not self._pattern:
            return None
        match = self._pattern.search(text)
        return match.group(0) if match else None

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
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return  # don't filter staff

        hit = self.contains_bad_word(message.content)
        if not hit:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        try:
            warn = await message.channel.send(
                f"{message.author.mention} that message was removed for containing a blocked word.",
                delete_after=6,
            )
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title="🧹 Message filtered",
            description=f"**Author:** {message.author} (`{message.author.id}`)\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Matched:** `{hit}`",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Original content", value=message.content[:1000] or "*(empty)*", inline=False)
        await self._log(message.guild, embed)

    # -------------------------------------------------------------- commands
    badword = app_commands.Group(
        name="badword", description="Manage the blocked word list (bad.txt)"
    )

    @badword.command(name="list", description="List currently blocked words")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def badword_list(self, interaction: discord.Interaction):
        if not self.bad_words:
            await interaction.response.send_message("No blocked words configured.", ephemeral=True)
            return
        words = ", ".join(f"`{w}`" for w in sorted(self.bad_words))
        await interaction.response.send_message(f"Blocked words ({len(self.bad_words)}): {words}"[:2000], ephemeral=True)

    @badword.command(name="add", description="Add a word/phrase to bad.txt")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def badword_add(self, interaction: discord.Interaction, word: str):
        self.bad_words.add(word.lower().strip())
        save_bad_words(self.bad_words)
        self._rebuild_pattern()
        await interaction.response.send_message(f"✅ Added `{word}` to bad.txt.", ephemeral=True)

    @badword.command(name="remove", description="Remove a word/phrase from bad.txt")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def badword_remove(self, interaction: discord.Interaction, word: str):
        self.bad_words.discard(word.lower().strip())
        save_bad_words(self.bad_words)
        self._rebuild_pattern()
        await interaction.response.send_message(f"✅ Removed `{word}` from bad.txt.", ephemeral=True)

    @badword.command(name="reload", description="Reload bad.txt from disk")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def badword_reload(self, interaction: discord.Interaction):
        self.bad_words = load_bad_words()
        self._rebuild_pattern()
        await interaction.response.send_message(
            f"🔄 Reloaded. {len(self.bad_words)} word(s) loaded from bad.txt.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WordFilter(bot))
