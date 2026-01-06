# raid_boss.py
# Button-based Raid Boss Cog (Option A: single shared button row per turn)
# Compatible with Nextcord (2.5.2). If your project uses "discord" directly,
# change `import nextcord as discord` to `import discord`.

import random
import asyncio
import json
import os
import typing
import discord
from discord.ext import commands

from config import MOD_ID, GROUP_ID, CHANNEL_ID, MONSTER_IMAGE_FOLDER

ALLOWED_ROLE_ID = MOD_ID
GROUP_ROLE_ID = GROUP_ID
ALLOWED_CHANNEL_ID = CHANNEL_ID

BOSS_FOLDER = MONSTER_IMAGE_FOLDER
BOSS_FILE = "cogs/data/raid_bosses.json"
REWARD_FILE = "cogs/data/raid_rewards.json"

EMOJI_ATTACK = "⚔️"
EMOJI_HEAL = "💉"
EMOJI_DEFEND = "🛡️"

ACTION_KEYS = {
    "attack": EMOJI_ATTACK,
    "heal": EMOJI_HEAL,
    "defend": EMOJI_DEFEND,
}

BUTTON_TIMEOUT = 10  # seconds per turn to collect actions


class RaidButtons(discord.ui.View):
    """
    Shared single-view for all players per turn.
    user_choices maps user_id -> action_key ("attack"/"heal"/"defend")
    """

    def __init__(self, timeout: float = BUTTON_TIMEOUT):
        super().__init__(timeout=None)
        self.user_choices: dict[int, str] = {}

    async def _safe_ack(self, interaction: discord.Interaction):
        """Prevent 'interaction failed'."""
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except:
                pass

    # ATTACK
    @discord.ui.button(label="Attack", style=discord.ButtonStyle.primary)
    async def attack_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        print("BUTTON FIRED:", interaction.user.id)
        await self._safe_ack(interaction)
        self.user_choices[interaction.user.id] = "attack"
        await interaction.followup.send(
            f"You chose {EMOJI_ATTACK} Attack.", ephemeral=True
        )

    # HEAL
    @discord.ui.button(label="Heal", style=discord.ButtonStyle.success)
    async def heal_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        print("BUTTON FIRED:", interaction.user.id)
        await self._safe_ack(interaction)
        self.user_choices[interaction.user.id] = "heal"
        await interaction.followup.send(f"You chose {EMOJI_HEAL} Heal.", ephemeral=True)

    # DEFEND
    @discord.ui.button(label="Defend", style=discord.ButtonStyle.secondary)
    async def defend_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        print("BUTTON FIRED:", interaction.user.id)
        await self._safe_ack(interaction)
        self.user_choices[interaction.user.id] = "defend"
        await interaction.followup.send(
            f"You chose {EMOJI_DEFEND} Defend.", ephemeral=True
        )


class RaidBoss(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active = False
        self.join_phase = False
        self.join_task: typing.Optional[asyncio.Task] = None
        self.players: dict[int, dict] = {}
        self.player_order: list[int] = []
        self.boss: typing.Optional[dict] = None
        self.called_turn = 0
        self.turn_lock = asyncio.Lock()
        self.join_end_time: float | None = None

        # Simulation controls
        self.simulate = False
        self.simulated_reactors: list[int] = []

        # load files
        try:
            with open(BOSS_FILE, "r", encoding="utf-8") as f:
                self.boss_list = json.load(f)
        except Exception as e:
            print(f"[RaidBoss] Error loading bosses: {e}")
            self.boss_list = []

        try:
            with open(REWARD_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if (
                isinstance(cfg, dict)
                and "rewards" in cfg
                and isinstance(cfg["rewards"], dict)
            ):
                cfg = cfg["rewards"]
            self.reward_config = cfg if isinstance(cfg, dict) else {}
        except Exception as e:
            print(f"[RaidBoss] Error loading rewards: {e}")
            self.reward_config = {}

        # safe defaults
        self.reward_config.setdefault("event_boxes", [])
        self.reward_config.setdefault(
            "legacy_tokens", {"enabled": False, "scaling": []}
        )
        self.reward_config.setdefault("antonio_bags", {"enabled": False, "scaling": []})

    # ---------- Commands ----------
    @commands.command(
        name="raidsim", help="Run a full simulation raid (Admin only)", hidden=True
    )
    async def raidsim(self, ctx, players: int = 30):
        if ALLOWED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            return await ctx.send("You are not allowed to run simulations.")

        if self.active:
            return await ctx.send("A raid is already running.")

        self.simulate = True
        await ctx.send(
            f"🧪 **Raid Simulation Mode ON** — generating {players} fake players..."
        )

        # pick boss and start raid via internal setup (to reuse scaling/pick logic)
        boss = random.choice(self.boss_list)
        await self._setup_boss_from_data(boss)

        # create fake players
        self.players.clear()
        self.player_order.clear()
        for i in range(players):
            fake_id = 990000000000 + i
            self.players[fake_id] = {
                "id": fake_id,
                "name": f"SimPlayer{i+1}",
                "hp": 1750,
                "max_hp": 1750,
                "atk": random.randint(90, 180),
                "defense": random.randint(70, 140),
                "alive": True,
                "defending": False,
                "action": None,
                "afk_streak": 0,
            }
            self.player_order.append(fake_id)

        # apply same scaling
        self._apply_boss_scaling(len(self.players))

        await ctx.send(
            f"🧪 Added **{players} simulated players**. Starting raid now..."
        )
        self.simulated_reactors = list(self.players.keys())
        await self._turn_loop(ctx)
        self.simulate = False

    @commands.command(name="raidstart", help="Start a raid boss event. (Admin only)")
    async def raidstart(self, ctx, *, boss_name: str = None):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        if ALLOWED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.send(
                embed=discord.Embed(
                    title="🚫 Access Denied",
                    description="You don't have permission to start raids.",
                    color=discord.Color.red(),
                )
            )
            return

        if self.active:
            await ctx.send("⚠️ A raid is already in progress.")
            return

        if not self.boss_list:
            await ctx.send(
                "⚠️ No bosses available. Please check your `raid_bosses.json` file."
            )
            return

        # pick boss
        if boss_name:
            boss_data = next(
                (b for b in self.boss_list if b["name"].lower() == boss_name.lower()),
                None,
            )
            if not boss_data:
                await ctx.send(
                    embed=discord.Embed(
                        title="❓ Boss Not Found",
                        description=f"No boss named **{boss_name}** found. Random boss selected instead.",
                        color=discord.Color.orange(),
                    )
                )
                boss_data = random.choice(self.boss_list)
        else:
            boss_data = random.choice(self.boss_list)

        await self._setup_boss_from_data(boss_data)

        # open join phase
        self.join_phase = True
        self.players.clear()
        self.player_order.clear()
        self.called_turn = 0
        self.active = True

        join_duration = 60
        self.join_end_time = asyncio.get_event_loop().time() + join_duration

        embed = discord.Embed(
            title=f"⚔️ Raid Starting: {self.boss['name']} Appears!",
            description=(
                f"Prepare yourselves to battle **{self.boss['name']}** with "
                f"**{self.boss['hp']:,} HP**, **{self.boss['atk']} ATK**, and **{self.boss['defense']} DEF**!\n\n"
                f"Type `!joinraid` to join. You have **{join_duration} seconds** to join."
            ),
            color=discord.Color.red(),
        )
        embed.add_field(
            name="Actions",
            value=(
                f"{EMOJI_ATTACK} Attack — damage the boss\n"
                f"{EMOJI_HEAL} Heal — restore your own HP\n"
                f"{EMOJI_DEFEND} Defend — reduce damage taken this turn\n\n"
                f"⚠️ **AFK Penalty System**\n"
                f"• If you do not act in a turn, you **skip your action**\n"
                f"• Each skipped turn causes **-50 HP**, stacking up to **-150 HP per turn**\n"
                f"• Penalty resets when you take an action"
            ),
            inline=False,
        )

        # attach image if present
        if self.boss.get("image"):
            img = self.boss["image"]
            if isinstance(img, str) and (
                img.startswith("http://") or img.startswith("https://")
            ):
                embed.set_image(url=img)
                await ctx.send(embed=embed)
            else:
                img_path = img or ""
                if not os.path.isabs(img_path) and BOSS_FOLDER:
                    img_path = os.path.join(BOSS_FOLDER, img_path)
                img_path = os.path.abspath(img_path)
                if os.path.exists(img_path):
                    file = discord.File(img_path, filename=os.path.basename(img_path))
                    embed.set_image(url=f"attachment://{os.path.basename(img_path)}")
                    await ctx.send(embed=embed, file=file)
                else:
                    await ctx.send(embed=embed)
        else:
            await ctx.send(embed=embed)

        # schedule join end
        self.join_task = self.bot.loop.create_task(
            self._end_join_phase_after(ctx, join_duration)
        )

    @commands.command(name="joinraid", help="Join the currently forming raid.")
    async def joinraid(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        if not self.join_phase:
            await ctx.send("⚠️ There is no open join window right now.")
            return

        if ctx.author.id in self.players:
            return await ctx.send(f"✅ {ctx.author.mention}, you're already signed up.")

        player = {
            "id": ctx.author.id,
            "name": getattr(ctx.author, "display_name", ctx.author.name),
            "hp": 1750,
            "max_hp": 1750,
            "atk": random.randint(90, 180),
            "defense": random.randint(70, 140),
            "alive": True,
            "defending": False,
            "action": None,
            "afk_streak": 0,
        }
        self.players[ctx.author.id] = player
        self.player_order.append(ctx.author.id)
        remaining = (
            max(0, int(self.join_end_time - asyncio.get_event_loop().time()))
            if self.join_end_time
            else 0
        )
        await ctx.send(
            f"✅ {ctx.author.mention} joined the raid! ({len(self.players)} players) — {remaining}s left to join."
        )

    @commands.command(name="mystats", help="Check your current raid stats (ephemeral).")
    async def mystats(self, ctx):
        """Shows player stats privately only to the user."""
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        # Not in raid
        if not self.active:
            return await ctx.reply("⚠️ There is no active raid.", mention_author=False)

        # Player not joined
        if ctx.author.id not in self.players:
            return await ctx.reply(
                "⚠️ You are not part of this raid.", mention_author=False
            )

        p = self.players[ctx.author.id]

        alive_status = "❤️ Alive" if p["alive"] else "💀 Defeated"

        embed = discord.Embed(
            title=f"📊 Your Raid Stats — {p['name']}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Status", value=alive_status, inline=False)
        embed.add_field(
            name="HP",
            value=f"{self._hp_bar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}",
            inline=False
        )
        embed.add_field(name="ATK", value=str(p["atk"]))
        embed.add_field(name="DEF", value=str(p["defense"]))
        embed.add_field(name="AFK Streak", value=str(p["afk_streak"]))

        # Boss image appears on mystats too
        if self.boss and isinstance(self.boss.get("image"), str):
            img = self.boss["image"]
            if img.startswith("http://") or img.startswith("https://"):
                embed.set_thumbnail(url=img)

        # Send ephemeral
        try:
            await ctx.author.send(embed=embed)
            await ctx.reply("📩 Check your DMs!", mention_author=False)
        except discord.Forbidden:
            await ctx.reply(
                "❌ I couldn't DM you. Please enable DMs from server members.",
                mention_author=False
            )

    @commands.command(
        name="raidstatus", help="Show current raid status (players & boss)."
    )
    async def raidstatus(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return
        if not self.active:
            return await ctx.send("⚠️ There is no active raid.")
        embed = discord.Embed(title="🛡️ Raid Status", color=discord.Color.blue())
        if self.boss:
            embed.add_field(
                name=f"Boss: {self.boss['name']}",
                value=f"HP: {self._hp_bar(self.boss['hp'], self.boss['max_hp'])} {self.boss['hp']:,}/{self.boss['max_hp']:,}",
                inline=False,
            )
        lines = []
        for p in self.players.values():
            status = "💀" if not p["alive"] else "❤️"
            lines.append(
                f"{status} {p['name']} — {self._hp_bar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}"
            )
        embed.add_field(
            name="Players", value="\n".join(lines) if lines else "(none)", inline=False
        )
        # attach image if present
        if (
            self.boss
            and self.boss.get("image")
            and isinstance(self.boss["image"], str)
            and (
                self.boss["image"].startswith("http://")
                or self.boss["image"].startswith("https://")
            )
        ):
            embed.set_image(url=self.boss["image"])
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=embed)

    @commands.command(name="raidend", help="Force end the current raid (Admin only).")
    async def raidend(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return
        if ALLOWED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            return await ctx.send(
                embed=discord.Embed(
                    title="🚫 Access Denied",
                    description="Only authorized users can end raids.",
                    color=discord.Color.red(),
                )
            )
        if not self.active:
            return await ctx.send("⚠️ There is no active raid to end.")
        if self.join_task and not self.join_task.done():
            self.join_task.cancel()
        self.active = False
        self.join_phase = False
        await ctx.send(
            embed=discord.Embed(
                title="🛑 Raid Ended",
                description=f"The raid was ended early by {ctx.author.mention}.",
                color=discord.Color.orange(),
            )
        )

    # ---------- Internal helpers ----------
    async def _setup_boss_from_data(self, boss_data: dict):
        """Initialize boss dict from JSON entry"""
        self.boss = {
            "name": boss_data.get("name", "Unknown"),
            "hp": int(boss_data.get("hp", 1000)),
            "max_hp": int(boss_data.get("hp", 1000)),
            "atk": int(boss_data.get("atk", 200)),
            "defense": int(boss_data.get("def", 50)),
            "image": boss_data.get("image"),
            "berserk": False,
        }
        # mark active
        self.active = True

    def _apply_boss_scaling(self, num_players: int):
        num_players = max(1, num_players)
        base_hp = self.boss["hp"]
        base_atk = self.boss["atk"]
        base_def = self.boss["defense"]
        scaled_hp = int(base_hp * (1 + 0.25 * (num_players - 1)))
        scaled_atk = int(base_atk * (1 + 0.07 * (num_players - 1)))
        scaled_def = int(base_def * (1 + 0.05 * (num_players - 1)))
        self.boss["hp"] = scaled_hp
        self.boss["max_hp"] = scaled_hp
        self.boss["atk"] = scaled_atk
        self.boss["defense"] = scaled_def

    async def _end_join_phase_after(self, ctx, delay: float):
        try:
            await asyncio.sleep(delay)
            async with self.turn_lock:
                self.join_phase = False
                if not self.players:
                    await ctx.send("No players joined the raid — event cancelled.")
                    self.active = False
                    return
                # scale boss
                self._apply_boss_scaling(len(self.players))
                embed = discord.Embed(
                    title="🔥 Raid Begins!",
                    description=(
                        f"Boss **{self.boss['name']}** emerges stronger based on your party size!\n\n"
                        f"**Players Joined:** {len(self.players)}\n"
                        f"**HP:** {self.boss['hp']:,}\n"
                        f"**ATK:** {self.boss['atk']}\n"
                        f"**DEF:** {self.boss['defense']}"
                    ),
                    color=discord.Color.red(),
                )
                # send image if available
                if (
                    self.boss.get("image")
                    and isinstance(self.boss["image"], str)
                    and (
                        self.boss["image"].startswith("http://")
                        or self.boss["image"].startswith("https://")
                    )
                ):
                    embed.set_image(url=self.boss["image"])
                    await ctx.send(embed=embed)
                else:
                    await ctx.send(embed=embed)
                await self._turn_loop(ctx)
        except asyncio.CancelledError:
            return

    async def _turn_loop(self, ctx):
        """Main loop using buttons for input"""
        turn = 1
        if not self.boss:
            return
        self.boss["berserk"] = False

        while (
            self.active
            and any(p["alive"] for p in self.players.values())
            and self.boss
            and self.boss["hp"] > 0
        ):
            self.called_turn = turn
            # reset flags
            for p in self.players.values():
                p["defending"] = False
                p["action"] = None

            # build embed
            embed = discord.Embed(
                title=f"🔁 Raid Turn {turn}",
                description=(
                    f"Boss **{self.boss['name']}** — HP: {self._hp_bar(self.boss['hp'], self.boss['max_hp'])} "
                    f"{self.boss['hp']:,}/{self.boss['max_hp']:,}\n\n"
                    f"Choose your action. You have **{BUTTON_TIMEOUT} seconds**.\n\n"
                    f"{EMOJI_ATTACK} — Attack\n"
                    f"{EMOJI_HEAL} — Heal (self-heal)\n"
                    f"{EMOJI_DEFEND} — Defend (reduce damage this turn)\n"
                ),
                color=discord.Color.dark_gold(),
            )

            # send message with view
            # send message with view, restoring boss image support
            view = RaidButtons()
            boss_img = self.boss.get("image")

            if boss_img:
                if isinstance(boss_img, str) and (
                    boss_img.startswith("http://") or boss_img.startswith("https://")
                ):
                    embed.set_image(url=boss_img)
                    action_msg = await ctx.send(embed=embed, view=view)

                else:
                    # Local file path
                    img_path = boss_img
                    if not os.path.isabs(img_path) and BOSS_FOLDER:
                        img_path = os.path.join(BOSS_FOLDER, img_path)
                    img_path = os.path.abspath(img_path)

                    if os.path.exists(img_path):
                        file = discord.File(
                            img_path, filename=os.path.basename(img_path)
                        )
                        embed.set_image(
                            url=f"attachment://{os.path.basename(img_path)}"
                        )
                        action_msg = await ctx.send(embed=embed, file=file, view=view)
                    else:
                        # file not found fallback
                        action_msg = await ctx.send(embed=embed, view=view)
            else:
                action_msg = await ctx.send(embed=embed, view=view)

            # Collect choices for BUTTON_TIMEOUT seconds
            if self.simulate:
                # Simulate presses across the window; this uses the same view.user_choices mapping
                # but because we can't simulate real interactions, we'll populate directly to mimic load.
                async def simulate_press(pid):
                    if pid not in self.players or not self.players[pid]["alive"]:
                        return
                    await asyncio.sleep(random.uniform(0.02, BUTTON_TIMEOUT - 0.02))
                    # choose action biased to attack for meaningful simulation
                    choice = random.choices(
                        ["attack", "heal", "defend"],
                        weights=[0.6, 0.15, 0.2, 0.05],
                    )[0]
                    view.user_choices[pid] = choice

                # staggered concurrent simulated presses
                await asyncio.gather(
                    *(simulate_press(pid) for pid in self.simulated_reactors)
                )
                # wait out remaining to exactly BUTTON_TIMEOUT
                await asyncio.sleep(0.05)
                # snapshot
                action_map = dict(view.user_choices)
            else:
                # Real players: wait BUTTON_TIMEOUT seconds, letting the view callbacks populate user_choices
                await asyncio.sleep(BUTTON_TIMEOUT)
                action_map = dict(view.user_choices)

            # Always remove view (disable buttons) to avoid late clicks interfering the next turn
            try:
                await action_msg.edit(view=None)
            except Exception:
                # ignore edit errors
                pass

            # assign actions
            inactive_players = []
            for user_id, choice in action_map.items():
                if user_id in self.players and self.players[user_id]["alive"]:
                    if choice == "attack":
                        self.players[user_id]["action"] = "attack"
                    elif choice == "heal":
                        self.players[user_id]["action"] = "heal"
                    elif choice == "defend":
                        self.players[user_id]["action"] = "defend"

            # AFK penalties
            for pid, p in self.players.items():
                if not p["alive"]:
                    continue
                if p["action"] is None:
                    p["afk_streak"] += 1
                    inactive_players.append(p["name"])
                    penalty = min(50 * p["afk_streak"], 150)
                    p["hp"] = max(0, p["hp"] - penalty)
                    if p["hp"] <= 0:
                        p["alive"] = False
                else:
                    p["afk_streak"] = 0

            if inactive_players:
                # limit list length so embed isn't huge
                inactive_preview = ", ".join(inactive_players[:25]) + (
                    ", ..." if len(inactive_players) > 25 else ""
                )
            else:
                inactive_preview = None

            # Resolve player actions
            resolution_lines = []
            total_player_damage = 0
            attack_events = []
            heal_events = []

            for pid, p in self.players.items():
                if not p["alive"]:
                    continue
                if p["action"] == "attack":
                    dmg = random.randint(max(1, p["atk"] - 20), p["atk"] + 25)
                    attack_events.append((pid, dmg))
                elif p["action"] == "heal":
                    heal_amt = random.randint(int(p["atk"] * 0.9), int(p["atk"] * 1.8))
                    heal_events.append((pid, heal_amt))
                elif p["action"] == "defend":
                    p["defending"] = True

            for pid, dmg in attack_events:
                net_dmg = max(0, dmg - int(self.boss["defense"] * 0.1))
                self.boss["hp"] = max(0, self.boss["hp"] - net_dmg)
                total_player_damage += net_dmg
                resolution_lines.append(
                    f"⚔️ **{self.players[pid]['name']}** attacked for **{net_dmg}** damage."
                )

            for pid, heal_amt in heal_events:
                p = self.players[pid]
                if not p["alive"]:
                    continue
                old = p["hp"]
                p["hp"] = min(p["max_hp"], p["hp"] + heal_amt)
                resolution_lines.append(
                    f"💉 **{p['name']}** healed themselves for **{p['hp'] - old}** HP."
                )

            # boss death check before counterattack
            if self.boss["hp"] <= 0:
                await ctx.send(
                    embed=discord.Embed(
                        title="🏆 Raid Victory!",
                        description=(
                            f"The players dealt **{total_player_damage}** total damage and defeated **{self.boss['name']}**!"
                        ),
                        color=discord.Color.green(),
                    )
                )
                break

            # boss phase scaling
            hp_ratio = self.boss["hp"] / self.boss["max_hp"]
            phase_text, dmg_multiplier = None, 1.0
            if hp_ratio <= 0.1:
                dmg_multiplier = 1.45
                phase_text = "🩸 **BERSERK MODE!** ATK increased massively!"
                if not self.boss.get("berserk", False):
                    self.boss["berserk"] = True
                    self.boss["atk"] = int(self.boss["atk"] * 1.5)
            elif hp_ratio <= 0.25:
                dmg_multiplier = 1.35
                phase_text = "😤 Enraged!"
            elif hp_ratio <= 0.5:
                dmg_multiplier = 1.25
                phase_text = "😡 Furious!"
            elif hp_ratio <= 0.75:
                dmg_multiplier = 1.15
                phase_text = "😠 Angry!"
            if phase_text:
                resolution_lines.append(f"🔥 **{self.boss['name']}** is {phase_text}")

            # boss targets
            alive_players = [p for p in self.players.values() if p["alive"]]
            total_alive = len(alive_players)
            if total_alive <= 3:
                num_targets = 1
            elif total_alive <= 6:
                num_targets = 2
            elif total_alive <= 9:
                num_targets = 3
            elif total_alive <= 12:
                num_targets = 4
            else:
                num_targets = 5
            num_targets = min(num_targets, len(alive_players))
            if num_targets > 0:
                targets = random.sample(alive_players, num_targets)
            else:
                targets = []

            if self.boss.get("berserk", False) and alive_players:
                extra_hits = random.choice([1, 2])
                extra_targets = random.sample(
                    alive_players, min(extra_hits, len(alive_players))
                )
                targets.extend(extra_targets)

            boss_events = []
            for tgt in targets:
                incoming = random.randint(
                    max(1, self.boss["atk"] - 50), self.boss["atk"] + 50
                )
                is_crit = random.random() < 0.1
                if is_crit:
                    incoming = int(incoming * random.uniform(1.5, 2.0))
                incoming = int(incoming * dmg_multiplier)
                damage_after_def = max(0, incoming - tgt["defense"])
                if tgt["defending"]:
                    damage_after_def = damage_after_def // 2
                oldhp = tgt["hp"]
                tgt["hp"] = max(0, tgt["hp"] - damage_after_def)
                if tgt["hp"] <= 0:
                    tgt["alive"] = False
                crit_text = " ⚡(CRITICAL!)" if is_crit else ""
                boss_events.append(
                    (tgt["name"], damage_after_def, oldhp, tgt["hp"], crit_text)
                )

            if total_player_damage > 0:
                resolution_lines.insert(
                    0,
                    f"🔥 Players dealt **{total_player_damage}** total damage to **{self.boss['name']}**.",
                )

            for tname, dmg, oldhp, newhp, crit_text in boss_events:
                # find player's max hp for display
                try:
                    pid = next(
                        pid for pid, p in self.players.items() if p["name"] == tname
                    )
                    mhp = self.players[pid]["max_hp"]
                except StopIteration:
                    mhp = 1750
                resolution_lines.append(
                    f"💥 **{self.boss['name']}** hit **{tname}** for **{dmg}** damage{crit_text}. ({newhp}/{mhp})"
                )

            if inactive_preview:
                resolution_lines.append(
                    f"⏳ **Skipped Turn (AFK penalty):** {inactive_preview} — They took damage!"
                )

            # summary embed
            summary = discord.Embed(
                title=f"🔔 Turn {turn} Results", color=discord.Color.dark_teal()
            )
            summary.description = (
                "\n".join(resolution_lines)
                if resolution_lines
                else "No actions this turn."
            )
            players_status = []
            for p in self.players.values():
                status_emoji = "💀" if not p["alive"] else "❤️"
                players_status.append(
                    f"{status_emoji} **{p['name']}** — {self._hp_bar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}"
                )
            summary.add_field(
                name=f"Boss: {self.boss['name']}",
                value=f"{self._hp_bar(self.boss['hp'], self.boss['max_hp'])} {self.boss['hp']:,}/{self.boss['max_hp']:,}",
                inline=False,
            )
            summary.add_field(
                name="Players",
                value="\n".join(players_status) or "(none)",
                inline=False,
            )
            # add boss image to summary too
            boss_img = self.boss.get("image")
            if boss_img:
                if isinstance(boss_img, str) and (
                    boss_img.startswith("http://") or boss_img.startswith("https://")
                ):
                    summary.set_image(url=boss_img)
                    await ctx.send(embed=summary)
                else:
                    img_path = boss_img
                    if not os.path.isabs(img_path) and BOSS_FOLDER:
                        img_path = os.path.join(BOSS_FOLDER, img_path)
                    img_path = os.path.abspath(img_path)
                    if os.path.exists(img_path):
                        file = discord.File(
                            img_path, filename=os.path.basename(img_path)
                        )
                        summary.set_image(
                            url=f"attachment://{os.path.basename(img_path)}"
                        )
                        await ctx.send(embed=summary, file=file)
                    else:
                        await ctx.send(embed=summary)
            else:
                await ctx.send(embed=summary)

            # checks
            if not any(p["alive"] for p in self.players.values()):
                await ctx.send(
                    embed=discord.Embed(
                        title="💀 Raid Failed",
                        description="All players were defeated. The boss remains victorious.",
                        color=discord.Color.red(),
                    )
                )
                break
            if self.boss["hp"] <= 0:
                break

            turn += 1
            await asyncio.sleep(0.2 if self.simulate else 1)

        # end & rewards
        await self._handle_end_and_rewards(ctx)

    async def _handle_end_and_rewards(self, ctx):
        survivors = [p for p in self.players.values() if p["alive"]]
        total_joined = len(self.players)
        if self.boss and self.boss["hp"] <= 0:
            if not survivors:
                await ctx.send("Raid finished: Boss defeated but no survivors.")
            else:
                num_survivors = len(survivors)

                def scaled_amount_for(table_or_list, players):
                    if not isinstance(table_or_list, list):
                        return 0
                    for rule in table_or_list:
                        try:
                            if rule["min_players"] <= players <= rule["max_players"]:
                                return int(rule.get("amount", 0))
                        except Exception:
                            continue
                    return 0

                reward_results = {
                    "event_boxes": {p["id"]: 0 for p in survivors},
                    "legacy_tokens": {p["id"]: 0 for p in survivors},
                    "antonio_bags": {p["id"]: 0 for p in survivors},
                }

                total_boxes = scaled_amount_for(
                    self.reward_config.get("event_boxes", []), total_joined
                )
                total_boxes = max(0, int(total_boxes))

                if total_boxes <= 0:
                    pass
                elif num_survivors >= total_boxes:
                    for p in survivors:
                        reward_results["event_boxes"][p["id"]] = 1
                else:
                    base_share = total_boxes // num_survivors
                    leftover = total_boxes % num_survivors
                    for p in survivors:
                        reward_results["event_boxes"][p["id"]] = base_share
                    if leftover > 0:
                        shuffled = survivors.copy()
                        random.shuffle(shuffled)
                        for i in range(leftover):
                            reward_results["event_boxes"][shuffled[i]["id"]] += 1

                legacy_cfg = self.reward_config.get(
                    "legacy_tokens", {"enabled": False, "scaling": []}
                )
                if legacy_cfg.get("enabled"):
                    total_tokens = scaled_amount_for(
                        legacy_cfg.get("scaling", []), total_joined
                    )
                    total_tokens = max(0, int(total_tokens))
                    if total_tokens > 0:
                        if num_survivors >= total_tokens:
                            for p in survivors:
                                reward_results["legacy_tokens"][p["id"]] = 1
                        else:
                            base_share = total_tokens // num_survivors
                            leftover = total_tokens % num_survivors
                            for p in survivors:
                                reward_results["legacy_tokens"][p["id"]] = base_share
                            if leftover > 0:
                                shuffled = survivors.copy()
                                random.shuffle(shuffled)
                                for i in range(leftover):
                                    reward_results["legacy_tokens"][
                                        shuffled[i]["id"]
                                    ] += 1

                treat_cfg = self.reward_config.get(
                    "antonio_bags", {"enabled": False, "scaling": []}
                )
                if treat_cfg.get("enabled"):
                    total_treats = scaled_amount_for(
                        treat_cfg.get("scaling", []), total_joined
                    )
                    total_treats = max(0, int(total_treats))
                    if total_treats > 0:
                        if num_survivors >= total_treats:
                            for p in survivors:
                                reward_results["antonio_bags"][p["id"]] = 1
                        else:
                            base_share = total_treats // num_survivors
                            leftover = total_treats % num_survivors
                            for p in survivors:
                                reward_results["antonio_bags"][p["id"]] = base_share
                            if leftover > 0:
                                shuffled = survivors.copy()
                                random.shuffle(shuffled)
                                for i in range(leftover):
                                    reward_results["antonio_bags"][
                                        shuffled[i]["id"]
                                    ] += 1

                available_rewards_text = []
                available_rewards_text.append(
                    f"📦 **Event Boxes Available:** {total_boxes}"
                )
                if legacy_cfg.get("enabled"):
                    lt = scaled_amount_for(legacy_cfg.get("scaling", []), total_joined)
                    available_rewards_text.append(
                        f"🪙 **Legacy Tokens Available:** {lt}"
                    )
                if treat_cfg.get("enabled"):
                    tb = scaled_amount_for(treat_cfg.get("scaling", []), total_joined)
                    available_rewards_text.append(
                        f"🎃 **Antonio Bags Available:** {tb}"
                    )

                reward_lines = []
                for p in survivors:
                    pid = p["id"]
                    ebox = reward_results["event_boxes"][pid]
                    legacy = reward_results["legacy_tokens"][pid]
                    treat = reward_results["antonio_bags"][pid]
                    items = []
                    if ebox > 0:
                        items.append(
                            f"**{ebox}x Event Box{'es' if ebox != 1 else ''}**"
                        )
                    if legacy_cfg.get("enabled") and legacy > 0:
                        items.append(
                            f"**{legacy}x Legacy Token{'s' if legacy != 1 else ''}**"
                        )
                    if treat_cfg.get("enabled") and treat > 0:
                        items.append(
                            f"**{treat}x Antonio Bag{'s' if treat != 1 else ''}**"
                        )
                    reward_lines.append(
                        f"🎁 <@{pid}> — {', '.join(items) if items else '*no rewards*'}"
                    )

                embed = discord.Embed(
                    title="🏁 Raid Complete — Players Win!",
                    description=(
                        f"**{self.boss['name']}** has been defeated!\n**Survivors:** {num_survivors} / {total_joined}\n\n"
                        + "### 🎉 **Available Rewards**\n"
                        + "\n".join(available_rewards_text)
                        + "\n\n### 🎁 **Reward Distribution**\n"
                        + "\n".join(reward_lines)
                    ),
                    color=discord.Color.gold(),
                )
                await ctx.send(embed=embed)

        # cleanup state
        self.active = False
        self.join_phase = False
        self.join_task = None
        self.boss = None
        self.players.clear()
        self.player_order.clear()
        self.simulated_reactors = []

    def _hp_bar(self, hp, max_hp, length: int = 12):
        if max_hp <= 0:
            return ""
        ratio = hp / max_hp
        filled = int(round(ratio * length))
        filled = max(0, min(length, filled))
        return "█" * filled + "░" * (length - filled)


async def setup(bot: commands.Bot):
    await bot.add_cog(RaidBoss(bot))
