import discord
import random
import json
import asyncio
import os
from discord.ext import commands
from config import MOD_ID, GROUP_ID, CHANNEL_ID, MONSTER_IMAGE_FOLDER

ALLOWED_ROLE_ID = MOD_ID
GROUP_ROLE_ID = GROUP_ID
ALLOWED_CHANNEL_ID = CHANNEL_ID

MONSTER_DATA_FILE = "cogs/data/monsters.json"
MONSTER_FOLDER = MONSTER_IMAGE_FOLDER


class MonsterQuiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_round = {}
        self.winners = set()
        self.lock = asyncio.Lock()
        self.event_starter = None

        try:
            with open(MONSTER_DATA_FILE, "r", encoding="utf-8") as f:
                self.monsters = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Failed to load monster data: {e}")
            self.monsters = []

    @commands.command(name="gtm")
    async def start_monster_quiz(self, ctx, rounds: int = 3):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        if ALLOWED_ROLE_ID not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                title="🚫 Access Denied",
                description="Only CMs or Admins can start the Guess the Monster game.",
                color=discord.Color.red()
            ))
            return

        if not self.monsters:
            await ctx.send("❗ No monster data available. Cannot start quiz.")
            return

        async with self.lock:
            if ctx.channel.id in self.active_round:
                await ctx.send("⚠️ A monster quiz is already running in this channel.")
                return

            self.active_round[ctx.channel.id] = None
            self.winners.clear()
            self.event_starter = ctx.author.id

        await ctx.send(embed=discord.Embed(
            title="👹 Forsaken Legacy - Guess the Monster Game",
            description=f"Starting a new quiz with **{rounds} round{'s' if rounds != 1 else ''}**! Type your guesses in chat.",
            color=discord.Color.green()
        ))

        # Work with a copy so original list stays intact
        available_monsters = self.monsters.copy()

        for round_num in range(min(rounds, len(available_monsters))):
            if ctx.channel.id not in self.active_round:
                break

            monster = random.choice(available_monsters)
            available_monsters.remove(monster)  # No repeats

            names = monster["name"] if isinstance(monster["name"], list) else [monster["name"]]
            valid_answers = [n.lower().strip() for n in names]

            async with self.lock:
                self.active_round[ctx.channel.id] = {"answer": valid_answers, "guessed": False}

            embed = discord.Embed(
                title=f"🎩 Guess the Monster! Round {round_num + 1}!",
                description="Here's a silhouette... Type your answer in chat!",
                color=discord.Color.dark_gray()
            )

            silhouette_path = monster.get("silhouette", "").strip()
            if not silhouette_path:
                await ctx.send("❗ No silhouette image provided for this monster.")
                continue

            if silhouette_path.startswith(("http://", "https://")):
                embed.set_image(url=silhouette_path)
                await ctx.send(embed=embed)
            else:
                full_path = silhouette_path
                if not os.path.isabs(full_path):
                    full_path = os.path.join(MONSTER_FOLDER, silhouette_path)

                if not os.path.isfile(full_path):
                    await ctx.send(f"❗ Silhouette image not found: `{silhouette_path}`")
                    continue

                file = discord.File(full_path, filename="silhouette.gif" if full_path.endswith(".gif") else "silhouette.jpg")
                embed.set_image(url=f"attachment://{file.filename}")
                await ctx.send(embed=embed, file=file)

            try:
                await asyncio.wait_for(self._wait_for_guess(ctx, monster), timeout=20)
            except asyncio.TimeoutError:
                async with self.lock:
                    round_info = self.active_round.get(ctx.channel.id)
                    if round_info and not round_info["guessed"]:
                        await ctx.send(embed=discord.Embed(
                            title="⏳ Time's Up!",
                            description="No one guessed correctly in this round.",
                            color=discord.Color.orange()
                        ))
                        await self._reveal_monster(ctx, monster, winner=None)
                        self.active_round[ctx.channel.id]["guessed"] = True

        async with self.lock:
            self.active_round.pop(ctx.channel.id, None)

        if self.winners:
            mentions = [f"<@{uid}>" for uid in self.winners]
            summary_embed = discord.Embed(
                title="🏁 Guess the Monster Game Summary",
                description="Congratulations to the winners! Reply your IGN below.",
                color=discord.Color.gold()
            )
            summary_embed.add_field(name="Winners 🎉", value="\n".join(mentions), inline=False)
            summary_embed.set_footer(text="Event Boxes will be sent by GM Yoasobi.")
            await ctx.send(embed=summary_embed)
        else:
            await ctx.send(embed=discord.Embed(
                title="📭 Guess the Monster Game Finished",
                description="No one answered correctly this time. Better luck next game!",
                color=discord.Color.red()
            ))

    async def _wait_for_guess(self, ctx, monster):
        names = monster["name"] if isinstance(monster["name"], list) else [monster["name"]]
        valid_answers = [n.lower().strip() for n in names]

        def check(m):
            return m.channel == ctx.channel and not m.author.bot

        while True:
            if ctx.channel.id not in self.active_round:
                return

            msg = await self.bot.wait_for("message", check=check)

            async with self.lock:
                round_info = self.active_round.get(ctx.channel.id)
                if not round_info or round_info["guessed"]:
                    continue

                if msg.author.id in self.winners:
                    await ctx.send(f"🛑 {msg.author.mention}, you've already answered correctly in this game! Let others try.")
                    continue

                if msg.content.lower().strip() in valid_answers:
                    round_info["guessed"] = True
                    self.winners.add(msg.author.id)
                    await self._reveal_monster(ctx, monster, winner=msg.author)
                    return
                else:
                    await ctx.send(f"❌ Wrong answer, {msg.author.mention}!")

    async def _reveal_monster(self, ctx, monster, winner=None):
        names = monster["name"] if isinstance(monster["name"], list) else [monster["name"]]
        display_names = " or ".join(names)

        reveal_embed = discord.Embed(
            title="👁 Monster Revealed!",
            description=f"The correct answer was **{display_names}**.",
            color=discord.Color.purple()
        )

        if winner:
            reveal_embed.add_field(name="Winner 🎉", value=f"{winner.mention}", inline=False)

        image_path = monster.get("image")
        if not image_path:
            reveal_embed.description += "\n⚠️ No image available."
            await ctx.send(embed=reveal_embed)
            return

        if image_path.startswith(("http://", "https://")):
            reveal_embed.set_image(url=image_path)
            await ctx.send(embed=reveal_embed)
        else:
            # Fix: ensure we look in the monster image folder if not absolute path
            full_path = image_path
            if not os.path.isabs(full_path):
                full_path = os.path.join(MONSTER_FOLDER, image_path)

            if os.path.isfile(full_path):
                file = discord.File(full_path, filename="monster.gif" if full_path.endswith(".gif") else "monster.jpg")
                reveal_embed.set_image(url=f"attachment://{file.filename}")
                await ctx.send(embed=reveal_embed, file=file)
            else:
                reveal_embed.description += "\n⚠️ Image not found."
                await ctx.send(embed=reveal_embed)

    @commands.command(name="stopgtm", help="End the current Guess the Monster game early (event starter only).")
    async def end_monster_quiz(self, ctx):
        if ctx.channel.id not in self.active_round:
            await ctx.send("❗ There is no active Guess the Monster game running in this channel.")
            return

        if getattr(self, "event_starter", None) != ctx.author.id:
            await ctx.send("🚫 Only the event starter can end this game early.")
            return

        async with self.lock:
            self.active_round.pop(ctx.channel.id, None)
            self.winners.clear()
            self.event_starter = None

        await ctx.send(embed=discord.Embed(
            title="🛑 Game Ended Early",
            description=f"The Guess the Monster game has been ended by {ctx.author.mention}.",
            color=discord.Color.red(),
        ))


async def setup(bot):
    await bot.add_cog(MonsterQuiz(bot))
