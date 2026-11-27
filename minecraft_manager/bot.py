"""Discord commands: !status, !ip, !up, !mods and !help."""

import asyncio
import time

import discord
from discord.ext import commands

from . import server
from .app import background, log

STARTUP_TIMEOUT_SECONDS = 300


def create_bot(config):
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
    start_lock = asyncio.Lock()

    async def address():
        try:
            return f"`{await asyncio.to_thread(server.public_address, config)}`"
        except Exception:
            return "(address unavailable)"

    async def notify(message):
        if not config.notification_channel_id:
            return
        try:
            channel = bot.get_channel(config.notification_channel_id) or await bot.fetch_channel(
                config.notification_channel_id
            )
            await channel.send(message)
        except discord.DiscordException as error:
            log(f"could not post to the notification channel: {error}")

    last_presence = []

    async def update_presence():
        online = await asyncio.to_thread(server.is_running)
        if last_presence == [online]:
            return
        last_presence[:] = [online]
        await bot.change_presence(
            status=discord.Status.online if online else discord.Status.idle,
            activity=discord.Game(f"{config.server_label} • {'Online' if online else 'Offline • !up'}"),
        )

    async def presence_loop():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                await update_presence()
            except Exception as error:
                log(f"presence update failed: {error}")
            await asyncio.sleep(30)

    background_tasks = []

    async def setup_hook():
        background_tasks.extend(asyncio.create_task(loop) for loop in background(config, notify))
        background_tasks.append(asyncio.create_task(presence_loop()))

    bot.setup_hook = setup_hook

    @bot.event
    async def on_ready():
        log(f"connected to Discord as {bot.user}")

    @bot.command(name="status")
    async def status(ctx):
        if not await asyncio.to_thread(server.is_running):
            await ctx.send(
                f"**{config.server_label}** is **offline**. Use `!up` to start it, then connect to {await address()}"
            )
            return
        players = await asyncio.to_thread(server.get_players, config)
        if players is None:
            detail = "starting up…"
        elif players.count:
            detail = f"**{players.count}** online: {', '.join(players.names) or '(names hidden)'}"
        else:
            detail = "nobody online"
        await ctx.send(f"**{config.server_label}** is **online** at {await address()}, {detail}")

    @bot.command(name="ip")
    async def ip(ctx):
        await ctx.send(f"**{config.server_label}**: {await address()}")

    @bot.command(name="up")
    async def up(ctx):
        if start_lock.locked():
            await ctx.send("Already starting, hang on…")
            return
        async with start_lock:
            if await asyncio.to_thread(server.is_running):
                await ctx.send(f"Already **online** at {await address()}")
                return
            message = await ctx.send(f"Starting **{config.server_label}**… this takes a minute or two.")
            error = await asyncio.to_thread(server.start)
            if error:
                await message.edit(content=f"Could not start the server: {error}")
                return
            started = time.monotonic()
            while time.monotonic() - started < STARTUP_TIMEOUT_SECONDS:
                await asyncio.sleep(5)
                if await asyncio.to_thread(server.rcon_ready, config):
                    seconds = round(time.monotonic() - started)
                    await message.edit(content=f"**{config.server_label}** is **online** at {await address()} (ready in {seconds}s)")
                    await update_presence()
                    return
                if not await asyncio.to_thread(server.is_running):
                    await message.edit(content="The server stopped while starting; check `journalctl -u minecraft`.")
                    return
            await message.edit(content="Still loading after 5 minutes. Try `!status` shortly.")

    @bot.command(name="mods")
    async def mods(ctx):
        summary, pack = server.client_mods()
        first, *rest = server.format_mods_messages(config, summary)
        if config.server_type != "fabric" or not pack:
            await ctx.send(first)
        else:
            filename = f"minecraft-{config.minecraft_version}-mods.mrpack"
            try:
                await ctx.send(first, file=discord.File(pack, filename=filename))
            except discord.Forbidden:
                await ctx.send(first + "\n_(I need the **Attach Files** permission in this channel to share the pack.)_")
        for text in rest:
            await ctx.send(text)

    @bot.command(name="help")
    async def help_command(ctx):
        await ctx.send(
            f"**{config.server_label}**\n"
            "`!status`: online or not, and who is playing\n"
            "`!ip`: the address to connect to\n"
            "`!up`: start the server\n"
            "`!mods`: the mods to install, with a one-click pack\n"
            f"It shuts down by itself after {config.idle_timeout_minutes} minutes with nobody online."
        )

    return bot
