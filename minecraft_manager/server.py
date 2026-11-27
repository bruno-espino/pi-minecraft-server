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
# Created by `mcserver pregen`; idle shutdown waits while it exists.
PREGEN_HOLD = SERVER_DIR / ".pregen"
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


def main_pid():
    """The server's process ID while the unit runs, else None."""
    result = subprocess.run(
        ["systemctl", "show", "-p", "MainPID", "--value", SERVICE], capture_output=True, text=True, timeout=10
    )
    pid = result.stdout.strip()
    return int(pid) if pid.isdigit() and pid != "0" else None


def parse_tick(response):
    """(average, P95) milliseconds per tick from `tick query` or Paper's `mspt`, or (None, None)."""
    text = " ".join(strip_formatting(response).split())
    average = re.search(r"Average time per tick: ([0-9.]+) ?ms", text)
    if average:
        p95 = re.search(r"P95: ([0-9.]+) ?ms", text)
        return float(average.group(1)), float(p95.group(1)) if p95 else None
    # Paper: "Server tick times (avg/min/max) from last 5s, 10s, 1m: ◴ 1.2/0.4/3.1, 1.3/0.4/5.0, 1.1/0.3/9.8"
    triples = re.findall(r"([0-9.]+)/([0-9.]+)/([0-9.]+)", text)
    if triples:
        return float(triples[-1][0]), None
    return None, None


def server_stats(config):
    """(players, tick average ms, tick P95 ms) over one RCON connection; None where unknown."""
    try:
        with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password, timeout=5) as rcon:
            players = parse_player_list(rcon.command("list"))
            tick = parse_tick(rcon.command("tick query"))
            if tick == (None, None) and config.server_type == "paper":
                tick = parse_tick(rcon.command("mspt"))
    except RCONError:
        return None, None, None
    return (players.count if players else None), *tick


def pregen_running(config, hold=None):
    """Whether pregeneration started by `mcserver pregen` is still going.

    Clears the hold file once Chunky reports no tasks, including after a
    restart interrupted it. Assumes busy while the console does not answer.
    """
    hold = hold or PREGEN_HOLD
    if not hold.exists():
        return False
    try:
        with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password) as rcon:
            reply = strip_formatting(rcon.command("chunky progress"))
    except RCONError:
        return True
    if "No tasks running" in reply or "Unknown" in reply:
        hold.unlink(missing_ok=True)
        return False
    return True


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


def format_mods_messages(config, summary, limit=1900):
    """Discord messages explaining what players install, each under Discord's 2000 characters.

    Long mod lists continue in further messages instead of losing their links.
    """
    if config.server_type != "fabric":
        return [f"**{config.server_label}** needs no mods: a normal Minecraft {config.minecraft_version} client works."]
    if not summary:
        return ["The mod list isn't available yet; ask the admin to rerun ./install.sh."]

    messages = [
        f"**Mods for {config.server_label}**\n"
        "Easiest: import the attached pack in the **Modrinth App** or **Prism Launcher** "
        "(Add instance → Import); it installs Fabric and the exact versions.\n"
        f"Manual install: Fabric Loader {summary['loader']} for Minecraft {summary['minecraft']}, then:"
    ]
    for group, label in (("required", "Required"), ("optional", "Optional")):
        names = [f"[{m['title']}](<{m['url']}>)" for m in summary[group]] or ["none"]
        line = f"**{label}:** {names[0]}"
        for name in names[1:]:
            if len(line) + 2 + len(name) > limit:
                messages, line = _append(messages, line, limit), f"**{label} (continued):** {name}"
            else:
                line += f", {name}"
        messages = _append(messages, line, limit)
    return [message[:limit] for message in messages]


def _append(messages, line, limit):
    """Add a line to the last message, or start a new message when it would not fit."""
    if len(messages[-1]) + 1 + len(line) <= limit:
        return messages[:-1] + [messages[-1] + "\n" + line]
    return messages + [line]


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
