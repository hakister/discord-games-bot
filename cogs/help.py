import discord
from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="flhelp")
    async def custom_help(self, ctx):
        embed = discord.Embed(title="Bot Commands", color=discord.Color.blue())
        embed.add_field(name="!ping", value="Check if the bot is responsive", inline=False)
        embed.add_field(name="!gtn", value="Start a number guessing game", inline=False)
        embed.add_field(name="!try [number]", value="Make a guess", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Help(bot))
