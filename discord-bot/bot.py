#!/usr/bin/env python3
"""
Minecraft Discord Bot

Allows remote server management via Discord commands:
- !ip     - Get the server's public IP address
- !status - Check server status and player count
- !up     - Start the server if offline
"""

import discord
from discord.ext import commands
import urllib.request
import subprocess
import os
import asyncio
import sys
import re

# Add parent directory to path to import shared module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import RCONClient, strip_color_codes

# Configuration - loaded from environment variables
TOKEN = os.environ.get('DISCORD_TOKEN')
NOTIFICATION_CHANNEL_ID = os.environ.get('NOTIFICATION_CHANNEL_ID')
MINECRAFT_PORT = int(os.environ.get('MINECRAFT_PORT', 25565))
MINECRAFT_SERVICE = os.environ.get('MINECRAFT_SERVICE', 'minecraft')
RCON_HOST = os.environ.get('RCON_HOST', 'localhost')
RCON_PORT = int(os.environ.get('RCON_PORT', 25575))
RCON_PASSWORD = os.environ.get('RCON_PASSWORD')
DEFAULT_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'mc-manager',
    'server_state.txt'
)
STATE_FILE = os.environ.get('STATE_FILE', DEFAULT_STATE_FILE)
IDLE_TIMEOUT_MINUTES = int(os.environ.get('IDLE_TIMEOUT_MINUTES', 30))
SERVER_VERSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'server',
    '.paper-version'
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


def get_server_version():
    """Return the configured Minecraft version, including while offline."""
    configured = os.environ.get('MINECRAFT_VERSION')
    if configured:
        return configured
    try:
        with open(SERVER_VERSION_FILE, 'r') as version_file:
            return version_file.read().strip() or "unknown"
    except OSError:
        return "unknown"


def is_server_running():
    """Return whether the configured Minecraft systemd service is active."""
    result = subprocess.run(
        ['systemctl', 'is-active', MINECRAFT_SERVICE],
        capture_output=True,
        text=True
    )
    return result.returncode == 0 and result.stdout.strip() == 'active'


def get_public_address():
    """Return the public Java server address."""
    with urllib.request.urlopen('https://api.ipify.org', timeout=10) as response:
        public_ip = response.read().decode('utf-8')
    return f"`{public_ip}:{MINECRAFT_PORT}`"


def parse_player_list(response):
    """Parse player count and names from vanilla or plugin list output."""
    response = strip_color_codes(response).strip()
    count_match = re.search(r"There are\s+(\d+)\b", response, re.IGNORECASE)
    if not count_match:
        return -1, ""

    count = int(count_match.group(1))
    names = []
    lines = response.splitlines()

    # Paper 26.1+: "There are 2 ... players online: Alice, Bob"
    inline_match = re.search(r"players online:\s*(.*)$", lines[0], re.IGNORECASE)
    if inline_match and inline_match.group(1).strip():
        names.append(inline_match.group(1).strip())

    # Some plugins put names on later lines: "group: Alice, Bob"
    for line in lines[1:]:
        value = line.split(':', 1)[1].strip() if ':' in line else line.strip()
        if value:
            names.append(value)

    return count, ", ".join(names)


def get_player_info():
    """Get player count and names from server."""
    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        rcon.connect()
        response = rcon.command("list")
        rcon.close()
        
        return parse_player_list(response)
    except Exception:
        return -1, ""


def read_server_state():
    """Read the current server state from the state file."""
    try:
        with open(STATE_FILE, 'r') as f:
            lines = f.read().strip().split('\n')
            if len(lines) >= 1:
                return lines[0]  # "running", "idle", or "stopped"
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Error reading state file: {e}")
    return None


@bot.event
async def on_ready():
    print(f'{bot.user} is online!')
    # on_ready can fire multiple times after reconnects.
    if not hasattr(bot, '_background_tasks_started'):
        bot._background_tasks_started = True
        bot.loop.create_task(monitor_shutdown())
        bot.loop.create_task(monitor_presence())


async def update_presence():
    """Show the server version and current lifecycle state on the bot user."""
    online = is_server_running()
    state = "Online" if online else "Offline • !up"
    status = discord.Status.online if online else discord.Status.idle
    await bot.change_presence(
        status=status,
        activity=discord.Game(name=f"Minecraft {get_server_version()} • {state}")
    )


async def monitor_presence():
    """Refresh Discord presence as Minecraft starts and stops."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await update_presence()
        except Exception as error:
            print(f"Error updating presence: {error}")
        await asyncio.sleep(30)


async def monitor_shutdown():
    """Background task to monitor for server shutdowns and announce them."""
    if not NOTIFICATION_CHANNEL_ID:
        print("NOTIFICATION_CHANNEL_ID not set, shutdown notifications disabled")
        return
    
    await bot.wait_until_ready()
    channel = bot.get_channel(int(NOTIFICATION_CHANNEL_ID))
    if not channel:
        print(f"Could not find channel {NOTIFICATION_CHANNEL_ID}")
        return
    
    print(f"Monitoring shutdowns, will notify #{getattr(channel, 'name', 'unknown')}")
    last_state = read_server_state()
    notified_shutdown = False
    
    while not bot.is_closed():
        await asyncio.sleep(10)  # Check every 10 seconds
        current_state = read_server_state()
        
        # Detect inactivity shutdown (monitor writes stopped_idle)
        if current_state == 'stopped_idle' and not notified_shutdown:
            if hasattr(channel, 'send'):
                await channel.send(
                    f"**Server shut down** due to {IDLE_TIMEOUT_MINUTES} minutes of inactivity.\n"
                    "Use `!up` to start it again."
                )
            notified_shutdown = True
        
        # Reset notification flag when server starts again
        if current_state in ('running', 'idle'):
            notified_shutdown = False
        
        last_state = current_state


@bot.command(name='ip')
async def get_ip(ctx):
    """Get the Minecraft server IP address"""
    try:
        await ctx.send(
            f"**Minecraft {get_server_version()} Server:** {get_public_address()}"
        )
    except Exception as e:
        await ctx.send(f"Failed to get IP: {e}")


@bot.command(name='status')
async def get_status(ctx):
    """Check if Minecraft server is running and show player count"""
    # Get public IP
    try:
        ip_str = get_public_address()
    except Exception:
        ip_str = "(couldn't fetch IP)"
    
    version = get_server_version()
    if is_server_running():
        player_count, players = get_player_info()
        if player_count > 0:
            await ctx.send(
                f"Server **online** • Minecraft **{version}** • {ip_str}\n"
                f"**{player_count}** player(s): {players}"
            )
        elif player_count == 0:
            await ctx.send(
                f"Server **online** • Minecraft **{version}** • {ip_str}\n"
                "No players connected"
            )
        else:
            await ctx.send(
                f"Server **online** (starting up...) • Minecraft **{version}** • {ip_str}"
            )
    else:
        await ctx.send(
            f"Server **offline** • Minecraft **{version}**\n"
            f"Use `!up` to start it, then connect to {ip_str}"
        )


@bot.command(name='up')
async def start_server(ctx):
    """Start the Minecraft server if it's not running"""
    # Get public IP
    try:
        ip_str = get_public_address()
    except Exception:
        ip_str = "(couldn't fetch IP)"
    
    # Check if already running
    version = get_server_version()
    if is_server_running():
        await ctx.send(
            f"Minecraft **{version}** is already **online**! Connect to {ip_str}"
        )
        return
    
    await ctx.send(
        f"Starting Minecraft **{version}**... (this takes about 30-60 seconds)"
    )
    
    # Start the server via systemctl
    result = subprocess.run(
        ['sudo', 'systemctl', 'start', MINECRAFT_SERVICE],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        await ctx.send(f"Failed to start server: {result.stderr}")
        return
    
    # Wait for server to be ready (check RCON connectivity)
    for i in range(60):
        await asyncio.sleep(2)
        try:
            rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASSWORD)
            rcon.connect()
            rcon.close()
            await update_presence()
            await ctx.send(
                f"Minecraft **{version}** is now **online**! Connect and play!\n{ip_str}"
            )
            return
        except Exception:
            continue
    
    await ctx.send("Server started but may still be loading. Try `!status` in a minute.")


@bot.command(name='help')
async def show_help(ctx):
    """Show Minecraft server bot commands."""
    await ctx.send(
        f"**Minecraft {get_server_version()} Server Commands**\n"
        "`!status` — server state, address, and players\n"
        "`!ip` — connection address\n"
        "`!up` — start the server when offline\n"
        "`!help` — show this message"
    )


if __name__ == '__main__':
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set")
        exit(1)
    if not RCON_PASSWORD:
        print("Error: RCON_PASSWORD environment variable not set")
        exit(1)
    bot.run(TOKEN)
