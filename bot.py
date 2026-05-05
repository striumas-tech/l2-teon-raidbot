import discord
from discord import app_commands
from discord.ext import tasks
import asyncpg
from datetime import datetime, timedelta, timezone
import os

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ================= DATABASE =================

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        ssl="require"
    )

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS raidboss (
                guild_id TEXT,
                name TEXT,
                window_start TIMESTAMPTZ NOT NULL,
                window_end TIMESTAMPTZ NOT NULL,
                warning_sent BOOLEAN DEFAULT FALSE,
                open_sent BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (guild_id, name)
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL
            );
        """)

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
    global db_pool

    if db_pool is None:
        await init_db()
        print("Database connected")

    print(f"Bot ready: {client.user}")

    for guild in client.guilds:
        try:
            synced = await tree.sync(guild=discord.Object(id=guild.id))
            print(f"Synced {len(synced)} commands to {guild.name}")
        except Exception as e:
            print(f"Sync failed for {guild.name}:", e)

    if not reminder_loop.is_running():
        reminder_loop.start()

# ================= /setchannel =================

@tree.command(name="setchannel", description="Set the raid alert channel for this server")
@app_commands.checks.has_permissions(administrator=True)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):

    guild_id = str(interaction.guild.id)

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO guild_config (guild_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id
        """, guild_id, str(channel.id))

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

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO raidboss (
                guild_id, name, window_start, window_end, warning_sent, open_sent
            )
            VALUES ($1, $2, $3, $4, FALSE, FALSE)
            ON CONFLICT (guild_id, name)
            DO UPDATE SET
                window_start = EXCLUDED.window_start,
                window_end = EXCLUDED.window_end,
                warning_sent = FALSE,
                open_sent = FALSE
        """, guild_id, boss_key, window_start, window_end)

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

    async with db_pool.acquire() as conn:
        boss_data = await conn.fetchrow("""
            SELECT *
            FROM raidboss
            WHERE guild_id = $1 AND name = $2
        """, guild_id, boss_key)

    if not boss_data:
        await interaction.response.send_message(
            f"No active timer for **{boss.title()}**."
        )
        return

    name = boss_data["name"]
    start = boss_data["window_start"]
    end = boss_data["window_end"]
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

    async with db_pool.acquire() as conn:
        bosses = await conn.fetch("""
            SELECT *
            FROM raidboss
            WHERE guild_id = $1
        """, guild_id)

    if not bosses:
        await interaction.response.send_message("No active raid timers.")
        return

    msg = ""

    for boss in bosses:
        name = boss["name"]
        start = boss["window_start"]
        end = boss["window_end"]

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

    if db_pool is None:
        return

    now = datetime.now(timezone.utc)

    for guild in client.guilds:
        guild_id = str(guild.id)

        async with db_pool.acquire() as conn:
            config = await conn.fetchrow("""
                SELECT channel_id
                FROM guild_config
                WHERE guild_id = $1
            """, guild_id)

        if not config:
            continue

        channel = guild.get_channel(int(config["channel_id"]))

        if not channel:
            continue

        async with db_pool.acquire() as conn:
            bosses = await conn.fetch("""
                SELECT *
                FROM raidboss
                WHERE guild_id = $1
            """, guild_id)

        for boss in bosses:
            name = boss["name"]
            start = boss["window_start"]
            end = boss["window_end"]
            warning_sent = boss["warning_sent"]
            open_sent = boss["open_sent"]

            warning_time = start - timedelta(minutes=30)

            if not warning_sent and now >= warning_time and now < start:
                try:
                    await channel.send(
                        f"⏳ **{name.title()} window opens in 30 minutes!**\n"
                        f"Opens: <t:{int(start.timestamp())}:F>\n"
                        f"⏱ <t:{int(start.timestamp())}:R>"
                    )
                except Exception as e:
                    print("Warning send failed:", e)

                async with db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE raidboss
                        SET warning_sent = TRUE
                        WHERE guild_id = $1 AND name = $2
                    """, guild_id, name)

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

                async with db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE raidboss
                        SET open_sent = TRUE
                        WHERE guild_id = $1 AND name = $2
                    """, guild_id, name)

            if now >= end:
                try:
                    await channel.send(
                        f"❌ **{name.title()} spawn window closed.**"
                    )
                except Exception as e:
                    print("Close send failed:", e)

                async with db_pool.acquire() as conn:
                    await conn.execute("""
                        DELETE FROM raidboss
                        WHERE guild_id = $1 AND name = $2
                    """, guild_id, name)

# ================= RUN =================

client.run(TOKEN)











