from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("BOT_PREFIX", "!")
MOD_ID = int(os.getenv("MOD_ROLE_ID"))
GROUP_ID = int(os.getenv("USER_GROUP_ROLE_ID"))
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
