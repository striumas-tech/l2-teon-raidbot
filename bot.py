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

c.execute("""CREATE TABLE IF NOT EXISTS raidboss (
    name TEXT PRIMARY KEY,
    window_start TEXT,
    window_end TEXT,
    warning_sent INTEGER DEFAULT 0,
    open_sent INTEGER DEFAULT 0
)""")
conn.commit()

# ================= BOSS TIMERS =================

BOSS_TIMERS = {
    # Normal bosses
    "normal": (12, 9),

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

# ================= RAID COMMAND =================

@tree.command(name="kill", description="Register boss kill")
async def kill(interaction: discord.Interaction, boss: str):
    boss_key = boss.lower().replace(" ", "")

    if boss_key not in BOSS_TIMERS:
        await interaction.response.send_message(
            "Boss not recognized. Check spelling.\n"
            "Supported: queenant, core, orfen, zaken, baium, antharas, valakas"
        )
        return

    fixed_hours, random_hours = BOSS_TIMERS[boss_key]

    now = datetime.utcnow()
    window_start = now + timedelta(hours=fixed_hours)
    window_end = window_start + timedelta(hours=random_hours)

    c.execute("REPLACE INTO raidboss VALUES (?, ?, ?, 0, 0)",
              (boss_key, window_start.isoformat(), window_end.isoformat()))
    conn.commit()

    await interaction.response.send_message(
        f"🔥 {boss.title()} spawn window:\n"
        f"Start: {window_start.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"End: {window_end.strftime('%Y-%m-%d %H:%M UTC')}"
    )


@tree.command(name="raids", description="List active raid windows")
async def raids(interaction: discord.Interaction):
    c.execute("SELECT * FROM raidboss")
    bosses = c.fetchall()

    if not bosses:
        await interaction.response.send_message("No active raid windows.")
        return

    msg = ""
    for boss in bosses:
        start = datetime.fromisoformat(boss[1])
        end = datetime.fromisoformat(boss[2])
        msg += (
            f"🔥 {boss[0].title()}\n"
            f"   Start: {start.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"   End: {end.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        )

    await interaction.response.send_message(msg)

# ================= REMINDER LOOP =================

@tasks.loop(minutes=1)
async def reminder_loop():
    await client.wait_until_ready()
    now = datetime.utcnow()

    channel = discord.utils.get(client.get_all_channels(), name="raids")
    if not channel:
        return

    c.execute("SELECT * FROM raidboss")
    bosses = c.fetchall()

    for boss in bosses:
        name, start_str, end_str, warning_sent, open_sent = boss
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)

        # 30 min warning
        if not warning_sent and now >= start - timedelta(minutes=30):
            await channel.send(f"⏳ **{name.title()} window opens in 30 minutes!**")
            c.execute("UPDATE raidboss SET warning_sent=1 WHERE name=?", (name,))
            conn.commit()

        # Window open
        if not open_sent and now >= start:
            await channel.send(f"🔥 **{name.title()} SPAWN WINDOW OPEN!**")
            c.execute("UPDATE raidboss SET open_sent=1 WHERE name=?", (name,))
            conn.commit()

        # Window closed
        if now >= end:
            await channel.send(f"❌ **{name.title()} spawn window closed.**")
            c.execute("DELETE FROM raidboss WHERE name=?", (name,))
            conn.commit()


@client.event
async def on_ready():
    await tree.sync()
    reminder_loop.start()
    print(f"Bot ready: {client.user}")



client.run(TOKEN)
