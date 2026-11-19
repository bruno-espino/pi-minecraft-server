"""Blocking helpers for the Minecraft systemd unit and its RCON console."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request

from .config import SERVICE
from .rcon import RCONClient, RCONError, strip_formatting

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
_address_cache = (0.0, "")


@dataclass(frozen=True)
class Players:
    count: int
    names: list[str]


def is_running():
    """Whether systemd reports the Minecraft unit as active."""
    result = subprocess.run(
        ["systemctl", "is-active", SERVICE], capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip() == "active"


def start():
    """Start the unit; returns an error message or None."""
    result = subprocess.run(
        ["sudo", "-n", "systemctl", "start", SERVICE], capture_output=True, text=True, timeout=60
    )
    return None if result.returncode == 0 else result.stderr.strip() or "systemctl start failed"


def parse_player_list(response):
    """Parse the `list` command; returns None for unrecognised output."""
    lines = strip_formatting(response).strip().splitlines()
    if not lines:
        return None
    match = re.search(r"There are\s+(\d+)\b", lines[0], re.IGNORECASE)
    if not match:
        return None
    names = []
    inline = re.search(r"players online:\s*(.*)$", lines[0], re.IGNORECASE)
    if inline:
        names += [name.strip() for name in inline.group(1).split(",") if name.strip()]
    for line in lines[1:]:  # some plugins list names on later "group: a, b" lines
        value = line.split(":", 1)[-1]
        names += [name.strip() for name in value.split(",") if name.strip()]
    return Players(int(match.group(1)), names)


def get_players(config):
    """Online players via RCON, or None while RCON is unavailable."""
    try:
        with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password) as rcon:
            return parse_player_list(rcon.command("list"))
    except RCONError:
        return None


def rcon_ready(config):
    try:
        with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password, timeout=5):
            return True
    except RCONError:
        return False


def stop_for_inactivity(config):
    """Warn players, stop through RCON, and fall back to systemd. Returns success."""
    try:
        with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password) as rcon:
            rcon.command("say Server shutting down due to inactivity. Use !up on Discord to restart.")
            time.sleep(3)
            rcon.command("stop")
    except RCONError as error:
        print(f"RCON stop failed ({error}); asking systemd to stop the server")
    for _ in range(90):
        if not is_running():
            return True
        time.sleep(1)
    result = subprocess.run(
        ["sudo", "-n", "systemctl", "stop", SERVICE], capture_output=True, text=True, timeout=120
    )
    return result.returncode == 0


def client_mods():
    """The players' mod summary and pack path written by install.sh, or (None, None)."""
    try:
        summary = json.loads((SERVER_DIR / "client-mods.json").read_text())
    except (OSError, ValueError):
        return None, None
    pack = SERVER_DIR / "client-pack.mrpack"
    return summary, pack if pack.is_file() else None


def format_mods_message(config, summary, limit=1900):
    """Discord text explaining what players install; stays under Discord's 2000 characters."""
    if config.server_type != "fabric":
        return f"**{config.server_label}** needs no mods: a normal Minecraft {config.minecraft_version} client works."
    if not summary:
        return "The mod list isn't available yet; ask the admin to rerun ./install.sh."

    def names(group):
        return ", ".join(f"[{m['title']}](<{m['url']}>)" for m in summary[group]) or "none"

    text = (
        f"**Mods for {config.server_label}**\n"
        "Easiest: import the attached pack in the **Modrinth App** or **Prism Launcher** "
        "(Add instance → Import); it installs Fabric and the exact versions.\n"
        f"Manual install: Fabric Loader {summary['loader']} for Minecraft {summary['minecraft']}, then:\n"
        f"**Required:** {names('required')}\n"
        f"**Optional:** {names('optional')}"
    )
    if len(text) > limit:  # drop links before dropping mods
        def plain(group):
            return ", ".join(m["title"] for m in summary[group]) or "none"
        text = text.split("**Required:**")[0] + f"**Required:** {plain('required')}\n**Optional:** {plain('optional')}"
    return text[:limit]


def public_address(config):
    """Address players should connect to: SERVER_ADDRESS, or the public IP."""
    global _address_cache
    if config.server_address:
        host = config.server_address
    else:
        fetched_at, host = _address_cache
        if time.monotonic() - fetched_at > 600 or not host:
            request = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "pi-minecraft-server"})
            with urllib.request.urlopen(request, timeout=10) as response:
                host = response.read().decode().strip()
            _address_cache = (time.monotonic(), host)
    return host if config.minecraft_port == 25565 else f"{host}:{config.minecraft_port}"
