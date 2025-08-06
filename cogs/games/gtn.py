import random
import discord
from discord.ext import commands, tasks
import asyncio
from config import MOD_ID, GROUP_ID, CHANNEL_ID  # Assuming MOD_ROLE_ID is defined in config.py

ALLOWED_ROLE_ID = MOD_ID  # change this to your desired role ID
GROUP_ROLE_ID = GROUP_ID # change this to your desired user group role ID
ALLOWED_CHANNEL_ID = CHANNEL_ID  # change this to your desired channel ID

class NumberGuess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_game = {}

    @commands.command(name="gtn", help="Start a new Guess the Number game. The bot picks a number between 1 and 100.")
    async def guess_number(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return  # Ignore command if not in allowed channel
        
        # Check if user has the allowed role
        if ALLOWED_ROLE_ID not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                title="🚫 Access Denied",
                description=f"Only CMs or Admins can start the Guess the Number game.",
                color=discord.Color.red()
            ))
            return
        
        if self.active_game:
            user_id = self.active_game["user_id"]
            await ctx.send(f"⚠️ A game is already in progress by <@{user_id}>. Please wait for it to finish or expire.")
            return
        
        # Start a new game

        number = random.randint(1, 100)
        timeout_task = self.bot.loop.create_task(self.expire_game(ctx))

        self.active_game = {"user_id": ctx.author.id, "target": number, "timeout": timeout_task}

        embed = discord.Embed(
            title="🎲 Forsaken Legacy - Guess the Number Game",
            description=(
                f"Hello! I've picked a number between **1 and 100**.\n"
                "Type your guess in chat!"
            ),
            color=discord.Color.orange(),
        ).set_footer(text="Winner will get 1 Event Box.")
        await ctx.send(embed=embed)

    async def expire_game(self, ctx):
        await asyncio.sleep(600)  # 10 minutes timeout
        if self.active_game:
            user_id = self.active_game["user_id"]
            await ctx.send(f"⌛ <@{user_id}>, your Guess the Number game has expired due to inactivity.")
            self.active_game = None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if not self.active_game: # or message.author.id != self.active_game["user_id"]:
            return

        content = message.content.strip()
        if not content.isdigit():
            return # Ignore non-numeric messages

        guess = int(content)
        target = self.active_game["target"]

        if not (1 <= guess <= 100):
            await message.channel.send(f"❗ {message.author.mention}, your guess must be between 1 and 100.")
            return

        if guess == target:
            embed = discord.Embed(
                title="🎉 Correct!",
                description=f"Well done {message.author.mention}, the number was **{target}**! The game is now over.",
                color=discord.Color.green(),
            ).set_footer(text="Your Event Box will be sent by GM Yoasobi.")
            await message.channel.send(embed=embed)
            self.active_game["timeout"].cancel()
            self.active_game = None
        elif guess < target:
            await message.channel.send(f"🔻 {message.author.mention}, too low! Try a higher number.")
        else:
            await message.channel.send(f"🔺 {message.author.mention}, too high! Try a lower number.")

    @commands.command(name="stopgtn", help="End the current Guess the Number game early (event starter only).")
    async def end_guess_number(self, ctx):
        if not self.active_game:
            await ctx.send("❗ There is no active Guess the Number game to end.")
            return

        # Only the event starter can end the game
        if ctx.author.id != self.active_game["user_id"]:
            await ctx.send("🚫 Only the event starter can end this game early.")
            return

        self.active_game["timeout"].cancel()
        target = self.active_game["target"]
        await ctx.send(
            embed=discord.Embed(
                title="🛑 Game Ended Early",
                description=f"The Guess the Number game has been ended by {ctx.author.mention}. The number was **{target}**.",
                color=discord.Color.red(),
            )
        )
        self.active_game = None                 

async def setup(bot):
    await bot.add_cog(NumberGuess(bot))