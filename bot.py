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

c.execute("DROP TABLE IF EXISTS raidboss")

c.execute("""CREATE TABLE raidboss (
    guild_id TEXT,
    name TEXT,
    window_start TEXT,
    window_end TEXT,
    warning_sent INTEGER DEFAULT 0,
    open_sent INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, name)
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
    guild_id = str(interaction.guild.id)

    if boss_key in BOSS_TIMERS:
        fixed_hours, random_hours = BOSS_TIMERS[boss_key]
    else:
        fixed_hours, random_hours = (12, 9)

    from datetime import timezone
now = datetime.now(timezone.utc)
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


@tree.command(name="raids", description="List active raid windows")
async def raids(interaction: discord.Interaction):
    try:
        guild_id = str(interaction.guild.id)

        c.execute("SELECT * FROM raidboss WHERE guild_id=?", (guild_id,))
        bosses = c.fetchall()

        if not bosses:
            await interaction.response.send_message("No active raid windows.")
            return

        msg = ""
        for boss in bosses:
            _, name, start_str, end_str, _, _ = boss
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)

            msg += (
                f"🔥 {name.title()}\n"
                f"   Start: {start.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"   End: {end.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            )

        await interaction.response.send_message(msg)

    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

# ================= REMINDER LOOP =================

@tasks.loop(minutes=1)
async def reminder_loop():
    await client.wait_until_ready()
    now = datetime.utcnow()

    for guild in client.guilds:
        channel = discord.utils.get(guild.text_channels, name="raids")
        if not channel:
            continue

        guild_id = str(guild.id)

        c.execute("SELECT * FROM raidboss WHERE guild_id=?", (guild_id,))
        bosses = c.fetchall()

        for boss in bosses:
            _, name, start_str, end_str, warning_sent, open_sent = boss
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)

            warning_time = start - timedelta(minutes=30)

            # 30 minute warning
            if not warning_sent and now >= warning_time and now < start:
                await channel.send(f"⏳ **{name.title()} window opens in 30 minutes!**")
                c.execute(
                    "UPDATE raidboss SET warning_sent=1 WHERE guild_id=? AND name=?",
                    (guild_id, name)
                )
                conn.commit()

            # Window open
            if not open_sent and now >= start:
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
  


client.run(TOKEN)








