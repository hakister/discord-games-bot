import random
import discord
from discord.ext import commands, tasks
import asyncio
from config import MOD_ID, GROUP_ID, CHANNEL_ID  # Assuming MOD_ROLE_ID is defined in config.py

ALLOWED_ROLE_ID = MOD_ID  # change this to your desired role ID
GROUP_ROLE_ID = GROUP_ID # change this to your desired user group role ID
ALLOWED_CHANNEL_ID = CHANNEL_ID  # change this to your desired channel ID

class Bingo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cards = {}  # player_id -> 5x5 list
        self.called_numbers = set()
        self.game_active = False
        self.call_task = None
        self.current_pattern = "row_col_diag"  # default pattern

    @commands.command(name="flbingo", help="Start a Bingo game and deal cards to players. Optionally specify pattern: row_col_diag, blackout, four_corners, f_pattern, l_pattern")
    async def start_bingo(self, ctx, pattern: str = "row_col_diag"):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return
        if ALLOWED_ROLE_ID not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                title="🚫 Access Denied",
                description="Only GMs/CMs can start Bingo.",
                color=discord.Color.red()
            ))
            return

        if pattern not in ["row_col_diag", "blackout", "four_corners", "f_pattern", "l_pattern"]:
            await ctx.send("❌ Invalid pattern. Use row_col_diag, blackout, four_corners, f_pattern, or l_pattern.")
            return

        if self.game_active:
            await ctx.send("⚠️ A Bingo game is already running!")
            return

        self.cards.clear()
        self.called_numbers.clear()
        self.game_active = True
        self.current_pattern = pattern

        await ctx.send(embed=discord.Embed(
            title="🎲 Bingo Game Starting!",
            description=f"Pattern: **{pattern.replace('_', ' ').title()}**\nReact with ✅ within 30 seconds to join!",
            color=discord.Color.green()
        ).set_footer(text="Winner will get 3 Event Boxes."))

        def check(reaction, user):
            return (
                str(reaction.emoji) == "✅"
                and reaction.message.channel == ctx.channel
                and not user.bot
            )

        players = []
        try:
            while True:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
                if user.id not in [p.id for p in players]:
                    players.append(user)
                    await ctx.send(f"✅ {user.mention} joined the Bingo game!")
        except asyncio.TimeoutError:
            if not players:
                await ctx.send("No players joined. Game cancelled.")
                self.game_active = False
                return

        # Generate cards and DM players
        for player in players:
            card = self.generate_card()
            self.cards[player.id] = card
            try:
                await player.send(embed=self.format_card_embed(card))
            except discord.Forbidden:
                await ctx.send(f"⚠️ Couldn't DM {player.mention}. They will not have a card.")

        await ctx.send(embed=discord.Embed(
            title="✅ All cards have been dealt!",
            description=f"Game will now begin! Pattern: **{pattern.replace('_', ' ').title()}**",
            color=discord.Color.blurple()
        ))

        self.call_task = self.bot.loop.create_task(self.call_numbers(ctx))

    async def call_numbers(self, ctx):
        available_numbers = [f"B-{n}" for n in range(1, 16)] + \
                            [f"I-{n}" for n in range(16, 31)] + \
                            [f"N-{n}" for n in range(31, 46)] + \
                            [f"G-{n}" for n in range(46, 61)] + \
                            [f"O-{n}" for n in range(61, 76)]

        random.shuffle(available_numbers)

        for number in available_numbers:
            if not self.game_active:
                return

            self.called_numbers.add(number)
            embed = discord.Embed(
                title="🔔 Bingo Number Called!",
                description=f"**{number}**",
                color=discord.Color.gold()
            ).set_footer(text="Type !bingonumbers to see all called numbers so far. Type !bingo if you have a winning card!")
            await ctx.send(embed=embed)
            await asyncio.sleep(10)  # Wait 10 seconds between calls

    @commands.command(name="bingo", help="Call Bingo if you think you have a winning card!")
    async def call_bingo(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            await ctx.send("⚠️ This command can only be used in the #discord-games channel.")
            return

        if not self.game_active:
            await ctx.send("⚠️ There is no active Bingo game.")
            return

        card = self.cards.get(ctx.author.id)
        if not card:
            await ctx.send("❌ You are not part of the current Bingo game.")
            return

        if self.check_bingo(card):
            self.game_active = False
            if self.call_task:
                self.call_task.cancel()

            await ctx.send(embed=discord.Embed(
                title="🎉 BINGO!",
                description=f"{ctx.author.mention} has won the game with pattern **{self.current_pattern.replace('_', ' ').title()}**!",
                color=discord.Color.green()
            ).set_footer(text="Please reply with your IGN. Your Event Boxes will be sent by [CM] Gold Ship after the event."))
        else:
            await ctx.send(f"❌ Sorry {ctx.author.mention}, you don't have a Bingo yet!")

    @commands.command(name="stopbingo", help="End the current Bingo game early (GM/CM only).")
    async def end_bingo(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return
        if ALLOWED_ROLE_ID not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                title="🚫 Access Denied",
                description="Only GMs/CMs can end Bingo early.",
                color=discord.Color.red()
            ))
            return

        if not self.game_active:
            await ctx.send("⚠️ There is no active Bingo game to end.")
            return

        self.game_active = False
        if self.call_task:
            self.call_task.cancel()

        await ctx.send(embed=discord.Embed(
            title="🛑 Bingo Game Ended",
            description=f"The game was ended early by {ctx.author.mention}.",
            color=discord.Color.orange()
        ))

    @commands.command(name="bingonumbers", help="Show all numbers that have been called so far.")
    async def show_called_numbers(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            await ctx.send("⚠️ This command can only be used in the discord-games channel.")
            return

        if not self.game_active:
            await ctx.send("⚠️ There is no active Bingo game.")
            return

        if not self.called_numbers:
            await ctx.send("ℹ️ No numbers have been called yet.")
            return

        groups = {"B": [], "I": [], "N": [], "G": [], "O": []}
        for num in sorted(self.called_numbers, key=lambda x: (x[0], int(x.split('-')[1]))):
            letter, value = num.split('-')
            groups[letter].append(value)

        lines = []
        for letter in ["B", "I", "N", "G", "O"]:
            line = f"{letter}: " + ", ".join(groups[letter]) if groups[letter] else f"{letter}: (none)"
            lines.append(line)

        embed = discord.Embed(
            title="📋 Called Numbers So Far",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)

    def generate_card(self):
        card = []
        columns = [range(1, 16), range(16, 31), range(31, 46), range(46, 61), range(61, 76)]
        for col in columns:
            card.append(random.sample(col, 5))
        card[2][2] = "FREE"  # Free space in the middle
        return card

    def format_card_embed(self, card):
        embed = discord.Embed(title="🎲 Your Bingo Card", color=discord.Color.blue())

        header = "".join(letter.center(4) for letter in ["B", "I", "N", "G", "O"])
        rows = []
        for r in range(5):
            row_values = []
            for c in range(5):
                val = str(card[c][r])
                row_values.append(val.center(4))
            rows.append("".join(row_values))

        embed.description = f"```{header}\n" + "\n".join(rows) + "```"
        embed.set_footer(text=f"Pattern: {self.current_pattern.replace('_', ' ').title()}\nMark numbers manually and call !bingo in #discord-games when you win!")
        return embed

    def check_bingo(self, card):
        marked = [[(str(card[c][r]) == "FREE") or (self.format_number(c, card[c][r]) in self.called_numbers) for c in range(5)] for r in range(5)]

        if self.current_pattern == "row_col_diag":
            for r in range(5):
                if all(marked[r]):
                    return True
            for c in range(5):
                if all(marked[r][c] for r in range(5)):
                    return True
            if all(marked[i][i] for i in range(5)):
                return True
            if all(marked[i][4 - i] for i in range(5)):
                return True
        elif self.current_pattern == "blackout":
            return all(all(row) for row in marked)
        elif self.current_pattern == "four_corners":
            return marked[0][0] and marked[0][4] and marked[4][0] and marked[4][4]
        elif self.current_pattern == "f_pattern":
            col_full = all(marked[r][0] for r in range(5))
            top_row = all(marked[0][c] for c in range(5))
            mid_row = all(marked[2][c] for c in range(5))
            if col_full and top_row and mid_row:
                return True
        elif self.current_pattern == "l_pattern":
            col_full = all(marked[r][0] for r in range(5))
            bottom_row = all(marked[4][c] for c in range(5))
            if col_full and bottom_row:
                return True

        return False

    def format_number(self, col, number):
        prefix = ["B", "I", "N", "G", "O"][col]
        return f"{prefix}-{number}"

async def setup(bot):
    await bot.add_cog(Bingo(bot))
