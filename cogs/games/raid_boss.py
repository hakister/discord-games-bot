import random
import asyncio
import json
import discord
from discord.ext import commands
from config import MOD_ID, GROUP_ID, CHANNEL_ID, MONSTER_IMAGE_FOLDER
import os

ALLOWED_ROLE_ID = MOD_ID
GROUP_ROLE_ID = GROUP_ID
ALLOWED_CHANNEL_ID = CHANNEL_ID

# JSON file containing boss data
BOSS_FOLDER = MONSTER_IMAGE_FOLDER
BOSS_FILE = "cogs/data/raid_bosses.json"
REWARD_FILE = "cogs/data/raid_rewards.json"

EMOJI_ATTACK = "⚔️"
EMOJI_HEAL = "💉"
EMOJI_DEFEND = "🛡️"
ACTION_EMOJIS = [EMOJI_ATTACK, EMOJI_HEAL, EMOJI_DEFEND]


class RaidBoss(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active = False
        self.join_phase = False
        self.join_task = None
        self.players = {}
        self.player_order = []
        self.boss = None
        self.called_turn = 0
        self.action_message = None
        self.called_numbers = None
        self.turn_lock = asyncio.Lock()
        self.join_end_time = None

        # Load boss list from JSON file
        try:
            with open(BOSS_FILE, "r", encoding="utf-8") as f:
                self.boss_list = json.load(f)
        except Exception as e:
            print(f"[RaidBoss] ⚠️ Error loading boss data: {e}")
            self.boss_list = []

        # Load reward scaling config
        try:
            with open(REWARD_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # allow old shape where top-level key might be "rewards"
            if isinstance(cfg, dict) and "rewards" in cfg and isinstance(cfg["rewards"], dict):
                cfg = cfg["rewards"]
            self.reward_config = cfg if isinstance(cfg, dict) else {}
        except Exception as e:
            print(f"[RaidBoss] ⚠️ Error loading reward scaling: {e}")
            self.reward_config = {}

        # Ensure required keys exist with safe defaults
        self.reward_config.setdefault("event_boxes", [])
        self.reward_config.setdefault("legacy_tokens", {"enabled": False, "scaling": []})
        self.reward_config.setdefault("treat_boxes", {"enabled": False, "scaling": []})

    # ---------- Commands ----------

    @commands.command(name="raidstart", help="Start a raid boss event. (Admin only)")
    async def raidstart(self, ctx, *, boss_name: str = None):
        """Start a raid. Admins only; allows boss name or random."""
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

        # Find or randomly pick a boss
        boss_data = None
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

        # Set boss stats (use fields from JSON: hp, atk, def, image)
        self.boss = {
            "name": boss_data.get("name", "Unknown"),
            "hp": int(boss_data.get("hp", 1000)),
            "max_hp": int(boss_data.get("hp", 1000)),
            "atk": int(boss_data.get("atk", 200)),
            "defense": int(boss_data.get("def", 50)),
            "image": boss_data.get("image"),
            # ensure berserk flag isn't present initially
            "berserk": False,
        }

        self.join_phase = True
        self.players.clear()
        self.player_order.clear()
        self.called_turn = 0
        self.active = True

        join_duration = 60
        self.join_end_time = asyncio.get_event_loop().time() + join_duration

        # Announce boss
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
                f"• If you do not react in a turn, you **skip your action**\n"
                f"• Each skipped turn causes **-50 HP**, stacking up to **-150 HP per turn**\n"
                f"• Penalty resets when you take an action\n"
            ),
            inline=False,
        )

        if self.boss["image"]:
            img = self.boss["image"]
            # If it's a URL, use it directly
            if isinstance(img, str) and (
                img.startswith("http://") or img.startswith("https://")
            ):
                embed.set_image(url=img)
                await ctx.send(embed=embed)
                self._boss_image_url = img
                self._boss_image_path = None
                self._boss_image_filename = None
            else:
                # Local file: resolve against configured folder if not absolute
                img_path = img or ""
                if not os.path.isabs(img_path) and BOSS_FOLDER:
                    img_path = os.path.join(BOSS_FOLDER, img_path)
                img_path = os.path.abspath(img_path)

                if os.path.exists(img_path):
                    filename = os.path.basename(img_path)
                    file = discord.File(img_path, filename=filename)
                    embed.set_image(url=f"attachment://{filename}")
                    await ctx.send(embed=embed, file=file)
                    self._boss_image_path = img_path
                    self._boss_image_filename = filename
                    self._boss_image_url = None
                else:
                    print(f"[RaidBoss] image not found: {img_path}")
                    await ctx.send(embed=embed)
                    self._boss_image_path = None
                    self._boss_image_filename = None
                    self._boss_image_url = None
        else:
            await ctx.send(embed=embed)
            self._boss_image_path = None
            self._boss_image_filename = None
            self._boss_image_url = None

        self.join_task = self.bot.loop.create_task(
            self._end_join_phase_after(ctx, join_duration)
        )

    async def _end_join_phase_after(self, ctx, delay):
        try:
            await asyncio.sleep(delay)
            async with self.turn_lock:
                self.join_phase = False
                if not self.players:
                    await ctx.send("No players joined the raid — event cancelled.")
                    self.active = False
                    return

                # 🧮 Scale boss stats based on number of players (kept)
                num_players = max(1, len(self.players))
                base_hp = self.boss["hp"]
                base_atk = self.boss["atk"]
                base_def = self.boss["defense"]

                # ⚔️ Scaling rules: +20% HP, +5% ATK, +1% DEF per additional player
                scaled_hp = int(base_hp * (1 + 0.25 * (num_players - 1)))
                scaled_atk = int(base_atk * (1 + 0.07 * (num_players - 1)))
                scaled_def = int(base_def * (1 + 0.05 * (num_players - 1)))

                # Apply new scaled values
                self.boss["hp"] = scaled_hp
                self.boss["max_hp"] = scaled_hp
                self.boss["atk"] = scaled_atk
                self.boss["defense"] = scaled_def

                # 🎉 Announce scaled boss
                embed = discord.Embed(
                    title="🔥 Raid Begins!",
                    description=(
                        f"Boss **{self.boss['name']}** emerges stronger based on your party size!\n\n"
                        f"**Players Joined:** {len(self.players)}\n"
                        f"**HP:** {scaled_hp:,}\n"
                        f"**ATK:** {scaled_atk}\n"
                        f"**DEF:** {scaled_def}"
                    ),
                    color=discord.Color.red(),
                )

                # If the boss image is cached, attach it again
                if getattr(self, "_boss_image_url", None):
                    embed.set_image(url=self._boss_image_url)
                    await ctx.send(embed=embed)
                elif getattr(self, "_boss_image_path", None) and getattr(
                    self, "_boss_image_filename", None
                ):
                    file = discord.File(
                        self._boss_image_path, filename=self._boss_image_filename
                    )
                    embed.set_image(url=f"attachment://{self._boss_image_filename}")
                    await ctx.send(embed=embed, file=file)
                else:
                    await ctx.send(embed=embed)

                # 🌀 Start the turn loop
                await self._turn_loop(ctx)

        except asyncio.CancelledError:
            return

    # --- Keep joinraid, raidstatus, raidend, mystats as before ---
    @commands.command(name="joinraid", help="Join the currently forming raid.")
    async def joinraid(self, ctx):
        """Players call this during the join window to participate."""
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        if not self.join_phase:
            await ctx.send(f"⚠️ There is no open join window right now.")
            return

        if ctx.author.id in self.players:
            await ctx.send(f"✅ {ctx.author.mention}, you're already signed up.")
            return

        # Create player with randomized stats
        player = {
            "id": ctx.author.id,
            "name": getattr(ctx.author, "display_name", ctx.author.name),
            "hp": 1750,
            "max_hp": 1750,
            "atk": random.randint(90, 180),  # randomized ATK
            "defense": random.randint(70, 140),  # randomized DEF
            "alive": True,
            "defending": False,
            "action": None,
            "afk_streak": 0, # track consecutive AFK turns
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

    @commands.command(
        name="raidstatus", help="Show current raid status (players & boss)."
    )
    async def raidstatus(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        if not self.active:
            await ctx.send("⚠️ There is no active raid.")
            return

        embed = discord.Embed(title="🛡️ Raid Status", color=discord.Color.blue())
        # Boss
        if self.boss:
            embed.add_field(
                name=f"Boss: {self.boss['name']}",
                value=f"HP: {self._hp_bar(self.boss['hp'], self.boss['max_hp'])} {self.boss['hp']:,}/{self.boss['max_hp']:,}",
                inline=False,
            )
        # Players
        lines = []
        for pid, p in self.players.items():
            status = "💀" if not p["alive"] else "❤️"
            lines.append(
                f"{status} {p['name']} — {self._hp_bar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}"
            )
        embed.add_field(
            name="Players", value="\n".join(lines) if lines else "(none)", inline=False
        )

        # send embed with boss image if cached
        if getattr(self, "_boss_image_url", None):
            embed.set_image(url=self._boss_image_url)
            await ctx.send(embed=embed)
        elif getattr(self, "_boss_image_path", None) and getattr(
            self, "_boss_image_filename", None
        ):
            file = discord.File(
                self._boss_image_path, filename=self._boss_image_filename
            )
            embed.set_image(url=f"attachment://{self._boss_image_filename}")
            await ctx.send(embed=embed, file=file)
        else:
            await ctx.send(embed=embed)

    @commands.command(name="raidend", help="Force end the current raid (Admin only).")
    async def raidend(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return
        if ALLOWED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.send(
                embed=discord.Embed(
                    title="🚫 Access Denied",
                    description="Only authorized users can end raids.",
                    color=discord.Color.red(),
                )
            )
            return

        if not self.active:
            await ctx.send("⚠️ There is no active raid to end.")
            return

        # cancel join task or stop active raid
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

    # ---------- Internal helpers / turn loop ----------
    async def _turn_loop(self, ctx):
        """Main loop: each turn ask players to react for action (10s), resolve actions, boss attacks, and reward survivors."""
        turn = 1
        self.boss["berserk"] = False  # Track berserk state

        while (
            self.active
            and any(p["alive"] for p in self.players.values())
            and self.boss
            and self.boss["hp"] > 0
        ):
            self.called_turn = turn
            # Reset per-turn flags
            for p in self.players.values():
                p["defending"] = False
                p["action"] = None

            # --- Display turn header ---
            embed = discord.Embed(
                title=f"🔁 Raid Turn {turn}",
                description=(
                    f"Boss **{self.boss['name']}** — HP: {self._hp_bar(self.boss['hp'], self.boss['max_hp'])} "
                    f"{self.boss['hp']:,}/{self.boss['max_hp']:,}\n\n"
                    f"React with your action. You have **10 seconds**.\n\n"
                    f"{EMOJI_ATTACK} — Attack\n"
                    f"{EMOJI_HEAL} — Heal (self-heal)\n"
                    f"{EMOJI_DEFEND} — Defend (apply DEF reduction)"
                ),
                color=discord.Color.dark_gold(),
            )

            msg = None
            # include boss image if available
            if getattr(self, "_boss_image_url", None):
                embed.set_image(url=self._boss_image_url)
                msg = await ctx.send(embed=embed)
            elif getattr(self, "_boss_image_path", None) and getattr(self, "_boss_image_filename", None):
                file = discord.File(self._boss_image_path, filename=self._boss_image_filename)
                embed.set_image(url=f"attachment://{self._boss_image_filename}")
                msg = await ctx.send(embed=embed, file=file)
            else:
                msg = await ctx.send(embed=embed)

            self.action_message = msg

            # --- Add reactions ---
            for em in ACTION_EMOJIS:
                try:
                    await msg.add_reaction(em)
                except Exception:
                    pass

            # --- Wait for reactions ---
            action_map = await self._collect_reactions_for_message(msg, timeout=10)

            # --- Assign actions ---
            inactive_players = []

            for user_id, em in action_map.items():
                if user_id in self.players and self.players[user_id]["alive"]:
                    if em == EMOJI_ATTACK:
                        self.players[user_id]["action"] = "attack"
                    elif em == EMOJI_HEAL:
                        self.players[user_id]["action"] = "heal"
                    elif em == EMOJI_DEFEND:
                        self.players[user_id]["action"] = "defend"

            # ✅ Apply AFK penalties
            for pid, p in self.players.items():
                if not p["alive"]:
                    continue

                if p["action"] is None:
                    # Player skipped — increase AFK streak
                    p["afk_streak"] += 1
                    inactive_players.append(p["name"])

                    # HP penalty based on streak - max 150
                    penalty = min(50 * p["afk_streak"], 150)
                    oldhp = p["hp"]
                    p["hp"] = max(0, p["hp"] - penalty)

                    if p["hp"] <= 0:
                        p["alive"] = False
                else:
                    # ✅ Player acted — reset streak
                    p["afk_streak"] = 0

            # Text display for skipped players
            afk_notice = None
            if inactive_players:
                skipped = ", ".join(inactive_players)
                afk_notice = f"⏳ **Skipped Turn:** {skipped} — They took damage!"

            # --- Resolve player actions ---
            resolution_lines = []
            total_player_damage = 0
            attack_events, heal_events = [], []

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

            # Apply attacks
            for pid, dmg in attack_events:
                net_dmg = max(0, dmg - int(self.boss["defense"] * 0.1))
                self.boss["hp"] = max(0, self.boss["hp"] - net_dmg)
                total_player_damage += net_dmg
                resolution_lines.append(f"⚔️ **{self.players[pid]['name']}** attacked for **{net_dmg}** damage.")

            # Apply heals
            for pid, heal_amt in heal_events:
                p = self.players[pid]
                if not p["alive"]:
                    continue
                old = p["hp"]
                p["hp"] = min(p["max_hp"], p["hp"] + heal_amt)
                resolution_lines.append(f"💉 **{p['name']}** healed themselves for **{p['hp'] - old}** HP.")

            # --- Boss death check before counterattack ---
            if self.boss["hp"] <= 0:
                await ctx.send(embed=discord.Embed(
                    title="🏆 Raid Victory!",
                    description=(f"The players dealt **{total_player_damage}** total damage and defeated "
                                f"**{self.boss['name']}**!"),
                    color=discord.Color.green()
                ))
                break

            # --- Boss phase scaling ---
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

            # --- Boss selects targets dynamically ---
            alive_players = [p for p in self.players.values() if p["alive"]]
            total_players = len(alive_players)
            if total_players <= 3:
                num_targets = 1
            elif total_players <= 6:
                num_targets = 2
            elif total_players <= 9:
                num_targets = 3
            elif total_players <= 12:
                num_targets = 4
            else:
                num_targets = 5

            num_targets = min(num_targets, len(alive_players))
            targets = random.sample(alive_players, num_targets)

            # Add extra berserk hits
            if self.boss.get("berserk", False):
                extra_hits = random.choice([1, 2])
                extra_targets = random.sample(alive_players, min(extra_hits, len(alive_players)))
                targets.extend(extra_targets)

            # --- Boss attack loop ---
            boss_events = []
            for tgt in targets:
                incoming = random.randint(max(1, self.boss["atk"] - 50), self.boss["atk"] + 50)

                # Critical chance
                is_crit = random.random() < 0.1
                if is_crit:
                    incoming = int(incoming * random.uniform(1.5, 2.0))

                # Apply phase scaling multiplier
                incoming = int(incoming * dmg_multiplier)

                # Defense and defend effects
                damage_after_def = max(0, incoming - tgt["defense"])
                if tgt["defending"]:
                    damage_after_def = damage_after_def // 2

                # Apply damage
                oldhp = tgt["hp"]
                tgt["hp"] = max(0, tgt["hp"] - damage_after_def)
                if tgt["hp"] <= 0:
                    tgt["alive"] = False

                crit_text = " ⚡(CRITICAL!)" if is_crit else ""
                boss_events.append((tgt["name"], damage_after_def, oldhp, tgt["hp"], crit_text))

            if total_player_damage > 0:
                resolution_lines.insert(0, f"🔥 Players dealt **{total_player_damage}** total damage to **{self.boss['name']}**.")

            for (tname, dmg, oldhp, newhp, crit_text) in boss_events:
                resolution_lines.append(
                    f"💥 **{self.boss['name']}** hit **{tname}** for **{dmg}** damage{crit_text}. "
                    f"({newhp}/{self.players[next(pid for pid,p in self.players.items() if p['name']==tname)]['max_hp']})"
                )

            # --- Turn summary embed ---
            summary = discord.Embed(title=f"🔔 Turn {turn} Results", color=discord.Color.dark_teal())
            if afk_notice:
                resolution_lines.append(afk_notice)
            summary.description = "\n".join(resolution_lines) if resolution_lines else "No actions this turn."

            players_status = []
            for p in self.players.values():
                status_emoji = "💀" if not p["alive"] else "❤️"
                players_status.append(f"{status_emoji} **{p['name']}** — {self._hp_bar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}")

            summary.add_field(name=f"Boss: {self.boss['name']}", value=f"{self._hp_bar(self.boss['hp'], self.boss['max_hp'])} {self.boss['hp']:,}/{self.boss['max_hp']:,}", inline=False)
            summary.add_field(name="Players", value="\n".join(players_status) or "(none)", inline=False)
            await ctx.send(embed=summary)

            # --- End checks ---
            if not any(p["alive"] for p in self.players.values()):
                await ctx.send(embed=discord.Embed(
                    title="💀 Raid Failed",
                    description="All players were defeated. The boss remains victorious.",
                    color=discord.Color.red()
                ))
                break

            if self.boss["hp"] <= 0:
                break

            turn += 1
            await asyncio.sleep(1)  # brief pause between turns

        # --- Raid End / Rewards Section ---
        survivors = [p for p in self.players.values() if p["alive"]]
        total_joined = len(self.players)

        if self.boss and self.boss["hp"] <= 0:

            if not survivors:
                await ctx.send("Raid finished: Boss defeated but no survivors.")
            else:
                num_survivors = len(survivors)

                # Helper local for safe lookup
                def scaled_amount_for(table_or_list, players):
                    # table_or_list may be a list of rules [{min_players,max_players,amount},...]
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
                    "treat_boxes": {p["id"]: 0 for p in survivors},
                }

                # --- EVENT BOXES ---
                total_boxes = scaled_amount_for(self.reward_config.get("event_boxes", []), total_joined)
                total_boxes = max(0, int(total_boxes))

                if total_boxes <= 0:
                    # nothing to give
                    pass
                elif num_survivors >= total_boxes:
                    # Give 1 each (ignore total_boxes)
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

                # --- LEGACY TOKENS (optional) ---
                legacy_cfg = self.reward_config.get("legacy_tokens", {"enabled": False, "scaling": []})
                if legacy_cfg.get("enabled"):
                    total_tokens = scaled_amount_for(legacy_cfg.get("scaling", []), total_joined)
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
                                    reward_results["legacy_tokens"][shuffled[i]["id"]] += 1

                # --- TRICK-OR-TREAT BOXES (optional) ---
                treat_cfg = self.reward_config.get("treat_boxes", {"enabled": False, "scaling": []})
                if treat_cfg.get("enabled"):
                    total_treats = scaled_amount_for(treat_cfg.get("scaling", []), total_joined)
                    total_treats = max(0, int(total_treats))

                    if total_treats > 0:
                        if num_survivors >= total_treats:
                            for p in survivors:
                                reward_results["treat_boxes"][p["id"]] = 1
                        else:
                            base_share = total_treats // num_survivors
                            leftover = total_treats % num_survivors
                            for p in survivors:
                                reward_results["treat_boxes"][p["id"]] = base_share
                            if leftover > 0:
                                shuffled = survivors.copy()
                                random.shuffle(shuffled)
                                for i in range(leftover):
                                    reward_results["treat_boxes"][shuffled[i]["id"]] += 1
                # ---------- SUMMARY EMBED ----------

                available_rewards_text = []

                # Event Boxes
                available_rewards_text.append(f"📦 **Event Boxes Available:** {total_boxes}")

                # Legacy Tokens
                if legacy_cfg.get("enabled"):
                    lt = scaled_amount_for(legacy_cfg.get("scaling", []), total_joined)
                    available_rewards_text.append(f"🪙 **Legacy Tokens Available:** {lt}")

                # Trick-or-Treat Boxes
                if treat_cfg.get("enabled"):
                    tb = scaled_amount_for(treat_cfg.get("scaling", []), total_joined)
                    available_rewards_text.append(
                        f"🎃 **Trick-or-Treat Boxes Available:** {tb}"
                    )

                reward_lines = []
                for p in survivors:
                    pid = p["id"]
                    ebox = reward_results["event_boxes"][pid]
                    legacy = reward_results["legacy_tokens"][pid]
                    treat = reward_results["treat_boxes"][pid]

                    items = []
                    if ebox > 0:
                        items.append(f"**{ebox}x Event Box{'es' if ebox != 1 else ''}**")
                    if legacy_cfg.get("enabled") and legacy > 0:
                        items.append(f"**{legacy}x Legacy Token{'s' if legacy != 1 else ''}**")
                    if treat_cfg.get("enabled") and treat > 0:
                        items.append(
                            f"**{treat}x Trick-or-Treat Box{'es' if treat != 1 else ''}**"
                        )

                    reward_lines.append(
                        f"🎁 <@{pid}> — {', '.join(items) if items else '*no rewards*'}"
                    )

                embed = discord.Embed(
                    title="🏁 Raid Complete — Players Win!",
                    description=(
                        f"**{self.boss['name']}** has been defeated!\n"
                        f"**Survivors:** {num_survivors} / {total_joined}\n\n"
                        "### 🎉 **Available Rewards**\n"
                        + "\n".join(available_rewards_text)
                        + "\n\n### 🎁 **Reward Distribution**\n"
                        + "\n".join(reward_lines)
                    ),
                    color=discord.Color.gold(),
                )
                await ctx.send(embed=embed)

        # Cleanup
        self.active = False
        self.join_phase = False
        self.join_task = None
        self.action_message = None
        self.boss = None
        self.players.clear()
        self.player_order.clear()

    @commands.command(
        name="mystats", help="Check your current raid stats (HP, ATK, DEF, etc.)"
    )
    async def mystats(self, ctx):
        """Displays the player's current raid stats if they are in an active game."""
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return
        if not self.active:
            await ctx.send(
                embed=discord.Embed(
                    title="ℹ️ No Active Raid",
                    description="There’s no ongoing raid right now.",
                    color=discord.Color.red(),
                )
            )
            return

        player = self.players.get(ctx.author.id)
        if not player:
            await ctx.send(
                embed=discord.Embed(
                    title="🚫 Not in the Raid",
                    description="You are not currently participating in the raid.",
                    color=discord.Color.red(),
                )
            )
            return

        # Create HP bar
        hp_bar = self._hp_bar(player["hp"], player["max_hp"])

        # Build embed
        embed = discord.Embed(
            title=f"📜 Stats for {ctx.author.display_name}", color=discord.Color.blue()
        )
        embed.add_field(
            name="❤️ HP",
            value=f"{hp_bar} {player['hp']}/{player['max_hp']}",
            inline=False,
        )
        embed.add_field(name="⚔️ Attack", value=f"{player['atk']}", inline=True)
        embed.add_field(name="🛡️ Defense", value=f"{player['defense']}", inline=True)
        embed.add_field(
            name="💀 Status",
            value="Alive ✅" if player["alive"] else "Defeated ❌",
            inline=True,
        )

        await ctx.send(embed=embed)

    async def _collect_reactions_for_message(self, message, timeout=10):
        """
        Collect actions using reaction events AND final reaction state.
        Ensures players aren't marked AFK if reactions were changed late.
        """
        action_map = {}
        end_time = asyncio.get_event_loop().time() + timeout

        def check(payload):
            return (
                payload.message_id == message.id
                and payload.user_id != self.bot.user.id
                and str(payload.emoji) in ACTION_EMOJIS
            )

        # Collect ADD events during the window
        while True:
            remaining = end_time - asyncio.get_event_loop().time()
            if remaining <= 0:
                break

            try:
                payload = await self.bot.wait_for(
                    "raw_reaction_add", timeout=remaining, check=check
                )
                action_map[payload.user_id] = str(payload.emoji)
            except asyncio.TimeoutError:
                break

        # ✅ Final reaction state override (fixes flicker/remove issues)
        await message.channel.fetch_message(message.id)  # ensure updated cache
        for reaction in message.reactions:
            if str(reaction.emoji) not in ACTION_EMOJIS:
                continue

            async for user in reaction.users():
                if user.bot:
                    continue
                if user.id in self.players and self.players[user.id]["alive"]:
                    action_map[user.id] = str(reaction.emoji)

        return action_map

    # ---------- Small utilities ----------
    def _hp_bar(self, hp, max_hp, length=12):
        if max_hp <= 0:
            return ""
        ratio = hp / max_hp
        filled = int(round(ratio * length))
        filled = max(0, min(length, filled))
        empty = length - filled
        return "█" * filled + "░" * empty

    def _get_scaled_reward_amount(self, table, player_count):
        """Return the reward amount based on scaling table and player count."""
        for rule in table:
            if rule["min_players"] <= player_count <= rule["max_players"]:
                return rule["amount"]
        return 0  # fallback


async def setup(bot):
    await bot.add_cog(RaidBoss(bot))
