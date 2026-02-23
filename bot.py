import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
from datetime import datetime, timedelta
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ================= DATABASE =================

conn = sqlite3.connect("l2raids.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS raidboss (
    guild_id TEXT,
    name TEXT,
    window_start TEXT,
    window_end TEXT,
    warning_sent INTEGER DEFAULT 0,
    open_sent INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, name)
)
""")
conn.commit()

# ================= BOSS TIMERS =================

BOSS_TIMERS = {
    "barakiel": (12, 9),

    # Field epics
    "queenant": (24, 4),
    "core": (48, 4),
    "orfen": (33, 4),
    "zaken": (45, 4),

    # Grand epics
    "baium": (125, 4),
    "antharas": (192, 4),
    "valakas": (264, 4),
}

# ================= READY EVENT =================

@client.event
async def on_ready():
    for guild in client.guilds:
        await tree.sync(guild=guild)

    print(f"Bot ready: {client.user}")

    if not reminder_loop.is_running():
        reminder_loop.start()

# ================= /kill =================

@tree.command(name="kill", description="Register boss kill")
async def kill(interaction: discord.Interaction, boss: str):
    boss_key = boss.lower().replace(" ", "")
    guild_id = str(interaction.guild.id)

    if boss_key in BOSS_TIMERS:
        fixed_hours, random_hours = BOSS_TIMERS[boss_key]
    else:
        fixed_hours, random_hours = (0.6, 1)

    now = datetime.utcnow()
    window_start = now + timedelta(hours=fixed_hours)
    window_end = window_start + timedelta(hours=random_hours)

    c.execute(
        "REPLACE INTO raidboss VALUES (?, ?, ?, ?, 0, 0)",
        (guild_id, boss_key, window_start.isoformat(), window_end.isoformat())
    )
    conn.commit()

    await interaction.response.send_message(
        f"🔥 {boss.title()} spawn window:\n"
        f"Start: {window_start.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"End: {window_end.strftime('%Y-%m-%d %H:%M UTC')}"
    )

# ================= /next =================

@tree.command(name="next", description="Show countdown for a boss")
async def next_boss(interaction: discord.Interaction, boss: str):
    guild_id = str(interaction.guild.id)
    boss_key = boss.lower().replace(" ", "")

    c.execute(
        "SELECT * FROM raidboss WHERE guild_id=? AND name=?",
        (guild_id, boss_key)
    )
    boss_data = c.fetchone()

    if not boss_data:
        await interaction.response.send_message(
            f"No active timer for {boss.title()}."
        )
        return

    _, name, start_str, end_str, _, _ = boss_data
    start = datetime.fromisoformat(start_str)
    end = datetime.fromisoformat(end_str)
    now = datetime.utcnow()

    if now < start:
        remaining = start - now
        hours, remainder = divmod(int(remaining.total_seconds()), 3600)
        minutes = remainder // 60

        await interaction.response.send_message(
            f"🔥 **{name.title()}**\n\n"
            f"⏳ Window Opens In: {hours}h {minutes}m"
        )

    elif start <= now < end:
        remaining = end - now
        hours, remainder = divmod(int(remaining.total_seconds()), 3600)
        minutes = remainder // 60

        await interaction.response.send_message(
            f"🔥 **{name.title()}**\n\n"
            f"⚔ **SPAWN WINDOW ACTIVE**\n"
            f"❌ Closes In: {hours}h {minutes}m"
        )

    else:
        await interaction.response.send_message(
            f"{name.title()} window already closed."
        )

# ================= /raids DASHBOARD =================

@tree.command(name="raids", description="Show countdown for all active bosses")
async def raids(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    now = datetime.utcnow()

    c.execute("SELECT * FROM raidboss WHERE guild_id=?", (guild_id,))
    bosses = c.fetchall()

    if not bosses:
        await interaction.response.send_message("No active raid timers.")
        return

    boss_list = []

    for boss in bosses:
        _, name, start_str, end_str, _, _ = boss

        print("DEBUG:", name, warning_sent, open_sent)
        
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)

        if now < start:
            remaining = start - now
            status = "upcoming"
            seconds = remaining.total_seconds()
        elif start <= now < end:
            remaining = end - now
            status = "active"
            seconds = remaining.total_seconds()
        else:
            continue

        boss_list.append((seconds, name, start, end, status))

    boss_list.sort(key=lambda x: x[0])

    msg = ""

    for _, name, start, end, status in boss_list:
        if status == "upcoming":
            remaining = start - now
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes = remainder // 60

            msg += (
                f"🔥 **{name.title()}**\n"
                f"⏳ Opens In: {hours}h {minutes}m\n\n"
            )

        elif status == "active":
            remaining = end - now
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes = remainder // 60

            msg += (
                f"🔥 **{name.title()}**\n"
                f"⚔ ACTIVE — Closes In: {hours}h {minutes}m\n\n"
            )

    await interaction.response.send_message(msg)

# ================= REMINDER LOOP =================

@tasks.loop(seconds=10)
async def reminder_loop():
    print("Reminder loop tick")

    await client.wait_until_ready()
    now = datetime.utcnow()

    for guild in client.guilds:

        channel = guild.get_channel(YOUR_CHANNEL_ID)

        if not channel:
            print("Channel not found in", guild.name)
            continue

        guild_id = str(guild.id)

        print("CHECKING GUILD:", guild.name, guild_id)

        c.execute("SELECT * FROM raidboss WHERE guild_id=?", (guild_id,))
        bosses = c.fetchall()

        print("BOSSES FOUND:", bosses)

        for boss in bosses:
            _, name, start_str, end_str, warning_sent, open_sent = boss

            print("DEBUG:", name, warning_sent, open_sent)

            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)

            warning_time = start - timedelta(minutes=30)

            # 30 min warning
            if not warning_sent and now >= warning_time:
                await channel.send(f"⏳ **{name.title()} window opens in 30 minutes!**")
                c.execute(
                    "UPDATE raidboss SET warning_sent=1 WHERE guild_id=? AND name=?",
                    (guild_id, name)
                )
                conn.commit()

            # Window open
            if not open_sent and now >= start and now < end:
                await channel.send(f"🔥 **{name.title()} SPAWN WINDOW OPEN!**")
                c.execute(
                    "UPDATE raidboss SET open_sent=1 WHERE guild_id=? AND name=?",
                    (guild_id, name)
                )
                conn.commit()

            # Window closed
            if now >= end:
                await channel.send(f"❌ **{name.title()} spawn window closed.**")
                c.execute(
                    "DELETE FROM raidboss WHERE guild_id=? AND name=?",
                    (guild_id, name)
                )
                conn.commit()

# ================= RUN =================

client.run(TOKEN)











