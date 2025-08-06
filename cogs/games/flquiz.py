import random
import discord
import asyncio
import json
import os
from discord.ext import commands

# ALLOWED_ROLE_ID = 1372934366870638674
QUESTION_FILE = "cogs/data/flquiz_questions.json"  # Adjust path if needed


class FLQuiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = set()
        self.questions = self._load_questions()

    def _load_questions(self):
        try:
            with open(QUESTION_FILE, "r", encoding="utf-8") as f:
                questions = json.load(f)
                return [q for q in questions if "question" in q and "answer" in q]
        except Exception as e:
            print(f"[FLQUIZ] Failed to load questions: {e}")
            return []

    @commands.command(name="flquiz")
    async def start_flquiz(self, ctx, num_questions: int = 3):
        # Permission check
        """
        if ALLOWED_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send(embed=discord.Embed(
            title="🚫 Access Denied",
            description=f"Only users with the `{ALLOWED_ROLE_ID}` role can start a quiz.",
            color=discord.Color.red()
        ))
        return
        """

        if ctx.channel.id in self.active_games:
            await ctx.send("⚠️ A quiz is already running in this channel.")
            return

        if not self.questions:
            await ctx.send(
                "❗ No quiz questions available. Please check the question file."
            )
            return

        self.active_games.add(ctx.channel.id)
        await self._run_quiz(ctx, self.questions, num_questions)
        self.active_games.remove(ctx.channel.id)

    async def _run_quiz(self, ctx, questions, num_questions):
        num_questions = min(num_questions, len(questions))
        winners = set()

        flquiz_embed = discord.Embed(
            title="🧠 Forsaken Legacy Quiz",
            description=f"Starting a new quiz with {num_questions} rounds of questions!\nFirst to answer wins **1x Event Box**.\n*Each player can only win once!*",
            color=discord.Color.purple(),
        )
        await ctx.send(embed=flquiz_embed)

        for i, q in enumerate(random.sample(questions, num_questions), 1):
            question_embed = discord.Embed(
                title=f"❓ Question {i}",
                description=q["question"],
                color=discord.Color.blurple(),
            ).set_footer(text="Reply in chat to answer!")
            await ctx.send(embed=question_embed)

            answered = False

            def check(m):
                return m.channel == ctx.channel and not m.author.bot

            try:
                while not answered:
                    msg = await self.bot.wait_for("message", timeout=10.0, check=check)

                    if msg.author.id in winners:
                        already_won_embed = discord.Embed(
                            description=f"🛑 {msg.author.mention}, you've already won. Let others try!",
                            color=discord.Color.red(),
                        )
                        await ctx.send(embed=already_won_embed)
                        continue

                    if msg.content.lower().strip() == q["answer"].lower().strip():
                        winners.add(msg.author.id)
                        await ctx.send(
                            embed=discord.Embed(
                                description=f"✅ Correct! {msg.author.mention} got it. The answer was **{q['answer']}**.",
                                color=discord.Color.green(),
                            )
                        )
                        answered = True
            except asyncio.TimeoutError:
                await ctx.send(
                    embed=discord.Embed(
                        description=f"⏰ Time's up! The correct answer was **{q['answer']}**.",
                        color=discord.Color.red(),
                    )
                )

        # Wrap-up summary
        if winners:
            mentions = [f"<@{uid}>" for uid in winners]
            summary_embed = (
                discord.Embed(
                    title="🎉 Forsaken Legacy Quiz Finished",
                    description="Congratulations to the winners! Reply your IGN below.",
                    color=discord.Color.gold(),
                )
                .add_field(
                    name="Each winner will get 1x Event Box.", value="\n".join(mentions)
                )
                .set_footer(text="Event Boxes will be sent by GM Yoasobi.")
            )
            await ctx.send(embed=summary_embed)
        else:
            await ctx.send(
                embed=discord.Embed(
                    title="🎉 Forsaken Legacy Quiz - Game Over",
                    description="No one answered any questions correctly. Better luck next time!",
                    color=discord.Color.red(),
                )
            )

async def setup(bot):
    await bot.add_cog(FLQuiz(bot))
