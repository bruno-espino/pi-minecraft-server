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

# Add parent directory to path to import shared module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import RCONClient, strip_color_codes

# Configuration - loaded from environment variables
TOKEN = os.environ.get('DISCORD_TOKEN')
NOTIFICATION_CHANNEL_ID = os.environ.get('NOTIFICATION_CHANNEL_ID')
MINECRAFT_PORT = int(os.environ.get('MINECRAFT_PORT', 25565))
BEDROCK_PORT = int(os.environ.get('BEDROCK_PORT', 19132))
RCON_HOST = os.environ.get('RCON_HOST', 'localhost')
RCON_PORT = int(os.environ.get('RCON_PORT', 25575))
RCON_PASSWORD = os.environ.get('RCON_PASSWORD')
STATE_FILE = os.environ.get('STATE_FILE', '/opt/minecraft/mc-manager/server_state.txt')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


def get_player_info():
    """Get player count and names from server."""
    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        rcon.connect()
        response = rcon.command("list")
        rcon.close()
        
        # Strip color codes first
        response = strip_color_codes(response)
        
        # Parse "There are X out of maximum Y players online.\ngroup: player1, player2"
        lines = response.strip().split('\n')
        first_line = lines[0] if lines else ""
        
        # Extract player names from subsequent lines (format: "group: player1, player2")
        players = ""
        if len(lines) > 1:
            player_lines = []
            for line in lines[1:]:
                if ':' in line:
                    player_lines.append(line.split(':', 1)[1].strip())
            players = ", ".join(player_lines)
        
        # Extract count - look for number after "are"
        if "There are" in first_line:
            words = first_line.split()
            for i, word in enumerate(words):
                if word == "are" and i + 1 < len(words):
                    try:
                        count = int(words[i + 1])
                        return count, players
                    except ValueError:
                        pass
        return 0, ""
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
    # Only start monitor task once (on_ready can fire multiple times on reconnect)
    if not hasattr(bot, '_monitor_task_started'):
        bot._monitor_task_started = True
        bot.loop.create_task(monitor_shutdown())


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
                    "**Server shut down** due to 30 minutes of inactivity.\n"
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
        with urllib.request.urlopen('https://api.ipify.org', timeout=10) as response:
            public_ip = response.read().decode('utf-8')
        
        await ctx.send(f"**Minecraft Server IP:**\nJava: `{public_ip}:{MINECRAFT_PORT}`\nBedrock: `{public_ip}:{BEDROCK_PORT}`")
    except Exception as e:
        await ctx.send(f"Failed to get IP: {e}")


@bot.command(name='status')
async def get_status(ctx):
    """Check if Minecraft server is running and show player count"""
    result = subprocess.run(['systemctl', 'is-active', 'minecraft'], capture_output=True, text=True)
    status = result.stdout.strip()
    
    # Get public IP
    try:
        with urllib.request.urlopen('https://api.ipify.org', timeout=10) as response:
            public_ip = response.read().decode('utf-8')
        ip_str = f"Java: `{public_ip}:{MINECRAFT_PORT}` | Bedrock: `{public_ip}:{BEDROCK_PORT}`"
    except Exception:
        ip_str = "(couldn't fetch IP)"
    
    if status == 'active':
        player_count, players = get_player_info()
        if player_count > 0:
            await ctx.send(f"Server **online** - {ip_str}\n**{player_count}** player(s): {players}")
        elif player_count == 0:
            await ctx.send(f"Server **online** - {ip_str}\nNo players connected")
        else:
            await ctx.send(f"Server **online** (starting up...) - {ip_str}")
    else:
        await ctx.send(f"Server **offline**\nUse `!up` to start it, then connect to {ip_str}")


@bot.command(name='up')
async def start_server(ctx):
    """Start the Minecraft server if it's not running"""
    # Get public IP
    try:
        with urllib.request.urlopen('https://api.ipify.org', timeout=10) as response:
            public_ip = response.read().decode('utf-8')
        ip_str = f"Java: `{public_ip}:{MINECRAFT_PORT}` | Bedrock: `{public_ip}:{BEDROCK_PORT}`"
    except Exception:
        ip_str = "(couldn't fetch IP)"
    
    # Check if already running
    result = subprocess.run(['systemctl', 'is-active', 'minecraft'], capture_output=True, text=True)
    if result.stdout.strip() == 'active':
        await ctx.send(f"Server is already **online**! Connect to {ip_str}")
        return
    
    await ctx.send("Starting Minecraft server... (this takes about 30-60 seconds)")
    
    # Start the server via systemctl
    result = subprocess.run(
        ['sudo', 'systemctl', 'start', 'minecraft'],
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
            await ctx.send(f"Minecraft server is now **online**! Connect and play!\n{ip_str}")
            return
        except Exception:
            continue
    
    await ctx.send("Server started but may still be loading. Try `!status` in a minute.")


if __name__ == '__main__':
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set")
        exit(1)
    if not RCON_PASSWORD:
        print("Error: RCON_PASSWORD environment variable not set")
        exit(1)
    bot.run(TOKEN)
