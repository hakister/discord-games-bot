# cogs/raid_boss.py
import random
import asyncio
import math
import discord
from discord.ext import commands
from config import MOD_ID, GROUP_ID, CHANNEL_ID # Assuming MOD_ROLE_ID is defined in config.py

ALLOWED_ROLE_ID = MOD_ID  # change this to your desired role ID
GROUP_ROLE_ID = GROUP_ID # change this to your desired user group role ID
ALLOWED_CHANNEL_ID = CHANNEL_ID  # change this to your desired channel ID

# emojis for actions
EMOJI_ATTACK = "⚔️"
EMOJI_HEAL = "💉"
EMOJI_DEFEND = "🛡️"
ACTION_EMOJIS = [EMOJI_ATTACK, EMOJI_HEAL, EMOJI_DEFEND]

class RaidBoss(commands.Cog):
    """
    Raid boss Cog — turn-based group-action raid with reaction selection.
    Players join with !joinraid during the join window after !raidstart.
    Each turn the bot posts an embed and players react to pick their action
    (attack / heal / defend). Actions are collected for 20s, resolved together,
    then the boss attacks 1-2 random alive players. Survivors are listed at end.
    """
    def __init__(self, bot):
        self.bot = bot
        # runtime state
        self.active = False
        self.join_phase = False
        self.join_task = None
        self.players = {}           # user_id -> player dict
        self.player_order = []      # list of user ids (not strictly needed here)
        self.boss = None            # boss dict
        self.called_turn = 0
        self.action_message = None
        self.called_numbers = None  # unused here, for parity with other cogs
        self.turn_lock = asyncio.Lock()
        self.join_end_time = None

    # ---------- Commands ----------

    @commands.command(name="raidstart", help="Start a raid boss event. (Admin only)")
    async def raidstart(self, ctx, *, boss_name: str = "The Beast"):
        """Start a raid. Admins only; requires correct channel."""
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        if ALLOWED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                title="🚫 Access Denied",
                description="You don't have permission to start raids.",
                color=discord.Color.red()
            ))
            return

        if self.active:
            await ctx.send("⚠️ A raid is already in progress.")
            return

        # initialize join phase
        self.join_phase = True
        self.players.clear()
        self.player_order.clear()
        self.boss = None
        self.called_turn = 0
        self.active = True

        join_duration = 60  # seconds (fixed, does not reset when players join)
        self.join_end_time = asyncio.get_event_loop().time() + join_duration

        embed = discord.Embed(
            title=f"⚔️ Raid Starting: {boss_name}",
            description=(f"A raid is forming! Type `!joinraid` to join. "
                         f"Join window: **{join_duration} seconds**."),
            color=discord.Color.blurple()
        )
        embed.add_field(name="Actions (choose by reacting during turns)",
                        value=f"{EMOJI_ATTACK} Attack — damage boss\n"
                              f"{EMOJI_HEAL} Heal — heal an ally\n"
                              f"{EMOJI_DEFEND} Defend — reduce incoming damage (DEF applies)\n",
                        inline=False)
        await ctx.send(embed=embed)

        # create background task to end join phase after join_duration
        self.join_task = self.bot.loop.create_task(self._end_join_phase_after(ctx, join_duration))

    async def _end_join_phase_after(self, ctx, delay):
        """Wait `delay` seconds then begin the raid if players joined."""
        try:
            await asyncio.sleep(delay)
            # lock to avoid races
            async with self.turn_lock:
                self.join_phase = False
                if not self.players:
                    await ctx.send("No players joined the raid — event cancelled.")
                    self.active = False
                    return
                # initialize boss and players
                self._finalize_players_and_boss()
                await ctx.send(embed=discord.Embed(
                    title="🔥 Raid Begins!",
                    description=(f"Boss **{self.boss['name']}** appears! "
                                 f"HP: {self.boss['hp']:,}\n"
                                 f"{len(self.players)} players joined."),
                    color=discord.Color.red()
                ))
                # start the turn loop
                await self._turn_loop(ctx)
        except asyncio.CancelledError:
            # join phase cancelled externally (e.g., raid_end)
            return

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
        # HP fixed, ATK & DEF randomized as requested
        player = {
            "id": ctx.author.id,
            "name": getattr(ctx.author, "display_name", ctx.author.name),
            "hp": 1000,
            "max_hp": 1000,
            "atk": random.randint(90, 140),     # randomized ATK
            "defense": random.randint(30, 90),  # randomized DEF
            "alive": True,
            "defending": False,
            "action": None
        }
        self.players[ctx.author.id] = player
        self.player_order.append(ctx.author.id)
        remaining = max(0, int(self.join_end_time - asyncio.get_event_loop().time())) if self.join_end_time else 0
        await ctx.send(f"✅ {ctx.author.mention} joined the raid! ({len(self.players)} players) — {remaining}s left to join.")

    @commands.command(name="raidstatus", help="Show current raid status (players & boss).")
    async def raidstatus(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return

        if not self.active:
            await ctx.send("⚠️ There is no active raid.")
            return

        embed = discord.Embed(title="🛡️ Raid Status", color=discord.Color.blue())
        # Boss
        if self.boss:
            embed.add_field(name=f"Boss: {self.boss['name']}",
                            value=f"HP: {self._hp_bar(self.boss['hp'], self.boss['max_hp'])} {self.boss['hp']:,}/{self.boss['max_hp']:,}",
                            inline=False)
        # Players
        lines = []
        for pid, p in self.players.items():
            status = "💀" if not p["alive"] else "❤️"
            lines.append(f"{status} {p['name']} — {self._hp_bar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}")
        embed.add_field(name="Players", value="\n".join(lines) if lines else "(none)", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="raidend", help="Force end the current raid (Admin only).")
    async def raidend(self, ctx):
        if ctx.channel.id != ALLOWED_CHANNEL_ID:
            return
        if ALLOWED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                title="🚫 Access Denied",
                description="Only authorized users can end raids.",
                color=discord.Color.red()
            ))
            return

        if not self.active:
            await ctx.send("⚠️ There is no active raid to end.")
            return

        # cancel join task or stop active raid
        if self.join_task and not self.join_task.done():
            self.join_task.cancel()
        self.active = False
        self.join_phase = False
        await ctx.send(embed=discord.Embed(
            title="🛑 Raid Ended",
            description=f"The raid was ended early by {ctx.author.mention}.",
            color=discord.Color.orange()
        ))

    # ---------- Internal helpers / turn loop ----------

    def _finalize_players_and_boss(self):
        """Scale boss HP based on number of players and set base boss stats."""
        num_players = max(1, len(self.players))
        base_hp = 1000
        # scale boss HP proportionally (25% more HP per additional player)
        boss_hp = int(base_hp * (1 + 0.25 * (num_players - 1)))
        boss_atk = int(200 * (1 + 0.1 * (num_players - 1)))  # scale a bit as well
        self.boss = {
            "name": "Ravager",
            "hp": boss_hp,
            "max_hp": boss_hp,
            "atk": boss_atk,
            "defense": 80  # boss defense (subtracted from player's damage if you want)
        }

    async def _turn_loop(self, ctx):
        """Main loop: each turn ask players to react for action (20s), resolve actions, boss attacks."""
        turn = 1
        while self.active and any(p["alive"] for p in self.players.values()) and self.boss and self.boss["hp"] > 0:
            self.called_turn = turn
            # reset per-turn flags
            for p in self.players.values():
                p["defending"] = False
                p["action"] = None

            # post action prompt
            embed = discord.Embed(
                title=f"🔁 Raid Turn {turn}",
                description=(f"Boss **{self.boss['name']}** — HP: {self._hp_bar(self.boss['hp'], self.boss['max_hp'])} "
                             f"{self.boss['hp']:,}/{self.boss['max_hp']:,}\n\n"
                             f"React with your action. You have **20 seconds**.\n\n"
                             f"{EMOJI_ATTACK} — Attack\n{EMOJI_HEAL} — Heal (target ally)\n{EMOJI_DEFEND} — Defend (apply DEF reduction)"),
                color=discord.Color.dark_gold()
            )
            msg = await ctx.send(embed=embed)
            self.action_message = msg

            # add reaction options
            for em in ACTION_EMOJIS:
                try:
                    await msg.add_reaction(em)
                except Exception:
                    pass

            # collect reactions for 20 seconds; last reaction per user counts
            action_map = await self._collect_reactions_for_message(msg, timeout=20)

            # map actions to players (only those who joined and alive)
            for user_id, em in action_map.items():
                if user_id in self.players and self.players[user_id]["alive"]:
                    if em == EMOJI_ATTACK:
                        self.players[user_id]["action"] = "attack"
                    elif em == EMOJI_HEAL:
                        self.players[user_id]["action"] = "heal"
                    elif em == EMOJI_DEFEND:
                        self.players[user_id]["action"] = "defend"

            # ensure players who didn't react default to attack (optional) or do nothing
            # here we'll default to attack to keep engagement
            for pid, p in self.players.items():
                if p["alive"] and p["action"] is None:
                    p["action"] = "attack"

            # Resolve player actions
            resolution_lines = []
            total_player_damage = 0
            # apply heals after computing attackers so we keep it fair: process attacks then heals then boss hits
            # we will collect attack damages, perform heals, set defending flags, then boss targets and attacks
            attack_events = []
            heal_events = []
            for pid, p in self.players.items():
                if not p["alive"]:
                    continue
                if p["action"] == "attack":
                    # random damage around atk
                    dmg = random.randint(max(1, p["atk"] - 15), p["atk"] + 20)
                    # subtract boss defense partially (optional), for now apply full dmg
                    attack_events.append((pid, dmg))
                elif p["action"] == "heal":
                    # heal amount as fraction of attack
                    heal_amt = random.randint(int(p["atk"] * 0.5), int(p["atk"] * 1.0))
                    heal_events.append((pid, heal_amt))
                elif p["action"] == "defend":
                    p["defending"] = True

            # apply attacks to boss (sum)
            for pid, dmg in attack_events:
                # optionally reduce by boss defense for each hit (simple approach)
                net_dmg = max(0, dmg - int(self.boss["defense"] * 0.1))  # boss def reduces a small portion
                self.boss["hp"] = max(0, self.boss["hp"] - net_dmg)
                total_player_damage += net_dmg
                resolution_lines.append(f"⚔️ **{self.players[pid]['name']}** attacked for **{net_dmg}** damage.")

            # apply heals (self heal)
            for pid, heal_amt in heal_events:
                p = self.players[pid]
                if not p["alive"]:
                    continue
                old = p["hp"]
                p["hp"] = min(p["max_hp"], p["hp"] + heal_amt)
                resolution_lines.append(
                    f"💉 **{p['name']}** healed themselves for **{p['hp'] - old}** HP."
								)

            # check boss death before boss attacks
            if self.boss["hp"] <= 0:
                await ctx.send(embed=discord.Embed(
                    title="🏆 Raid Victory!",
                    description=(f"The players dealt **{total_player_damage}** total damage and defeated "
                                 f"**{self.boss['name']}**!"),
                    color=discord.Color.green()
                ))
                break

            # Boss attacks: choose 1 or 2 random alive players
            alive_players = [p for p in self.players.values() if p["alive"]]
            if not alive_players:
                # all dead
                break

            num_targets = 1 if len(alive_players) == 1 else random.choice([1, 2])
            targets = random.sample(alive_players, min(num_targets, len(alive_players)))

            boss_events = []
            for tgt in targets:
                # boss incoming damage variance
                incoming = random.randint(max(1, self.boss["atk"] - 50), self.boss["atk"] + 50)
                # apply player's defense
                damage_after_def = max(0, incoming - tgt["defense"])
                def_line = f"🛡️ **{tgt['name']}** blocked **{tgt['defense']}** damage with their defense stat."
                # if defending, halve the remainder (as requested)
                if tgt["defending"]:
                    damage_after_def = damage_after_def // 2
                # apply damage
                oldhp = tgt["hp"]
                tgt["hp"] = max(0, tgt["hp"] - damage_after_def)
                if tgt["hp"] <= 0:
                    tgt["alive"] = False
                boss_events.append((tgt["name"], damage_after_def, oldhp, tgt["hp"]))
            # build resolution summary
            if total_player_damage > 0:
                resolution_lines.insert(0, f"🔥 Players dealt **{total_player_damage}** total damage to **{self.boss['name']}**.")
            if boss_events:
                for (tname, dmg, oldhp, newhp) in boss_events:
                    status = "💀 fallen!" if newhp <= 0 else f"{newhp}/{self.players[next(pid for pid,p in self.players.items() if p['name']==tname)]['max_hp']}"
                    resolution_lines.append(f"💥 **{self.boss['name']}** hit **{tname}** for **{dmg}** damage. ({newhp}/{self.players[next(pid for pid,p in self.players.items() if p['name']==tname)]['max_hp']})")
            # send turn resolution embed
            summary = discord.Embed(title=f"🔔 Turn {turn} Results", color=discord.Color.dark_teal())
            summary.description = "\n".join(resolution_lines) if resolution_lines else "No actions this turn."
            # show boss hp and player statuses
            players_status = []
            for p in self.players.values():
                status_emoji = "💀" if not p["alive"] else "❤️"
                players_status.append(f"{status_emoji} **{p['name']}** — {self._hp_bar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}")
            summary.add_field(name=f"Boss: {self.boss['name']}", value=f"{self._hp_bar(self.boss['hp'], self.boss['max_hp'])} {self.boss['hp']:,}/{self.boss['max_hp']:,}", inline=False)
            summary.add_field(name="Players", value="\n".join(players_status) or "(none)", inline=False)
            await ctx.send(embed=summary)

            # check end conditions
            alive_now = [p for p in self.players.values() if p["alive"]]
            if not alive_now:
                await ctx.send(embed=discord.Embed(
                    title="💀 Raid Failed",
                    description="All players were defeated. The boss remains victorious.",
                    color=discord.Color.red()
                ))
                break
            if self.boss["hp"] <= 0:
                # already handled above, but guard
                break

            turn += 1
            # small delay before next turn
            await asyncio.sleep(1)

        # raid ended, compile survivors
        survivors = [p for p in self.players.values() if p["alive"]]
        if self.boss and self.boss["hp"] <= 0:
            # players won – survivors share rewards (we only list survivors)
            if survivors:
                mention_list = " ".join(f"<@{p['id']}>" for p in survivors)
                await ctx.send(embed=discord.Embed(
                    title="🏁 Raid Complete — Players Win!",
                    description=f"Survivors: {mention_list}\nPlease distribute rewards among survivors.",
                    color=discord.Color.gold()
                ))
            else:
                await ctx.send("Raid finished: Boss defeated but no survivors.")
        else:
            # boss remains or players wiped
            if survivors:
                mention_list = " ".join(f"<@{p['id']}>" for p in survivors)
                await ctx.send(embed=discord.Embed(
                    title="🛡️ Raid Over",
                    description=f"The raid has ended. Survivors: {mention_list}\nDistribute rewards as you see fit.",
                    color=discord.Color.orange()
                ))
            else:
                await ctx.send(embed=discord.Embed(
                    title="💀 Raid Over - Wipe",
                    description="No survivors remain.",
                    color=discord.Color.dark_red()
                ))

        # cleanup
        self.active = False
        self.join_phase = False
        self.join_task = None
        self.action_message = None
        self.boss = None
        self.players.clear()
        self.player_order.clear()

    @commands.command(name="mystats", help="Check your current raid stats (HP, ATK, DEF, etc.)")
    async def mystats(self, ctx):
      """Displays the player's current raid stats if they are in an active game."""
      if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return
      if not self.active:
        await ctx.send(embed=discord.Embed(
            title="ℹ️ No Active Raid",
            description="There’s no ongoing raid right now.",
            color=discord.Color.red()
        ))
        return

      player = self.players.get(ctx.author.id)
      if not player:
        await ctx.send(embed=discord.Embed(
            title="🚫 Not in the Raid",
            description="You are not currently participating in the raid.",
            color=discord.Color.red()
        ))
        return

      # Create HP bar
      hp_bar = self._hp_bar(player["hp"], player["max_hp"])

      # Build embed
      embed = discord.Embed(
          title=f"📜 Stats for {ctx.author.display_name}",
          color=discord.Color.blue()
      )
      embed.add_field(name="❤️ HP", value=f"{hp_bar} {player['hp']}/{player['max_hp']}", inline=False)
      embed.add_field(name="⚔️ Attack", value=f"{player['atk']}", inline=True)
      embed.add_field(name="🛡️ Defense", value=f"{player['defense']}", inline=True)
      embed.add_field(name="💀 Status", value="Alive ✅" if player["alive"] else "Defeated ❌", inline=True)

      await ctx.send(embed=embed)



    async def _collect_reactions_for_message(self, message, timeout=20):
        """
        Listen for reaction_add events on a message for `timeout` seconds.
        Return a mapping of user_id -> emoji (last reaction observed wins).
        """
        action_map = {}  # user_id -> emoji
        end_time = asyncio.get_event_loop().time() + timeout

        def check(payload):
            return payload.message_id == message.id and payload.user_id != self.bot.user.id

        while True:
            remaining = end_time - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                payload = await self.bot.wait_for("raw_reaction_add", timeout=remaining, check=check)
            except asyncio.TimeoutError:
                break
            # interpret payload
            user_id = payload.user_id
            emoji = str(payload.emoji)
            # only accept our action emojis
            if emoji not in ACTION_EMOJIS:
                continue
            # record or overwrite last reaction for this user
            action_map[user_id] = emoji

        return action_map

    # ---------- Small utilities ----------

    def _hp_bar(self, hp, max_hp, length=12):
        """Return a simple text bar like ████░░░░."""
        if max_hp <= 0:
            return ""
        ratio = hp / max_hp
        filled = int(round(ratio * length))
        filled = max(0, min(length, filled))
        empty = length - filled
        return "█" * filled + "░" * empty

# Add Cog
async def setup(bot):
    await bot.add_cog(RaidBoss(bot))
