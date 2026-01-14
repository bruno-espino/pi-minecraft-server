#!/usr/bin/env python3
"""
Minecraft Server Auto-Shutdown Monitor

Monitors player count via RCON and shuts down the server
after a configurable period of inactivity.
"""

import time
import subprocess
import sys
import os
from datetime import datetime

# Add parent directory to path to import shared module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import RCONClient, strip_color_codes

# Configuration - loaded from environment variables
RCON_HOST = os.environ.get('RCON_HOST', 'localhost')
RCON_PORT = int(os.environ.get('RCON_PORT', 25575))
RCON_PASSWORD = os.environ.get('RCON_PASSWORD')
IDLE_TIMEOUT_MINUTES = int(os.environ.get('IDLE_TIMEOUT_MINUTES', 30))
CHECK_INTERVAL_SECONDS = int(os.environ.get('CHECK_INTERVAL_SECONDS', 60))

# State file to communicate with Discord bot
STATE_FILE = os.environ.get('STATE_FILE', '/opt/minecraft/mc-manager/server_state.txt')


def get_player_count():
    """Get the current player count from the server."""
    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        rcon.connect()
        response = rcon.command("list")
        rcon.disconnect()
        
        # Strip color codes first
        response = strip_color_codes(response)
        
        # Parse response like "There are 1 out of maximum 10 players online."
        if "There are" in response:
            words = response.split()
            for i, word in enumerate(words):
                if word == "are" and i + 1 < len(words):
                    try:
                        return int(words[i + 1])
                    except ValueError:
                        pass
        return 0
    except Exception as e:
        print(f"[{datetime.now()}] Error getting player count: {e}")
        return -1  # Error state


def is_server_running():
    """Check if the Minecraft server process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "server.jar"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def stop_server():
    """Gracefully stop the Minecraft server."""
    print(f"[{datetime.now()}] Stopping server due to inactivity...")
    
    try:
        # Send stop command via RCON
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        rcon.connect()
        rcon.command("say Server shutting down due to inactivity. Use !up on Discord to restart.")
        time.sleep(3)
        rcon.command("stop")
        rcon.disconnect()
        
        # Wait for server to stop
        for _ in range(30):
            if not is_server_running():
                print(f"[{datetime.now()}] Server stopped successfully")
                update_state("stopped_idle")
                return True
            time.sleep(1)
        
        print(f"[{datetime.now()}] Server did not stop gracefully, forcing...")
        subprocess.run(["pkill", "-f", "server.jar"])
        update_state("stopped_idle")
        return True
        
    except Exception as e:
        print(f"[{datetime.now()}] Error stopping server: {e}")
        return False


def update_state(state, players=0):
    """Update the state file for the Discord bot."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            f.write(f"{state}\n{players}\n{datetime.now().isoformat()}")
    except Exception as e:
        print(f"[{datetime.now()}] Error updating state: {e}")


def main():
    print(f"[{datetime.now()}] Minecraft Auto-Shutdown Monitor started")
    print(f"[{datetime.now()}] Idle timeout: {IDLE_TIMEOUT_MINUTES} minutes")
    
    last_activity = datetime.now()
    server_was_running = False
    
    while True:
        try:
            if not is_server_running():
                print(f"[{datetime.now()}] Server not running, monitor sleeping...")
                # Don't overwrite stopped_idle state - only set stopped if not already stopped
                current_state = None
                try:
                    with open(STATE_FILE, 'r') as f:
                        current_state = f.read().strip().split('\n')[0]
                except Exception:
                    pass
                if current_state not in ('stopped', 'stopped_idle'):
                    update_state("stopped")
                server_was_running = False
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue
            
            # Reset idle timer when server starts up
            if not server_was_running:
                print(f"[{datetime.now()}] Server started, resetting idle timer")
                last_activity = datetime.now()
                server_was_running = True
            
            player_count = get_player_count()
            
            if player_count < 0:
                # Error getting player count, server might be starting up
                print(f"[{datetime.now()}] Could not get player count, retrying...")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue
            
            if player_count > 0:
                last_activity = datetime.now()
                print(f"[{datetime.now()}] Players online: {player_count}")
                update_state("running", player_count)
            else:
                idle_time = datetime.now() - last_activity
                idle_minutes = idle_time.total_seconds() / 60
                remaining = IDLE_TIMEOUT_MINUTES - idle_minutes
                
                print(f"[{datetime.now()}] No players online. Idle for {idle_minutes:.1f} min. "
                      f"Shutdown in {remaining:.1f} min")
                update_state("idle", 0)
                
                if idle_minutes >= IDLE_TIMEOUT_MINUTES:
                    stop_server()
                    last_activity = datetime.now()  # Reset for next startup
            
            time.sleep(CHECK_INTERVAL_SECONDS)
            
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] Monitor stopped by user")
            break
        except Exception as e:
            print(f"[{datetime.now()}] Error in monitor loop: {e}")
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    if not RCON_PASSWORD:
        print("Error: RCON_PASSWORD environment variable not set")
        sys.exit(1)
    main()
