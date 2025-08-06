import discord
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="flhelp")
    async def custom_help(self, ctx):
        embed = discord.Embed(title="Aesira Discord Game Bot Commands", color=discord.Color.blue())
        embed.add_field(
            name="!ping", value="Check if the bot is responsive or online", inline=False
        )
        embed.add_field(name="!gtn", value="Start a Guess the Number Game", inline=False)
        embed.add_field(name="!stopgtn", value="Stop currently running Guess the Number Game", inline=False)
        embed.add_field(name="!gtm", value="Start a Guess the Monster Game with 3 Rounds Default", inline=False)
        embed.add_field(name="!gtm [number]", value="Start a Guess the Monster Game with [number] Rounds", inline=False)
        embed.add_field(name="!stopgtm", value="Stop currently running Guess the Monster Game", inline=False)
        embed.add_field(name="!flquiz", value="Start a Forsaken Legacy Quiz Game with 3 Rounds Default", inline=False)
        embed.add_field(name="!flquiz [number]", value="Start a Forsaken Legacy Quiz Game with [number] Rounds", inline=False)
        embed.add_field(name="!stopquiz", value="Stop currently running Forsaken Legacy Quiz Game", inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
