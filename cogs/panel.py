"""
A single in-Discord control panel (/panel) for admins to configure every
part of the bot -- moderation, autorole, word filter, anti-raid, anti-nuke,
music, and the gambling economy -- using buttons, dropdowns, and forms
instead of remembering slash-command syntax.

Requires Manage Server permission to open or interact with the panel.
The panel is not persistent across bot restarts (it's a normal, timed-out
view) -- just run /panel again if it expires after 3 minutes of inactivity.
"""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from config import guild_config, economy_store, bot_settings, GLOBAL_KEY
from cogs.moderation import OFFENSE_ACTIONS
from cogs.tickets import TicketOpenView

PANEL_TIMEOUT = 180
BRAND_COLOR = discord.Color.blurple()


def require_manage_guild(interaction: discord.Interaction) -> bool:
    perms = interaction.user.guild_permissions
    return perms.manage_guild or perms.administrator


# ---------------------------------------------------------------------------
# Shared base view
# ---------------------------------------------------------------------------
class BasePanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, invoker_id: int):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.bot = bot
        self.guild = guild
        self.invoker_id = invoker_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not require_manage_guild(interaction):
            await interaction.response.send_message(
                "❌ You need the **Manage Server** permission to use this panel.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def goto(self, interaction: discord.Interaction, view: "BasePanelView", embed: discord.Embed):
        view.message = self.message
        await interaction.response.edit_message(embed=embed, view=view)


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------
def build_home_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    log_ch = guild.get_channel(cfg.get("log_channel_id")) if cfg.get("log_channel_id") else None
    autorole = guild.get_role(cfg.get("autorole_id")) if cfg.get("autorole_id") else None

    embed = discord.Embed(
        title="🎛️ Bot Control Panel",
        description="Pick a category below to configure it.",
        color=BRAND_COLOR,
    )
    embed.add_field(name="Log channel", value=log_ch.mention if log_ch else "*not set*", inline=True)
    embed.add_field(name="Autorole", value=autorole.mention if autorole else "*not set*", inline=True)
    embed.add_field(name="Raid lockdown", value="🔴 ACTIVE" if cfg.get("raid_lockdown") else "🟢 normal", inline=True)
    embed.set_footer(text="Requires Manage Server permission • expires after 3 minutes")
    return embed


class PanelHome(BasePanelView):
    @discord.ui.button(label="Moderation", style=discord.ButtonStyle.secondary, emoji="🛡️", row=0)
    async def moderation_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ModerationPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_moderation_embed(self.guild))

    @discord.ui.button(label="Autorole", style=discord.ButtonStyle.secondary, emoji="🚪", row=0)
    async def autorole_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AutoRolePage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_autorole_embed(self.guild))

    @discord.ui.button(label="Word Filter", style=discord.ButtonStyle.secondary, emoji="🧹", row=0)
    async def wordfilter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WordFilterPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_wordfilter_embed(self.bot))

    @discord.ui.button(label="Anti-Raid", style=discord.ButtonStyle.secondary, emoji="🚨", row=1)
    async def antiraid_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AntiRaidPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_antiraid_embed(self.guild))

    @discord.ui.button(label="Anti-Nuke", style=discord.ButtonStyle.secondary, emoji="🛑", row=1)
    async def antinuke_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AntiNukePage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_antinuke_embed(self.guild))

    @discord.ui.button(label="Music", style=discord.ButtonStyle.secondary, emoji="🎵", row=1)
    async def music_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MusicPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_music_embed(self.bot, self.guild))

    @discord.ui.button(label="Economy", style=discord.ButtonStyle.secondary, emoji="🎰", row=2)
    async def economy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EconomyPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_economy_embed(self.guild))

    @discord.ui.button(label="Bot Profile", style=discord.ButtonStyle.secondary, emoji="🪪", row=2)
    async def bio_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = BioPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_bio_embed(self.bot, self.guild))

    @discord.ui.button(label="Tickets", style=discord.ButtonStyle.secondary, emoji="🎫", row=2)
    async def tickets_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TicketsPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_tickets_embed(self.guild))

    @discord.ui.button(label="Text-to-Speech", style=discord.ButtonStyle.secondary, emoji="🗣️", row=3)
    async def tts_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TTSPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_tts_embed(self.bot, self.guild))

    @discord.ui.button(label="Leveling", style=discord.ButtonStyle.secondary, emoji="⭐", row=3)
    async def leveling_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LevelingPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_leveling_embed(self.guild))

    @discord.ui.button(label="Voice Master", style=discord.ButtonStyle.secondary, emoji="🔊", row=3)
    async def voicemaster_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = VoiceMasterPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_voicemaster_embed(self.guild))

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="✖️", row=4)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Panel closed.", embed=None, view=self)
        self.stop()


# ---------------------------------------------------------------------------
# Moderation page
# ---------------------------------------------------------------------------
def build_moderation_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    log_ch = guild.get_channel(cfg.get("log_channel_id")) if cfg.get("log_channel_id") else None
    offense_count = len(cfg.get("warn_offenses", []))
    embed = discord.Embed(title="🛡️ Moderation", color=BRAND_COLOR)
    embed.add_field(name="Log channel", value=log_ch.mention if log_ch else "*not set*", inline=False)
    embed.add_field(name="Warn offenses configured", value=str(offense_count), inline=False)
    embed.description = "Pick a channel below to send mod/security logs there, purge messages, or configure /warn offenses."
    return embed


class PurgeModal(discord.ui.Modal, title="Purge messages"):
    amount = discord.ui.TextInput(label="How many messages to delete? (1-500)", default="25")

    def __init__(self, channel: discord.abc.Messageable):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = max(1, min(500, int(self.amount.value)))
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid number.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await self.channel.purge(limit=n)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} message(s) in {self.channel.mention}.", ephemeral=True)


class ModerationPage(BasePanelView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text],
                        placeholder="Set log channel...", row=0)
    async def log_channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        guild_config.set_guild_key(self.guild.id, "log_channel_id", channel.id)
        await interaction.response.edit_message(embed=build_moderation_embed(self.guild), view=self)

    @discord.ui.button(label="Purge this channel", style=discord.ButtonStyle.danger, emoji="🧹", row=1)
    async def purge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PurgeModal(interaction.channel))

    @discord.ui.button(label="Warn Offenses", style=discord.ButtonStyle.secondary, emoji="⚠️", row=1)
    async def warn_offenses_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WarnOffensesPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_warn_offenses_embed(self.guild))

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Warn Offenses page (customizable /warn presets)
# ---------------------------------------------------------------------------
def build_warn_offenses_embed(guild: discord.Guild) -> discord.Embed:
    offenses = guild_config.get_guild_key(guild.id, "warn_offenses", [])
    embed = discord.Embed(title="⚠️ Warn Offenses", color=BRAND_COLOR)
    embed.description = (
        "Preset offenses staff can pick from when using `/warn` (it autocompletes "
        "these). Each offense can optionally auto-apply a timeout/kick/ban on top "
        "of logging the warning."
    )
    if offenses:
        lines = []
        for o in offenses:
            action = o.get("action", "none")
            extra = f" ({o.get('duration', 10)}m)" if action == "timeout" else ""
            lines.append(f"**{o['name']}** — {o['reason']}\n　└ auto-action: `{action}{extra}`")
        embed.add_field(name="Configured offenses", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="Configured offenses", value="*none set -- /warn falls back to a free-text reason*", inline=False)
    return embed


class AddOffenseModal(discord.ui.Modal, title="Add a warn offense"):
    name = discord.ui.TextInput(label="Offense name (shown in /warn autocomplete)", max_length=80)
    reason = discord.ui.TextInput(label="Reason text stored on the warning", style=discord.TextStyle.paragraph, max_length=300)
    action = discord.ui.TextInput(
        label="Auto-action: none / timeout / kick / ban", default="none", max_length=10,
    )
    duration = discord.ui.TextInput(
        label="Timeout minutes (if action=timeout)", default="10", required=False, max_length=6,
    )

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        action = self.action.value.strip().lower()
        if action not in OFFENSE_ACTIONS:
            await interaction.response.send_message(
                f"❌ Action must be one of: {', '.join(OFFENSE_ACTIONS)}.", ephemeral=True
            )
            return
        try:
            duration = int(self.duration.value) if self.duration.value else 10
        except ValueError:
            await interaction.response.send_message("❌ Duration must be a whole number of minutes.", ephemeral=True)
            return

        offenses = guild_config.get_guild_key(self.guild.id, "warn_offenses", [])
        offenses = [o for o in offenses if o["name"].strip().lower() != self.name.value.strip().lower()]
        offenses.append({
            "name": self.name.value.strip(),
            "reason": self.reason.value.strip(),
            "action": action,
            "duration": duration,
        })
        guild_config.set_guild_key(self.guild.id, "warn_offenses", offenses)
        await interaction.response.send_message(f"✅ Added offense **{self.name.value.strip()}**.", ephemeral=True)


class RemoveOffenseModal(discord.ui.Modal, title="Remove a warn offense"):
    name = discord.ui.TextInput(label="Exact offense name to remove")

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        offenses = guild_config.get_guild_key(self.guild.id, "warn_offenses", [])
        target = self.name.value.strip().lower()
        new_offenses = [o for o in offenses if o["name"].strip().lower() != target]
        if len(new_offenses) == len(offenses):
            await interaction.response.send_message("No offense with that name was found.", ephemeral=True)
            return
        guild_config.set_guild_key(self.guild.id, "warn_offenses", new_offenses)
        await interaction.response.send_message(f"✅ Removed offense **{self.name.value.strip()}**.", ephemeral=True)


class WarnOffensesPage(BasePanelView):
    @discord.ui.button(label="Add offense", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddOffenseModal(self.guild))

    @discord.ui.button(label="Remove offense", style=discord.ButtonStyle.danger, emoji="➖", row=0)
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RemoveOffenseModal(self.guild))

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=build_warn_offenses_embed(self.guild), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ModerationPage(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, view, build_moderation_embed(self.guild))


# ---------------------------------------------------------------------------
# Autorole page
# ---------------------------------------------------------------------------
def build_autorole_embed(guild: discord.Guild) -> discord.Embed:
    role_id = guild_config.get_guild_key(guild.id, "autorole_id")
    role = guild.get_role(role_id) if role_id else None
    embed = discord.Embed(title="🚪 Autorole", color=BRAND_COLOR)
    embed.description = "Choose the role automatically given to new members, or disable it."
    embed.add_field(name="Current autorole", value=role.mention if role else "*not set*")
    return embed


class AutoRolePage(BasePanelView):
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Choose autorole...", row=0)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]
        if role >= self.guild.me.top_role:
            await interaction.response.send_message(
                "❌ I can't assign that role — move my role above it in Server Settings → Roles.",
                ephemeral=True,
            )
            return
        guild_config.set_guild_key(self.guild.id, "autorole_id", role.id)
        await interaction.response.edit_message(embed=build_autorole_embed(self.guild), view=self)

    @discord.ui.button(label="Disable autorole", style=discord.ButtonStyle.danger, row=1)
    async def disable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_config.set_guild_key(self.guild.id, "autorole_id", None)
        await interaction.response.edit_message(embed=build_autorole_embed(self.guild), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Word filter page
# ---------------------------------------------------------------------------
def build_wordfilter_embed(bot: commands.Bot) -> discord.Embed:
    cog = bot.get_cog("WordFilter")
    count = len(cog.bad_words) if cog else 0
    embed = discord.Embed(title="🧹 Word Filter", color=BRAND_COLOR)
    embed.description = f"**{count}** word(s) currently blocked (from `bad.txt`)."
    return embed


class WordModal(discord.ui.Modal):
    word = discord.ui.TextInput(label="Word or phrase")

    def __init__(self, title: str, mode: str, cog):
        super().__init__(title=title)
        self.mode = mode
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.word_filter import save_bad_words
        w = self.word.value.lower().strip()
        if self.mode == "add":
            self.cog.bad_words.add(w)
            msg = f"✅ Added `{w}`."
        else:
            self.cog.bad_words.discard(w)
            msg = f"✅ Removed `{w}`."
        save_bad_words(self.cog.bad_words)
        self.cog._rebuild_pattern()
        await interaction.response.send_message(msg, ephemeral=True)


class WordFilterPage(BasePanelView):
    @discord.ui.button(label="Add word", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("WordFilter")
        await interaction.response.send_modal(WordModal("Add blocked word", "add", cog))

    @discord.ui.button(label="Remove word", style=discord.ButtonStyle.danger, emoji="➖", row=0)
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("WordFilter")
        await interaction.response.send_modal(WordModal("Remove blocked word", "remove", cog))

    @discord.ui.button(label="List words", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("WordFilter")
        words = ", ".join(f"`{w}`" for w in sorted(cog.bad_words)) if cog.bad_words else "*(none)*"
        await interaction.response.send_message(f"Blocked words: {words}"[:2000], ephemeral=True)

    @discord.ui.button(label="Reload from bad.txt", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def reload_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.word_filter import load_bad_words
        cog = self.bot.get_cog("WordFilter")
        cog.bad_words = load_bad_words()
        cog._rebuild_pattern()
        await interaction.response.edit_message(embed=build_wordfilter_embed(self.bot), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Anti-raid page
# ---------------------------------------------------------------------------
def build_antiraid_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    embed = discord.Embed(title="🚨 Anti-Raid", color=BRAND_COLOR)
    embed.add_field(name="Status", value="🔴 LOCKDOWN ACTIVE" if cfg.get("raid_lockdown") else "🟢 Normal", inline=False)
    embed.add_field(name="Join threshold", value=str(cfg.get("raid_join_threshold", 6)), inline=True)
    embed.add_field(name="Window (sec)", value=str(cfg.get("raid_join_window", 10)), inline=True)
    embed.add_field(name="Min account age (hrs)", value=str(cfg.get("raid_min_account_age_hours", 24)), inline=True)
    return embed


class AntiRaidConfigModal(discord.ui.Modal, title="Anti-raid thresholds"):
    threshold = discord.ui.TextInput(label="Join threshold (joins to trigger)", required=False)
    window = discord.ui.TextInput(label="Window in seconds", required=False)
    min_age = discord.ui.TextInput(label="Min account age in hours (during lockdown)", required=False)

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        if self.threshold.value:
            guild_config.set_guild_key(self.guild.id, "raid_join_threshold", int(self.threshold.value))
        if self.window.value:
            guild_config.set_guild_key(self.guild.id, "raid_join_window", int(self.window.value))
        if self.min_age.value:
            guild_config.set_guild_key(self.guild.id, "raid_min_account_age_hours", int(self.min_age.value))
        await interaction.response.send_message("✅ Anti-raid settings updated.", ephemeral=True)


class AntiRaidPage(BasePanelView):
    @discord.ui.button(label="Enable lockdown", style=discord.ButtonStyle.danger, row=0)
    async def enable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_config.set_guild_key(self.guild.id, "raid_lockdown", True)
        try:
            await self.guild.edit(verification_level=discord.VerificationLevel.highest, reason="Manual lockdown via panel")
        except discord.Forbidden:
            pass
        await interaction.response.edit_message(embed=build_antiraid_embed(self.guild), view=self)

    @discord.ui.button(label="Disable lockdown", style=discord.ButtonStyle.success, row=0)
    async def disable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_config.set_guild_key(self.guild.id, "raid_lockdown", False)
        try:
            await self.guild.edit(verification_level=discord.VerificationLevel.medium, reason="Lockdown lifted via panel")
        except discord.Forbidden:
            pass
        await interaction.response.edit_message(embed=build_antiraid_embed(self.guild), view=self)

    @discord.ui.button(label="Configure thresholds", style=discord.ButtonStyle.secondary, emoji="⚙️", row=1)
    async def config_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AntiRaidConfigModal(self.guild))

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Anti-nuke page
# ---------------------------------------------------------------------------
def build_antinuke_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    wl = cfg.get("antinuke_whitelist", [])
    wl_mentions = ", ".join(f"<@{uid}>" for uid in wl) if wl else "*(none)*"
    embed = discord.Embed(title="🛑 Anti-Nuke", color=BRAND_COLOR)
    embed.add_field(name="Threshold", value=str(cfg.get("antinuke_threshold", 3)), inline=True)
    embed.add_field(name="Window (sec)", value=str(cfg.get("antinuke_window", 20)), inline=True)
    embed.add_field(name="Punishment", value=cfg.get("antinuke_punishment", "strip_roles"), inline=True)
    embed.add_field(name="Whitelist", value=wl_mentions, inline=False)
    return embed


class AntiNukeConfigModal(discord.ui.Modal, title="Anti-nuke thresholds"):
    threshold = discord.ui.TextInput(label="Action threshold", required=False)
    window = discord.ui.TextInput(label="Window in seconds", required=False)

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        if self.threshold.value:
            guild_config.set_guild_key(self.guild.id, "antinuke_threshold", int(self.threshold.value))
        if self.window.value:
            guild_config.set_guild_key(self.guild.id, "antinuke_window", int(self.window.value))
        await interaction.response.send_message("✅ Anti-nuke settings updated.", ephemeral=True)


class AntiNukePage(BasePanelView):
    @discord.ui.select(placeholder="Set punishment...", row=0, options=[
        discord.SelectOption(label="Strip dangerous roles (reversible)", value="strip_roles"),
        discord.SelectOption(label="Ban immediately", value="ban"),
    ])
    async def punishment_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        guild_config.set_guild_key(self.guild.id, "antinuke_punishment", select.values[0])
        await interaction.response.edit_message(embed=build_antinuke_embed(self.guild), view=self)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Add user to whitelist...", row=1)
    async def whitelist_add_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        user = select.values[0]
        wl = guild_config.get_guild_key(self.guild.id, "antinuke_whitelist", [])
        if user.id not in wl:
            wl.append(user.id)
            guild_config.set_guild_key(self.guild.id, "antinuke_whitelist", wl)
        await interaction.response.edit_message(embed=build_antinuke_embed(self.guild), view=self)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Remove user from whitelist...", row=2)
    async def whitelist_remove_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        user = select.values[0]
        wl = guild_config.get_guild_key(self.guild.id, "antinuke_whitelist", [])
        if user.id in wl:
            wl.remove(user.id)
            guild_config.set_guild_key(self.guild.id, "antinuke_whitelist", wl)
        await interaction.response.edit_message(embed=build_antinuke_embed(self.guild), view=self)

    @discord.ui.button(label="Configure thresholds", style=discord.ButtonStyle.secondary, emoji="⚙️", row=3)
    async def config_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AntiNukeConfigModal(self.guild))

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Music page
# ---------------------------------------------------------------------------
def build_music_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    cog = bot.get_cog("Music")
    state = cog.state_for(guild.id) if cog else None
    embed = discord.Embed(title="🎵 Music", color=BRAND_COLOR)
    if state and state.voice_client and state.voice_client.is_connected():
        embed.add_field(name="Connected to", value=state.voice_client.channel.mention, inline=True)
    else:
        embed.add_field(name="Connected to", value="*not connected*", inline=True)
    embed.add_field(name="24/7 mode", value="✅ on" if (state and state.stay_247) else "❌ off", inline=True)
    now = state.now_playing["title"] if state and state.now_playing else "*nothing*"
    embed.add_field(name="Now playing", value=now, inline=False)
    qlen = len(state.queue) if state else 0
    embed.add_field(name="Queue length", value=str(qlen), inline=False)
    return embed


class MusicPage(BasePanelView):
    @discord.ui.button(label="Join & stay 24/7", style=discord.ButtonStyle.success, emoji="🔊", row=0)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = self.guild.get_member(interaction.user.id)
        if not member or not member.voice or not member.voice.channel:
            await interaction.response.send_message("❌ Join a voice channel first.", ephemeral=True)
            return
        cog = self.bot.get_cog("Music")
        state = cog.state_for(self.guild.id)
        channel = member.voice.channel
        if state.voice_client and state.voice_client.is_connected():
            await state.voice_client.move_to(channel)
        else:
            state.voice_client = await channel.connect(reconnect=True, self_deaf=True)
        state.stay_247 = True
        state.text_channel = interaction.channel
        guild_config.set_guild_key(self.guild.id, "music_247", True)
        await interaction.response.edit_message(embed=build_music_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger, emoji="👋", row=0)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("Music")
        state = cog.state_for(self.guild.id)
        state.stay_247 = False
        state.queue.clear()
        if state.voice_client:
            await state.voice_client.disconnect()
            state.voice_client = None
        await interaction.response.edit_message(embed=build_music_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="Toggle 24/7", style=discord.ButtonStyle.secondary, emoji="🔁", row=1)
    async def toggle_247_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("Music")
        state = cog.state_for(self.guild.id)
        state.stay_247 = not state.stay_247
        guild_config.set_guild_key(self.guild.id, "music_247", state.stay_247)
        await interaction.response.edit_message(embed=build_music_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️", row=1)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("Music")
        state = cog.state_for(self.guild.id)
        if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
            state.voice_client.stop()
        await interaction.response.edit_message(embed=build_music_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="Pause/Resume", style=discord.ButtonStyle.secondary, emoji="⏯️", row=1)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("Music")
        state = cog.state_for(self.guild.id)
        if state.voice_client:
            if state.voice_client.is_playing():
                state.voice_client.pause()
            elif state.voice_client.is_paused():
                state.voice_client.resume()
        await interaction.response.edit_message(embed=build_music_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="Stop & clear queue", style=discord.ButtonStyle.danger, emoji="⏹️", row=2)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("Music")
        state = cog.state_for(self.guild.id)
        state.queue.clear()
        if state.voice_client:
            state.voice_client.stop()
        await interaction.response.edit_message(embed=build_music_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Economy page
# ---------------------------------------------------------------------------
def build_economy_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    gamble_id = cfg.get("gambling_channel_id")
    gamble_ch = guild.get_channel(gamble_id) if gamble_id else None
    embed = discord.Embed(title="🎰 Economy / Gambling", color=BRAND_COLOR)
    embed.add_field(name="Starting balance", value=str(cfg.get("econ_starting_balance", 500)), inline=True)
    embed.add_field(name="Daily claim amount", value=str(cfg.get("econ_daily_amount", 250)), inline=True)
    embed.add_field(
        name="Gambling restricted to",
        value=gamble_ch.mention if gamble_ch else "*any channel (not restricted)*",
        inline=False,
    )
    embed.description = "`/coinflip` `/dice` `/slots` `/blackjack` only work in the channel set below, if one is set."
    return embed


class EconomyConfigModal(discord.ui.Modal, title="Economy settings"):
    starting = discord.ui.TextInput(label="Starting balance", required=False)
    daily = discord.ui.TextInput(label="Daily claim amount", required=False)

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        if self.starting.value:
            guild_config.set_guild_key(self.guild.id, "econ_starting_balance", int(self.starting.value))
        if self.daily.value:
            guild_config.set_guild_key(self.guild.id, "econ_daily_amount", int(self.daily.value))
        await interaction.response.send_message("✅ Economy settings updated.", ephemeral=True)


class ConfirmResetView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=30)
        self.guild_id = guild_id
        self.confirmed = False

    @discord.ui.button(label="Yes, reset all balances", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        economy_store.clear_guild(self.guild_id)
        self.confirmed = True
        await interaction.response.edit_message(content="✅ All balances reset.", view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)
        self.stop()


class EconomyPage(BasePanelView):
    @discord.ui.button(label="Configure", style=discord.ButtonStyle.secondary, emoji="⚙️", row=0)
    async def config_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EconomyConfigModal(self.guild))

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text],
                        placeholder="Restrict gambling to this channel...", row=1)
    async def gambling_channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        guild_config.set_guild_key(self.guild.id, "gambling_channel_id", select.values[0].id)
        await interaction.response.edit_message(embed=build_economy_embed(self.guild), view=self)

    @discord.ui.button(label="Clear channel restriction", style=discord.ButtonStyle.secondary, row=2)
    async def clear_gambling_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_config.set_guild_key(self.guild.id, "gambling_channel_id", None)
        await interaction.response.edit_message(embed=build_economy_embed(self.guild), view=self)

    @discord.ui.button(label="Reset all balances", style=discord.ButtonStyle.danger, emoji="⚠️", row=2)
    async def reset_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Are you sure? This wipes every member's coin balance in this server.",
            view=ConfirmResetView(self.guild.id),
            ephemeral=True,
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Bot profile / "bio" page — nickname (per-server), status text/activity
# type, and online status. Discord bots can't set a free-text "About Me"
# via the bot API (that's only editable by a human in the Dev Portal), so
# this page exposes everything that actually is controllable at runtime.
# ---------------------------------------------------------------------------
_ACTIVITY_MAP = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}
_STATUS_MAP = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}


def build_bio_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    cfg = bot_settings.get_guild(GLOBAL_KEY)
    activity_type = cfg.get("activity_type", "watching")
    activity_text = cfg.get("activity_text", "over the server 👁️")
    status = cfg.get("status", "online")
    nick = guild.me.nick if guild.me else None

    embed = discord.Embed(title="🪪 Bot Profile", color=BRAND_COLOR)
    embed.description = (
        "Nickname is per-server. Status/activity apply to the bot everywhere "
        "it's added (Discord presence isn't per-server)."
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name="Nickname (this server)", value=nick or "*(using bot's real name)*", inline=False)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Activity", value=f"{activity_type.title()} **{activity_text}**", inline=True)
    return embed


class NicknameModal(discord.ui.Modal, title="Set bot nickname"):
    nickname = discord.ui.TextInput(
        label="Nickname for this server (blank = reset)", required=False, max_length=32
    )

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.guild.me.edit(nick=self.nickname.value or None)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I can't change my own nickname here — check my role's permissions.", ephemeral=True
            )
            return
        await interaction.response.send_message("✅ Nickname updated.", ephemeral=True)


class ActivityTextModal(discord.ui.Modal, title="Set status text"):
    text = discord.ui.TextInput(label="Status text", max_length=128, placeholder="e.g. over the server 👁️")

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        bot_settings.set_guild_key(GLOBAL_KEY, "activity_text", str(self.text.value))
        await apply_presence(self.bot)
        await interaction.response.send_message("✅ Status text updated.", ephemeral=True)


async def apply_presence(bot: commands.Bot):
    cfg = bot_settings.get_guild(GLOBAL_KEY)
    activity_type = _ACTIVITY_MAP.get(cfg.get("activity_type", "watching"), discord.ActivityType.watching)
    activity_text = cfg.get("activity_text", "over the server 👁️")
    status = _STATUS_MAP.get(cfg.get("status", "online"), discord.Status.online)
    await bot.change_presence(status=status, activity=discord.Activity(type=activity_type, name=activity_text))


class BioPage(BasePanelView):
    @discord.ui.button(label="Set nickname", style=discord.ButtonStyle.secondary, emoji="✏️", row=0)
    async def nickname_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NicknameModal(self.guild))

    @discord.ui.button(label="Set status text", style=discord.ButtonStyle.secondary, emoji="💬", row=0)
    async def status_text_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ActivityTextModal(self.bot))

    @discord.ui.select(placeholder="Activity type (Playing/Watching/...)", row=1, options=[
        discord.SelectOption(label="Playing", value="playing", emoji="🎮"),
        discord.SelectOption(label="Watching", value="watching", emoji="👁️"),
        discord.SelectOption(label="Listening to", value="listening", emoji="🎧"),
        discord.SelectOption(label="Competing in", value="competing", emoji="🏆"),
    ])
    async def activity_type_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        bot_settings.set_guild_key(GLOBAL_KEY, "activity_type", select.values[0])
        await apply_presence(self.bot)
        await interaction.response.edit_message(embed=build_bio_embed(self.bot, self.guild), view=self)

    @discord.ui.select(placeholder="Online status", row=2, options=[
        discord.SelectOption(label="Online", value="online", emoji="🟢"),
        discord.SelectOption(label="Idle", value="idle", emoji="🌙"),
        discord.SelectOption(label="Do Not Disturb", value="dnd", emoji="⛔"),
        discord.SelectOption(label="Invisible", value="invisible", emoji="⚫"),
    ])
    async def status_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        bot_settings.set_guild_key(GLOBAL_KEY, "status", select.values[0])
        await apply_presence(self.bot)
        await interaction.response.edit_message(embed=build_bio_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Text-to-speech page
# ---------------------------------------------------------------------------
TTS_VOICE_CHOICES = {
    "en-US-AriaNeural": "Aria (US, female)",
    "en-US-GuyNeural": "Guy (US, male)",
    "en-GB-SoniaNeural": "Sonia (UK, female)",
    "en-GB-RyanNeural": "Ryan (UK, male)",
    "en-AU-NatashaNeural": "Natasha (AU, female)",
}


def build_tts_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    tts_cog = bot.get_cog("TTS")
    active_channel_id = tts_cog.active.get(guild.id) if tts_cog else None
    active_channel = guild.get_channel(active_channel_id) if active_channel_id else None

    music_cog = bot.get_cog("Music")
    state = music_cog.state_for(guild.id) if music_cog else None
    connected = state.voice_client.channel if (state and state.voice_client and state.voice_client.is_connected()) else None

    rate = guild_config.get_guild_key(guild.id, "tts_rate", "+35%")
    voice = guild_config.get_guild_key(guild.id, "tts_voice", "en-US-AriaNeural")
    voice_label = TTS_VOICE_CHOICES.get(voice, voice)

    embed = discord.Embed(title="🗣️ Text-to-Speech", color=BRAND_COLOR)
    embed.description = (
        "Use **Speak now** to say something in your current voice channel. "
        "To have chat read aloud automatically, run `/tts` in the text "
        "channel you want read — it joins your voice channel and reads "
        "that channel (as \"*name* says *message*\") until `/tts` is run "
        "again to stop."
    )
    embed.add_field(
        name="Currently connected to",
        value=connected.mention if connected else "*not connected*",
        inline=False,
    )
    embed.add_field(
        name="Auto-reading",
        value=active_channel.mention if active_channel else "*not active — use `/tts`*",
        inline=False,
    )
    embed.add_field(name="Speaking speed", value=rate, inline=True)
    embed.add_field(name="Voice", value=voice_label, inline=True)
    return embed


class SpeakModal(discord.ui.Modal, title="Speak in voice chat"):
    text = discord.ui.TextInput(label="What should I say?", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, cog, guild: discord.Guild, voice_channel: discord.VoiceChannel):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.voice_channel = voice_channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog._speak(self.guild, self.voice_channel, str(self.text.value))
        except Exception as e:
            await interaction.followup.send(f"⚠️ Couldn't speak that: {e}", ephemeral=True)
            return
        await interaction.followup.send("🗣️ Said it.", ephemeral=True)


_TTS_RATE_RE = re.compile(r"^[+-]\d{1,3}%$")


class TTSSpeedModal(discord.ui.Modal, title="Set TTS speaking speed"):
    rate = discord.ui.TextInput(
        label="Speed (e.g. +35%, +50%, +0%, -10%)",
        placeholder="+35%",
        max_length=6,
    )

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild
        self.rate.default = guild_config.get_guild_key(guild.id, "tts_rate", "+35%")

    async def on_submit(self, interaction: discord.Interaction):
        value = self.rate.value.strip()
        if not _TTS_RATE_RE.match(value):
            await interaction.response.send_message(
                "❌ Use a percentage like `+35%` or `-10%`.", ephemeral=True
            )
            return
        guild_config.set_guild_key(self.guild.id, "tts_rate", value)
        await interaction.response.send_message(f"✅ TTS speed set to `{value}`.", ephemeral=True)


class TTSPage(BasePanelView):
    @discord.ui.button(label="Speak now", style=discord.ButtonStyle.success, emoji="🗣️", row=0)
    async def speak_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = self.guild.get_member(interaction.user.id)
        if not member or not member.voice or not member.voice.channel:
            await interaction.response.send_message("❌ Join a voice channel first.", ephemeral=True)
            return
        cog = self.bot.get_cog("TTS")
        if cog is None:
            await interaction.response.send_message("❌ TTS system isn't loaded.", ephemeral=True)
            return
        await interaction.response.send_modal(SpeakModal(cog, self.guild, member.voice.channel))

    @discord.ui.button(label="Set speed", style=discord.ButtonStyle.secondary, emoji="⏩", row=0)
    async def speed_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TTSSpeedModal(self.guild))

    @discord.ui.select(placeholder="Set TTS voice...", row=1, options=[
        discord.SelectOption(label=label, value=value)
        for value, label in TTS_VOICE_CHOICES.items()
    ])
    async def voice_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        guild_config.set_guild_key(self.guild.id, "tts_voice", select.values[0])
        await interaction.response.edit_message(embed=build_tts_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))



# ---------------------------------------------------------------------------
# Leveling page
# ---------------------------------------------------------------------------
def build_leveling_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    enabled = cfg.get("leveling_enabled", True)
    announce_id = cfg.get("levelup_channel_id")
    announce_ch = guild.get_channel(announce_id) if announce_id else None
    level_roles = cfg.get("level_roles", {})

    embed = discord.Embed(title="⭐ Leveling", color=BRAND_COLOR)
    embed.description = (
        "Members earn XP from chatting and level up automatically. "
        "Pick a role in the dropdown below, then click **Assign to level** "
        "to auto-give it when someone reaches that level."
    )
    embed.add_field(name="Status", value="✅ enabled" if enabled else "❌ disabled", inline=True)
    embed.add_field(
        name="Level-up announcements",
        value=announce_ch.mention if announce_ch else "*in the channel the message was sent*",
        inline=True,
    )
    if level_roles:
        lines = []
        for lvl in sorted(level_roles, key=int):
            role = guild.get_role(level_roles[lvl])
            lines.append(f"**Lvl {lvl}** → {role.mention if role else '*deleted role*'}")
        embed.add_field(name="Level roles", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Level roles", value="*none set*", inline=False)
    return embed


class LevelNumberModal(discord.ui.Modal, title="Set level for this role"):
    level = discord.ui.TextInput(label="Level number (e.g. 5)", max_length=4)

    def __init__(self, guild: discord.Guild, role: discord.Role, parent_view: "LevelingPage"):
        super().__init__()
        self.guild = guild
        self.role = role
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            lvl = int(self.level.value)
            if lvl < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Enter a positive whole number.", ephemeral=True)
            return
        if self.role >= self.guild.me.top_role:
            await interaction.response.send_message(
                "❌ I can't assign that role — move my role above it in Server Settings → Roles.",
                ephemeral=True,
            )
            return
        level_roles = guild_config.get_guild_key(self.guild.id, "level_roles", {})
        level_roles[str(lvl)] = self.role.id
        guild_config.set_guild_key(self.guild.id, "level_roles", level_roles)
        self.parent_view.pending_role = None
        await interaction.response.send_message(
            f"✅ **{self.role.name}** will now be given at level **{lvl}**.", ephemeral=True
        )


class RemoveLevelRoleModal(discord.ui.Modal, title="Remove a level role"):
    level = discord.ui.TextInput(label="Level number to clear")

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        try:
            lvl = int(self.level.value)
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid number.", ephemeral=True)
            return
        level_roles = guild_config.get_guild_key(self.guild.id, "level_roles", {})
        if str(lvl) in level_roles:
            del level_roles[str(lvl)]
            guild_config.set_guild_key(self.guild.id, "level_roles", level_roles)
            await interaction.response.send_message(f"✅ Cleared the role for level **{lvl}**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"No role was set for level **{lvl}**.", ephemeral=True)


class LevelingPage(BasePanelView):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, invoker_id: int):
        super().__init__(bot, guild, invoker_id)
        self.pending_role: discord.Role | None = None

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="1. Pick a role...", row=0)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.pending_role = select.values[0]
        embed = build_leveling_embed(self.guild)
        embed.add_field(
            name="Selected role",
            value=f"{self.pending_role.mention} — now click **Assign to level**",
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="2. Assign to level", style=discord.ButtonStyle.success, emoji="🎯", row=1)
    async def assign_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pending_role is None:
            await interaction.response.send_message("❌ Pick a role from the dropdown first.", ephemeral=True)
            return
        await interaction.response.send_modal(LevelNumberModal(self.guild, self.pending_role, self))

    @discord.ui.button(label="Remove a level role", style=discord.ButtonStyle.danger, emoji="➖", row=1)
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RemoveLevelRoleModal(self.guild))

    @discord.ui.button(label="Toggle leveling on/off", style=discord.ButtonStyle.secondary, emoji="🔁", row=2)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        enabled = guild_config.get_guild_key(self.guild.id, "leveling_enabled", True)
        guild_config.set_guild_key(self.guild.id, "leveling_enabled", not enabled)
        await interaction.response.edit_message(embed=build_leveling_embed(self.guild), view=self)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text],
                        placeholder="Set level-up announcement channel...", row=3)
    async def announce_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        guild_config.set_guild_key(self.guild.id, "levelup_channel_id", select.values[0].id)
        await interaction.response.edit_message(embed=build_leveling_embed(self.guild), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Tickets page
# ---------------------------------------------------------------------------
def build_tickets_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    category_id = cfg.get("ticket_category_id")
    category = guild.get_channel(category_id) if category_id else None
    role_id = cfg.get("ticket_support_role_id")
    role = guild.get_role(role_id) if role_id else None
    log_id = cfg.get("ticket_log_channel_id")
    log_ch = guild.get_channel(log_id) if log_id else None
    open_count = len(cfg.get("open_tickets", {}))

    embed = discord.Embed(title="🎫 Tickets", color=BRAND_COLOR)
    embed.description = (
        "Set a category, support role, and log channel below, then click "
        "**Send ticket panel here** in whichever channel members should use "
        "to open tickets."
    )
    embed.add_field(name="Category", value=category.mention if category else "*not set*", inline=True)
    embed.add_field(name="Support role", value=role.mention if role else "*not set*", inline=True)
    embed.add_field(name="Log channel", value=log_ch.mention if log_ch else "*not set*", inline=True)
    embed.add_field(name="Currently open tickets", value=str(open_count), inline=True)
    return embed


class TicketsPage(BasePanelView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.category],
                        placeholder="Set ticket category...", row=0)
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        guild_config.set_guild_key(self.guild.id, "ticket_category_id", select.values[0].id)
        await interaction.response.edit_message(embed=build_tickets_embed(self.guild), view=self)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Set support role...", row=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        guild_config.set_guild_key(self.guild.id, "ticket_support_role_id", select.values[0].id)
        await interaction.response.edit_message(embed=build_tickets_embed(self.guild), view=self)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text],
                        placeholder="Set log channel...", row=2)
    async def log_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        guild_config.set_guild_key(self.guild.id, "ticket_log_channel_id", select.values[0].id)
        await interaction.response.edit_message(embed=build_tickets_embed(self.guild), view=self)

    @discord.ui.button(label="Send ticket panel here", style=discord.ButtonStyle.success, emoji="🎫", row=3)
    async def send_panel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not guild_config.get_guild_key(self.guild.id, "ticket_category_id"):
            await interaction.response.send_message(
                "❌ Set a category first, or ticket creation will fail for members.", ephemeral=True
            )
            return
        panel_embed = discord.Embed(
            title="🎫 Support Tickets",
            description="Need help? Click the button below to open a private ticket with our team.",
            color=BRAND_COLOR,
        )
        await interaction.channel.send(embed=panel_embed, view=TicketOpenView())
        await interaction.response.send_message(f"✅ Ticket panel sent to {interaction.channel.mention}.", ephemeral=True)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Voice Master (join-to-create) page
# ---------------------------------------------------------------------------
def build_voicemaster_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_config.get_guild(guild.id)
    enabled = cfg.get("vm_enabled", False)
    trigger_id = cfg.get("vm_trigger_channel_id")
    trigger = guild.get_channel(trigger_id) if trigger_id else None
    category_id = cfg.get("vm_category_id")
    category = guild.get_channel(category_id) if category_id else None
    template = cfg.get("vm_name_template", DEFAULT_VM_NAME_TEMPLATE)
    default_limit = cfg.get("vm_default_limit", 0)

    embed = discord.Embed(title="🔊 Voice Master (Join to Create)", color=BRAND_COLOR)
    embed.description = (
        "When someone joins the **trigger channel**, the bot instantly creates "
        "a brand new voice channel just for them and moves them in. They get "
        "full control over it with `/voice lock`, `/voice unlock`, "
        "`/voice limit`, `/voice name`, `/voice permit`, `/voice reject`, "
        "`/voice transfer`, and `/voice claim`. The channel is deleted "
        "automatically once everyone leaves."
    )
    embed.add_field(name="Status", value="✅ enabled" if enabled else "❌ disabled", inline=True)
    embed.add_field(name="Trigger channel", value=trigger.mention if trigger else "*not set*", inline=True)
    embed.add_field(
        name="Category for new channels",
        value=category.mention if category else "*same as trigger channel*",
        inline=True,
    )
    embed.add_field(name="Name template", value=f"`{template}`", inline=True)
    embed.add_field(
        name="Default user limit",
        value=str(default_limit) if default_limit else "unlimited",
        inline=True,
    )
    return embed


DEFAULT_VM_NAME_TEMPLATE = "{user}'s Channel"


class VMNameTemplateModal(discord.ui.Modal, title="Set channel name template"):
    template = discord.ui.TextInput(
        label="Use {user} for their display name",
        placeholder="{user}'s Channel",
        max_length=90,
    )

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild
        self.template.default = guild_config.get_guild_key(guild.id, "vm_name_template", DEFAULT_VM_NAME_TEMPLATE)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.template.value.strip() or DEFAULT_VM_NAME_TEMPLATE
        guild_config.set_guild_key(self.guild.id, "vm_name_template", value)
        await interaction.response.send_message(f"✅ Name template set to `{value}`.", ephemeral=True)


class VMDefaultLimitModal(discord.ui.Modal, title="Set default user limit"):
    limit = discord.ui.TextInput(label="Default limit for new channels (0=unlimited)", max_length=2)

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild
        self.limit.default = str(guild_config.get_guild_key(guild.id, "vm_default_limit", 0))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.limit.value)
            if not (0 <= value <= 99):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Enter a whole number from 0 to 99.", ephemeral=True)
            return
        guild_config.set_guild_key(self.guild.id, "vm_default_limit", value)
        await interaction.response.send_message(
            f"✅ Default user limit set to **{value if value else 'unlimited'}**.", ephemeral=True
        )


class VoiceMasterPage(BasePanelView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.voice],
                        placeholder="Set trigger (join-to-create) channel...", row=0)
    async def trigger_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        guild_config.set_guild_key(self.guild.id, "vm_trigger_channel_id", select.values[0].id)
        guild_config.set_guild_key(self.guild.id, "vm_enabled", True)
        await interaction.response.edit_message(embed=build_voicemaster_embed(self.guild), view=self)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.category],
                        placeholder="Set category for new channels (optional)...", row=1)
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        guild_config.set_guild_key(self.guild.id, "vm_category_id", select.values[0].id)
        await interaction.response.edit_message(embed=build_voicemaster_embed(self.guild), view=self)

    @discord.ui.button(label="Name template", style=discord.ButtonStyle.secondary, emoji="✏️", row=2)
    async def template_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VMNameTemplateModal(self.guild))

    @discord.ui.button(label="Default limit", style=discord.ButtonStyle.secondary, emoji="👥", row=2)
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VMDefaultLimitModal(self.guild))

    @discord.ui.button(label="Enable / Disable", style=discord.ButtonStyle.secondary, emoji="🔁", row=2)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = guild_config.get_guild(self.guild.id)
        if not cfg.get("vm_trigger_channel_id"):
            await interaction.response.send_message(
                "❌ Set a trigger channel first.", ephemeral=True
            )
            return
        guild_config.set_guild_key(self.guild.id, "vm_enabled", not cfg.get("vm_enabled", False))
        await interaction.response.edit_message(embed=build_voicemaster_embed(self.guild), view=self)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        home = PanelHome(self.bot, self.guild, self.invoker_id)
        await self.goto(interaction, home, build_home_embed(self.guild))


# ---------------------------------------------------------------------------
# Cog entrypoint
# ---------------------------------------------------------------------------
class Panel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="panel", description="Open the bot control panel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction):
        view = PanelHome(self.bot, interaction.guild, interaction.user.id)
        embed = build_home_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Panel(bot))
