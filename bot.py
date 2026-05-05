import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
from datetime import datetime, timedelta, timezone
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

c.execute("""
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id TEXT PRIMARY KEY,
    channel_id TEXT
)
""")

conn.commit()

# ================= BOSS TIMERS =================

BOSS_TIMERS = {
    "barakiel": (12, 9),

    "queenant": (24, 4),
    "core": (48, 4),
    "orfen": (33, 4),
    "zaken": (45, 4),

    "baium": (125, 4),
    "antharas": (192, 4),
    "valakas": (264, 4),
}

# ================= READY EVENT =================

@client.event
async def on_ready():
    synced = await tree.sync()
    print(f"Synced {len(synced)} global commands")
    print(f"Bot ready: {client.user}")

    if not reminder_loop.is_running():
        reminder_loop.start()

# ================= /setchannel =================

@tree.command(name="setchannel", description="Set the raid alert channel for this server")
@app_commands.checks.has_permissions(administrator=True)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):

    guild_id = str(interaction.guild.id)

    c.execute(
        "REPLACE INTO guild_config VALUES (?, ?)",
        (guild_id, str(channel.id))
    )
    conn.commit()

    await interaction.response.send_message(
        f"✅ Raid alerts will now be sent in {channel.mention}.",
        ephemeral=True
    )

@setchannel.error
async def setchannel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ Only administrators can use this command.",
            ephemeral=True
        )

# ================= /kill =================

@tree.command(name="kill", description="Register boss kill")
async def kill(interaction: discord.Interaction, boss: str):

    boss_key = boss.lower().replace(" ", "")
    guild_id = str(interaction.guild.id)

    fixed_hours, random_hours = BOSS_TIMERS.get(boss_key, (12, 9))

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=fixed_hours)
    window_end = window_start + timedelta(hours=random_hours)

    c.execute(
        "REPLACE INTO raidboss VALUES (?, ?, ?, ?, 0, 0)",
        (
            guild_id,
            boss_key,
            window_start.isoformat(),
            window_end.isoformat()
        )
    )
    conn.commit()

    unix_start = int(window_start.timestamp())
    unix_end = int(window_end.timestamp())

    await interaction.response.send_message(
        f"🔥 **{boss.title()}** spawn window:\n"
        f"Start: <t:{unix_start}:F>\n"
        f"End: <t:{unix_end}:F>\n"
        f"Opens <t:{unix_start}:R>"
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
            f"No active timer for **{boss.title()}**."
        )
        return

    _, name, start_str, end_str, _, _ = boss_data

    start = datetime.fromisoformat(start_str)
    end = datetime.fromisoformat(end_str)
    now = datetime.now(timezone.utc)

    if now < start:
        unix_start = int(start.timestamp())

        await interaction.response.send_message(
            f"🔥 **{name.title()}**\n\n"
            f"⏳ Opens: <t:{unix_start}:F>\n"
            f"⏱ <t:{unix_start}:R>"
        )

    elif start <= now < end:
        unix_end = int(end.timestamp())

        await interaction.response.send_message(
            f"🔥 **{name.title()}**\n\n"
            f"⚔ **SPAWN WINDOW ACTIVE**\n"
            f"❌ Closes: <t:{unix_end}:F>\n"
            f"⏱ <t:{unix_end}:R>"
        )

    else:
        await interaction.response.send_message(
            f"{name.title()} window already closed."
        )

# ================= /raids =================

@tree.command(name="raids", description="Show all active raid timers")
async def raids(interaction: discord.Interaction):

    guild_id = str(interaction.guild.id)
    now = datetime.now(timezone.utc)

    c.execute("SELECT * FROM raidboss WHERE guild_id=?", (guild_id,))
    bosses = c.fetchall()

    if not bosses:
        await interaction.response.send_message("No active raid timers.")
        return

    msg = ""

    for boss in bosses:
        _, name, start_str, end_str, _, _ = boss

        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)

        if now < start:
            unix_start = int(start.timestamp())

            msg += (
                f"🔥 **{name.title()}**\n"
                f"⏳ Opens: <t:{unix_start}:F>\n"
                f"⏱ <t:{unix_start}:R>\n\n"
            )

        elif start <= now < end:
            unix_end = int(end.timestamp())

            msg += (
                f"🔥 **{name.title()}**\n"
                f"⚔ ACTIVE — Closes: <t:{unix_end}:F>\n"
                f"⏱ <t:{unix_end}:R>\n\n"
            )

    if msg == "":
        await interaction.response.send_message("No active raid timers.")
    else:
        await interaction.response.send_message(msg)

# ================= REMINDER LOOP =================

@tasks.loop(minutes=1)
async def reminder_loop():

    await client.wait_until_ready()
    now = datetime.now(timezone.utc)

    for guild in client.guilds:

        guild_id = str(guild.id)

        c.execute(
            "SELECT channel_id FROM guild_config WHERE guild_id=?",
            (guild_id,)
        )
        config = c.fetchone()

        if not config:
            continue

        channel = guild.get_channel(int(config[0]))

        if not channel:
            continue

        c.execute("SELECT * FROM raidboss WHERE guild_id=?", (guild_id,))
        bosses = c.fetchall()

        for boss in bosses:
            _, name, start_str, end_str, warning_sent, open_sent = boss

            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)

            warning_time = start - timedelta(minutes=30)

            # 30 min warning
            if not warning_sent and now >= warning_time and now < start:
                try:
                    await channel.send(
                        f"⏳ **{name.title()} window opens in 30 minutes!**\n"
                        f"Opens: <t:{int(start.timestamp())}:F>\n"
                        f"⏱ <t:{int(start.timestamp())}:R>"
                    )
                except Exception as e:
                    print("Warning send failed:", e)

                c.execute(
                    "UPDATE raidboss SET warning_sent=1 WHERE guild_id=? AND name=?",
                    (guild_id, name)
                )
                conn.commit()

            # Window open
            if not open_sent and start <= now < end:
                try:
                    await channel.send(
                        f"🔥 **{name.title()} SPAWN WINDOW OPEN!**\n"
                        f"Started: <t:{int(start.timestamp())}:F>\n"
                        f"Closes: <t:{int(end.timestamp())}:F>\n"
                        f"⏱ Closes <t:{int(end.timestamp())}:R>"
                    )
                except Exception as e:
                    print("Open send failed:", e)

                c.execute(
                    "UPDATE raidboss SET open_sent=1 WHERE guild_id=? AND name=?",
                    (guild_id, name)
                )
                conn.commit()

            # Window closed
            if now >= end:
                try:
                    await channel.send(
                        f"❌ **{name.title()} spawn window closed.**"
                    )
                except Exception as e:
                    print("Close send failed:", e)

                c.execute(
                    "DELETE FROM raidboss WHERE guild_id=? AND name=?",
                    (guild_id, name)
                )
                conn.commit()

# ================= RUN =================

client.run(TOKEN)
















