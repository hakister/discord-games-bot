import discord
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="flhelp")
    async def custom_help(self, ctx):
        embed = discord.Embed(title="Aesira Discord Game Bot Commands", color=discord.Color.blue())
        embed.add_field(
            name="!ping", 
            value="Check if the bot is responsive or online", 
            inline=False
        )
        embed.add_field(
            name="!gtn", 
            value="Start a Guess the Number Game", 
            inline=False
        )
        embed.add_field(
            name="!stopgtn", 
            value="Stop currently running Guess the Number Game", 
            inline=False
        )
        embed.add_field(
            name="!gtm", 
            value="Start a Guess the Monster Game with 3 Rounds Default", 
            inline=False
        )
        embed.add_field(
            name="!gtm [number]", 
            value="Start a Guess the Monster Game with [number] Rounds", 
            inline=False
        )
        embed.add_field(
            name="!stopgtm", 
            value="Stop currently running Guess the Monster Game", 
            inline=False
        )
        embed.add_field(
            name="!flquiz", 
            value="Start a Forsaken Legacy Quiz Game with 3 Rounds Default", 
            inline=False
        )
        embed.add_field(
            name="!flquiz [number]", 
            value="Start a Forsaken Legacy Quiz Game with [number] Rounds", 
            inline=False
        )
        embed.add_field(
            name="!stopquiz", 
            value="Stop currently running Forsaken Legacy Quiz Game", 
            inline=False
        )
        embed.add_field(
            name="!flbingo",
            value="Start a Bingo Game with default row_col_diag pattern",
            inline=False,
        )
        embed.add_field(
            name="!flbingo [pattern]",
            value="Start a Bingo Game with the following [pattern]: row_col_diag, blackout, four_corners, f_pattern, or l_pattern.",
            inline=False,
        )
        embed.add_field(
            name="!bingonumbers", 
            value="Show all numbers that have been called so far", 
            inline=False
        )
        embed.add_field(
            name="!bingo", 
            value="Declare Bingo if you have a winning card", 
            inline=False
        )
        embed.add_field(
            name="!stopbingo", 
            value="Stop currently running Bingo Game", 
            inline=False
        )
        embed.add_field(
            name="!raidstart", 
            value="Start a random Raid Boss Battle Event", 
            inline=False
        )
        embed.add_field(
            name="!raidstart [Boss Monster Name]", 
            value="Start a specific Raid Boss Battle Event",
            inline=False,
        )
        embed.add_field(
            name="!joinraid",
            value="Join the currently forming raid.",
            inline=False,
        )
        embed.add_field(
            name="!mystats",
            value="Check your current raid stats (HP, ATK, DEF, etc.)",
            inline=False,
        )
        embed.add_field(
            name="!raidstatus", 
            value="Show current raid status (players & boss).",
            inline=False,
        )
        embed.add_field(
            name="!raidend",
            value="Force end the current raid.",
            inline=False,
        )

        embed.set_footer(
            text="Games are usually held once or twice a day. Winners get Event Boxes!"
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
