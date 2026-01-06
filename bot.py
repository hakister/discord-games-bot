import asyncio
import discord
from discord.ext import commands
import os
from config import TOKEN, PREFIX

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
intents.guilds = True
intents.dm_messages = True
intents.dm_reactions = True
intents.integrations = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")


# Dynamically load all cogs
async def load_cogs():
    for folder in ["cogs", "cogs/games"]:
        for filename in os.listdir(folder):
            if filename.endswith(".py") and filename != "__init__.py":
                await bot.load_extension(f"{folder.replace('/', '.')}.{filename[:-3]}")


async def main():
    await load_cogs()
    await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
