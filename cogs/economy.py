"""
Virtual-currency economy with animated gambling mini-games: coinflip,
slots, blackjack (simplified), and dice -- plus /rob and /leaderboard.
Currency is per-guild and has no real monetary value. A daily claim
command (with a streak bonus) helps people who go broke recover.

NOTE ON RESPONSIBLE USE: this is play-money for entertainment only. If you
want to be extra safe for younger audiences, consider setting low daily
caps / bet limits via /economy config, or disabling this cog entirely.
"""

import asyncio
import random
import datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import economy_store, guild_config

STARTING_BALANCE = 500
DAILY_AMOUNT = 250
STREAK_BONUS_PER_DAY = 25     # extra coins per consecutive daily streak day
STREAK_BONUS_CAP_DAYS = 10    # streak bonus stops growing past this many days
ROB_COOLDOWN_HOURS = 6
ROB_SUCCESS_CHANCE = 0.45
ROB_MAX_STEAL_PCT = 0.25      # steal at most this fraction of the target's balance
ROB_MIN_TARGET_BALANCE = 50

WIN_COLOR = discord.Color.green()
LOSE_COLOR = discord.Color.red()
NEUTRAL_COLOR = discord.Color.blurple()
ANIM_DELAY = 0.55


def get_starting_balance(guild_id: int) -> int:
    return guild_config.get_guild_key(guild_id, "econ_starting_balance", STARTING_BALANCE)


def get_daily_amount(guild_id: int) -> int:
    return guild_config.get_guild_key(guild_id, "econ_daily_amount", DAILY_AMOUNT)


def get_balance(guild_id: int, user_id: int) -> int:
    return economy_store.get_guild_key(guild_id, str(user_id), get_starting_balance(guild_id))


def set_balance(guild_id: int, user_id: int, amount: int):
    economy_store.set_guild_key(guild_id, str(user_id), max(0, amount))


async def _check_gambling_channel(interaction: discord.Interaction) -> bool:
    """Returns True if the command may proceed. If a gambling channel is
    configured (via /panel -> Economy) and this isn't it, sends an
    ephemeral rejection and returns False."""
    channel_id = guild_config.get_guild_key(interaction.guild.id, "gambling_channel_id")
    if not channel_id or interaction.channel.id == channel_id:
        return True
    await interaction.response.send_message(
        f"❌ Gambling commands can only be used in <#{channel_id}>.", ephemeral=True
    )
    return False


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- misc
    @app_commands.command(name="balance", description="Check your (or someone else's) coin balance")
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        bal = get_balance(interaction.guild.id, member.id)
        embed = discord.Embed(description=f"💰 **{member.display_name}** has **{bal}** coins.", color=NEUTRAL_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily coins (streak bonus for consecutive days)")
    async def daily(self, interaction: discord.Interaction):
        gid, uid = interaction.guild.id, interaction.user.id
        last_key, streak_key = f"daily_{uid}", f"dailystreak_{uid}"
        last = economy_store.get_guild_key(gid, last_key)
        now = datetime.datetime.utcnow()

        streak = economy_store.get_guild_key(gid, streak_key, 0)
        if last:
            last_dt = datetime.datetime.fromisoformat(last)
            elapsed = now - last_dt
            if elapsed < datetime.timedelta(hours=24):
                remaining = datetime.timedelta(hours=24) - elapsed
                hrs = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                await interaction.response.send_message(
                    f"⏳ Already claimed. Try again in {hrs}h {mins}m.", ephemeral=True)
                return
            streak = streak + 1 if elapsed < datetime.timedelta(hours=48) else 1
        else:
            streak = 1

        base = get_daily_amount(gid)
        bonus = min(streak - 1, STREAK_BONUS_CAP_DAYS) * STREAK_BONUS_PER_DAY
        amount = base + bonus
        bal = get_balance(gid, uid)
        set_balance(gid, uid, bal + amount)
        economy_store.set_guild_key(gid, last_key, now.isoformat())
        economy_store.set_guild_key(gid, streak_key, streak)

        embed = discord.Embed(title="✅ Daily claimed!", color=WIN_COLOR)
        embed.add_field(name="Base", value=f"{base} coins", inline=True)
        if bonus:
            embed.add_field(name=f"🔥 Streak bonus (day {streak})", value=f"+{bonus} coins", inline=True)
        embed.add_field(name="New balance", value=f"**{bal + amount}**", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="See the richest members in this server")
    async def leaderboard(self, interaction: discord.Interaction):
        data = economy_store.get_guild(interaction.guild.id)
        balances = [(int(k), v) for k, v in data.items() if k.isdigit() and isinstance(v, int)]
        balances.sort(key=lambda kv: kv[1], reverse=True)

        if not balances:
            await interaction.response.send_message("Nobody has a balance yet.", ephemeral=True)
            return

        top_balance = balances[0][1]
        medals = ["🥇", "🥈", "🥉"]
        bar_len = 10
        lines = []
        for i, (uid, bal) in enumerate(balances[:10]):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            pct = bal / top_balance if top_balance else 0
            filled = round(bar_len * pct)
            bar = "▰" * filled + "▱" * (bar_len - filled)

            if i == 0:
                lines.append(f"{medals[0]} **{name}** — 💰 **{bal:,}**\n`{bar}`")
            elif i < 3:
                lines.append(f"{medals[i]} **{name}** — 💰 **{bal:,}** coins")
            else:
                lines.append(f"`#{i + 1:>2}` **{name}** — 💰 {bal:,} coins")

        embed = discord.Embed(
            title=f"🏆 {interaction.guild.name} High Rollers",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        top_member = interaction.guild.get_member(balances[0][0])
        if top_member:
            embed.set_author(name=f"👑 {top_member.display_name} is the richest", icon_url=top_member.display_avatar.url)

        top_ids = [uid for uid, _ in balances[:10]]
        if interaction.user.id not in top_ids:
            for i, (uid, bal) in enumerate(balances):
                if uid == interaction.user.id:
                    embed.add_field(
                        name="Your rank",
                        value=f"`#{i + 1}` **{interaction.user.display_name}** — 💰 {bal:,} coins",
                        inline=False,
                    )
                    break

        embed.set_footer(text=f"{len(balances)} player(s) on the books • /daily for free coins")
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------------- /rob
    @app_commands.command(name="rob", description="Attempt to rob another member's coins (risky!)")
    async def rob(self, interaction: discord.Interaction, member: discord.Member):
        gid, uid = interaction.guild.id, interaction.user.id
        if member.bot:
            await interaction.response.send_message("❌ You can't rob a bot.", ephemeral=True)
            return
        if member.id == uid:
            await interaction.response.send_message("❌ You can't rob yourself.", ephemeral=True)
            return

        cd_key = f"robcd_{uid}"
        last = economy_store.get_guild_key(gid, cd_key)
        now = datetime.datetime.utcnow()
        if last:
            last_dt = datetime.datetime.fromisoformat(last)
            elapsed = now - last_dt
            if elapsed < datetime.timedelta(hours=ROB_COOLDOWN_HOURS):
                remaining = datetime.timedelta(hours=ROB_COOLDOWN_HOURS) - elapsed
                hrs = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                await interaction.response.send_message(
                    f"⏳ You're laying low. Try robbing again in {hrs}h {mins}m.", ephemeral=True)
                return

        target_bal = get_balance(gid, member.id)
        if target_bal < ROB_MIN_TARGET_BALANCE:
            await interaction.response.send_message(
                f"❌ {member.display_name} is too broke to rob (needs at least {ROB_MIN_TARGET_BALANCE} coins).",
                ephemeral=True)
            return

        economy_store.set_guild_key(gid, cd_key, now.isoformat())
        await interaction.response.send_message(embed=discord.Embed(
            title="🕵️ Sneaking up...", description=f"Attempting to rob **{member.display_name}**...",
            color=NEUTRAL_COLOR))
        await asyncio.sleep(ANIM_DELAY)
        await interaction.edit_original_response(embed=discord.Embed(
            title="🕵️ Picking the lock...", color=NEUTRAL_COLOR))
        await asyncio.sleep(ANIM_DELAY)

        uid_bal = get_balance(gid, uid)
        if random.random() < ROB_SUCCESS_CHANCE:
            steal = max(1, int(target_bal * random.uniform(0.05, ROB_MAX_STEAL_PCT)))
            set_balance(gid, member.id, target_bal - steal)
            set_balance(gid, uid, uid_bal + steal)
            embed = discord.Embed(
                title="💰 Rob successful!",
                description=f"You stole **{steal}** coins from **{member.display_name}**!",
                color=WIN_COLOR)
        else:
            penalty = min(uid_bal, random.randint(10, 100))
            set_balance(gid, uid, uid_bal - penalty)
            embed = discord.Embed(
                title="🚨 Caught red-handed!",
                description=f"You got caught and paid a **{penalty}** coin fine.",
                color=LOSE_COLOR)
        await interaction.edit_original_response(embed=embed)

    def _take_bet(self, interaction: discord.Interaction, bet: int) -> tuple[bool, int]:
        bal = get_balance(interaction.guild.id, interaction.user.id)
        if bet <= 0:
            return False, bal
        if bet > bal:
            return False, bal
        return True, bal

    # -------------------------------------------------------------- coinflip
    @app_commands.command(name="coinflip", description="Bet coins on a coin flip")
    @app_commands.choices(side=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ])
    async def coinflip(self, interaction: discord.Interaction, bet: int, side: app_commands.Choice[str]):
        if not await _check_gambling_channel(interaction):
            return
        ok, bal = self._take_bet(interaction, bet)
        if not ok:
            await interaction.response.send_message(
                "❌ Invalid bet amount." if bet <= 0 else f"❌ You only have {bal} coins.", ephemeral=True)
            return

        result = random.choice(["heads", "tails"])
        won = result == side.value
        delta = bet if won else -bet
        set_balance(interaction.guild.id, interaction.user.id, bal + delta)

        await interaction.response.send_message(embed=discord.Embed(
            title="🪙 Flipping the coin...", color=NEUTRAL_COLOR))
        faces = ["🪙 Heads...", "🪙 Tails..."]
        for i in range(4):
            await asyncio.sleep(ANIM_DELAY)
            await interaction.edit_original_response(embed=discord.Embed(title=faces[i % 2], color=NEUTRAL_COLOR))

        await asyncio.sleep(ANIM_DELAY)
        emoji = "🎉" if won else "💸"
        outcome = f"won **{bet}**" if won else f"lost **{bet}**"
        embed = discord.Embed(
            title=f"🪙 Landed on {result.upper()}! {emoji}",
            description=f"You {outcome} coins.\nNew balance: **{bal + delta}**",
            color=WIN_COLOR if won else LOSE_COLOR)
        await interaction.edit_original_response(embed=embed)

    # ------------------------------------------------------------------ dice
    @app_commands.command(name="dice", description="Bet coins guessing a dice roll (1-6), big payout")
    async def dice(self, interaction: discord.Interaction, bet: int, guess: app_commands.Range[int, 1, 6]):
        if not await _check_gambling_channel(interaction):
            return
        ok, bal = self._take_bet(interaction, bet)
        if not ok:
            await interaction.response.send_message(
                "❌ Invalid bet amount." if bet <= 0 else f"❌ You only have {bal} coins.", ephemeral=True)
            return

        roll = random.randint(1, 6)
        won = roll == guess
        delta = bet * 5 if won else -bet
        set_balance(interaction.guild.id, interaction.user.id, bal + delta)

        dice_faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
        await interaction.response.send_message(embed=discord.Embed(title="🎲 Rolling...", color=NEUTRAL_COLOR))
        for _ in range(4):
            await asyncio.sleep(ANIM_DELAY)
            spin = random.randint(1, 6)
            await interaction.edit_original_response(embed=discord.Embed(
                title=f"🎲 {dice_faces[spin - 1]} Rolling...", color=NEUTRAL_COLOR))

        await asyncio.sleep(ANIM_DELAY)
        outcome = f"won **{delta}**" if won else f"lost **{bet}**"
        embed = discord.Embed(
            title=f"🎲 {dice_faces[roll - 1]} Rolled a {roll}!",
            description=f"You {outcome} coins.\nNew balance: **{bal + delta}**",
            color=WIN_COLOR if won else LOSE_COLOR)
        await interaction.edit_original_response(embed=embed)

    # ----------------------------------------------------------------- slots
    SLOT_EMOJIS = ["🍒", "🍋", "🍇", "🔔", "⭐", "💎"]
    SLOT_PAYOUTS = {"💎": 10, "⭐": 7, "🔔": 5, "🍇": 4, "🍋": 3, "🍒": 2}

    @app_commands.command(name="slots", description="Bet coins on the slot machine")
    async def slots(self, interaction: discord.Interaction, bet: int):
        if not await _check_gambling_channel(interaction):
            return
        ok, bal = self._take_bet(interaction, bet)
        if not ok:
            await interaction.response.send_message(
                "❌ Invalid bet amount." if bet <= 0 else f"❌ You only have {bal} coins.", ephemeral=True)
            return

        spin = [random.choice(self.SLOT_EMOJIS) for _ in range(3)]

        if spin[0] == spin[1] == spin[2]:
            multiplier = self.SLOT_PAYOUTS[spin[0]]
            delta = bet * multiplier
        elif len(set(spin)) == 2:
            delta = bet
        else:
            delta = -bet
        set_balance(interaction.guild.id, interaction.user.id, bal + delta)

        # Reel-lock animation: spin all three, then lock them one at a time
        # (left to right), like a real slot machine.
        await interaction.response.send_message(embed=discord.Embed(title="🎰 | ? | ? | ? |", color=NEUTRAL_COLOR))
        reels = [None, None, None]
        for locking in range(3):
            for _ in range(2):
                await asyncio.sleep(ANIM_DELAY * 0.6)
                preview = [reels[i] or random.choice(self.SLOT_EMOJIS) for i in range(3)]
                await interaction.edit_original_response(embed=discord.Embed(
                    title=f"🎰 | {' | '.join(preview)} |", color=NEUTRAL_COLOR))
            reels[locking] = spin[locking]
            await asyncio.sleep(ANIM_DELAY * 0.6)
            preview = [reels[i] or random.choice(self.SLOT_EMOJIS) for i in range(3)]
            await interaction.edit_original_response(embed=discord.Embed(
                title=f"🎰 | {' | '.join(preview)} |", color=NEUTRAL_COLOR))

        display = " | ".join(spin)
        if spin[0] == spin[1] == spin[2]:
            desc = f"🎉 JACKPOT! x{self.SLOT_PAYOUTS[spin[0]]} payout — won **{delta}** coins!"
            color = WIN_COLOR
        elif len(set(spin)) == 2:
            desc = f"✨ Pair! Won **{delta}** coins."
            color = WIN_COLOR
        else:
            desc = f"💸 No match. Lost **{bet}** coins."
            color = LOSE_COLOR

        embed = discord.Embed(
            title=f"🎰 | {display} |",
            description=f"{desc}\nNew balance: **{bal + delta}**",
            color=color)
        await interaction.edit_original_response(embed=embed)

    # ------------------------------------------------------------ blackjack
    @app_commands.command(name="blackjack", description="Play a simplified round of blackjack against the bot")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if not await _check_gambling_channel(interaction):
            return
        ok, bal = self._take_bet(interaction, bet)
        if not ok:
            await interaction.response.send_message(
                "❌ Invalid bet amount." if bet <= 0 else f"❌ You only have {bal} coins.", ephemeral=True)
            return

        deck_values = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11]

        def draw_hand():
            return [random.choice(deck_values), random.choice(deck_values)]

        def hand_total(hand):
            total = sum(hand)
            aces = hand.count(11)
            while total > 21 and aces:
                total -= 10
                aces -= 1
            return total

        player = draw_hand()
        dealer = draw_hand()

        await interaction.response.send_message(embed=discord.Embed(title="🃏 Dealing...", color=NEUTRAL_COLOR))
        await asyncio.sleep(ANIM_DELAY)
        await interaction.edit_original_response(embed=discord.Embed(
            title="🃏 Dealing cards...",
            description=f"**Your hand:** {player} = {hand_total(player)}\n**Dealer shows:** {dealer[0]}, ?",
            color=NEUTRAL_COLOR))
        await asyncio.sleep(ANIM_DELAY)

        # Very simplified: player auto-stands at >=17, dealer draws to >=17
        while hand_total(player) < 17:
            player.append(random.choice(deck_values))
            await interaction.edit_original_response(embed=discord.Embed(
                title="🃏 You draw...",
                description=f"**Your hand:** {player} = {hand_total(player)}\n**Dealer shows:** {dealer[0]}, ?",
                color=NEUTRAL_COLOR))
            await asyncio.sleep(ANIM_DELAY)

        await interaction.edit_original_response(embed=discord.Embed(
            title="🃏 Dealer reveals...",
            description=f"**Your hand:** {player} = {hand_total(player)}\n**Dealer hand:** {dealer} = {hand_total(dealer)}",
            color=NEUTRAL_COLOR))
        await asyncio.sleep(ANIM_DELAY)

        while hand_total(dealer) < 17:
            dealer.append(random.choice(deck_values))
            await interaction.edit_original_response(embed=discord.Embed(
                title="🃏 Dealer draws...",
                description=f"**Your hand:** {player} = {hand_total(player)}\n**Dealer hand:** {dealer} = {hand_total(dealer)}",
                color=NEUTRAL_COLOR))
            await asyncio.sleep(ANIM_DELAY)

        p_total, d_total = hand_total(player), hand_total(dealer)

        if p_total > 21:
            delta, result = -bet, "You busted! 💥"
        elif d_total > 21:
            delta, result = bet, "Dealer busted — you win! 🎉"
        elif p_total > d_total:
            delta, result = bet, "You win! 🎉"
        elif p_total < d_total:
            delta, result = -bet, "Dealer wins. 💸"
        else:
            delta, result = 0, "Push — bet returned."

        set_balance(interaction.guild.id, interaction.user.id, bal + delta)
        embed = discord.Embed(
            title=result,
            description=(
                f"**Your hand:** {player} = {p_total}\n"
                f"**Dealer hand:** {dealer} = {d_total}\n\n"
                f"New balance: **{bal + delta}**"
            ),
            color=WIN_COLOR if delta > 0 else (LOSE_COLOR if delta < 0 else NEUTRAL_COLOR))
        await interaction.edit_original_response(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
