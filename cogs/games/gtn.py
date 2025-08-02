import random
import discord
from discord.ext import commands

# ALLOWED_ROLE_ID = 1372934366870638674  # change this to your desired role ID


class Guess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}

    @commands.command(name="gtn")
    async def guess_number(self, ctx):
        # Check if user has the allowed role
        """allowed_role = discord.utils.get(ctx.author.roles, id=ALLOWED_ROLE_ID)
        if allowed_role is None:
            embed = discord.Embed(
                title="🚫 Access Denied",
                description=f"Only Echo Keepers [Mods] or Admins can start the Guess the Number game.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return"""

        number = random.randint(1, 100)
        self.active_games[ctx.author.id] = number

        embed = discord.Embed(
            title="🎲 Guess the Number",
            description=(
                f"{ctx.author.mention}, I've picked a number between **1 and 100**.\n"
                "Use `!try <number>` to make a guess!"
            ),
            color=discord.Color.orange(),
        )
        await ctx.send(embed=embed)

    @commands.command(name="try")
    async def try_guess(self, ctx, guess: int):
        target = self.active_games.get(ctx.author.id)

        if target is None:
            embed = discord.Embed(
                title="❗ No Active Game",
                description="Wait for CMs or Admins to start a game with `!gtn`.",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return

        if guess == target:
            embed = discord.Embed(
                title="🎉 Correct!",
                description=f"Well done {ctx.author.mention}, the number was **{target}**!",
                color=discord.Color.green(),
            )
            del self.active_games[ctx.author.id]
        elif guess < target:
            embed = discord.Embed(
                title="🔻 Too Low!",
                description="Try a higher number.",
                color=discord.Color.blurple(),
            )
        else:
            embed = discord.Embed(
                title="🔺 Too High!",
                description="Try a lower number.",
                color=discord.Color.blurple(),
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Guess(bot))
