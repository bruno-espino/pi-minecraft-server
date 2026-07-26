#!/bin/bash
#
# Install a Paper Minecraft server and its optional Discord/idle manager.

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_USER="${SUDO_USER:-$USER}"
INSTANCE="main"
MINECRAFT_VERSION="26.1.2"
MINECRAFT_PORT=25565
RCON_PORT=25575
MEMORY_MB=3584
JAVA_BIN="${JAVA_BIN:-java}"
WITH_DISCORD=true
INSTALL_SERVICES=false
START_SERVICES=false
NON_INTERACTIVE=false
DRY_RUN=false
ACCEPT_EULA=false

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --instance NAME           Instance name (default: main)
  --minecraft-version VER  Paper/Minecraft version (default: 26.1.2)
  --minecraft-port PORT     Java server port (default: 25565)
  --rcon-port PORT          Local RCON port (default: 25575)
  --memory MB               JVM memory in MiB (default: 3584)
  --java-bin PATH           Java executable for Minecraft
  --no-discord              Configure only Minecraft and the idle monitor
  --install-services        Install and enable systemd units
  --start                   Start installed services after installation
  --accept-eula             Accept the Minecraft EULA non-interactively
  --non-interactive         Never prompt; fail when required input is missing
  --dry-run                 Validate and print the plan without changing files
  -h, --help                Show this help

DISCORD_TOKEN and NOTIFICATION_CHANNEL_ID can be supplied as environment
variables. Secrets are stored in .env with mode 600.
EOF
}

fail() {
    echo "Error: $*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --instance) INSTANCE="${2:?missing instance}"; shift 2 ;;
        --minecraft-version) MINECRAFT_VERSION="${2:?missing version}"; shift 2 ;;
        --minecraft-port) MINECRAFT_PORT="${2:?missing port}"; shift 2 ;;
        --rcon-port) RCON_PORT="${2:?missing port}"; shift 2 ;;
        --memory) MEMORY_MB="${2:?missing memory}"; shift 2 ;;
        --java-bin) JAVA_BIN="${2:?missing Java path}"; shift 2 ;;
        --no-discord) WITH_DISCORD=false; shift ;;
        --install-services) INSTALL_SERVICES=true; shift ;;
        --start) START_SERVICES=true; INSTALL_SERVICES=true; shift ;;
        --accept-eula) ACCEPT_EULA=true; shift ;;
        --non-interactive) NON_INTERACTIVE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

[[ "$INSTANCE" =~ ^[a-z0-9][a-z0-9-]*$ ]] || fail "instance must use lowercase letters, numbers, and hyphens"
[[ "$MINECRAFT_PORT" =~ ^[0-9]+$ ]] && (( MINECRAFT_PORT >= 1024 && MINECRAFT_PORT <= 65535 )) || fail "invalid Minecraft port"
[[ "$RCON_PORT" =~ ^[0-9]+$ ]] && (( RCON_PORT >= 1024 && RCON_PORT <= 65535 )) || fail "invalid RCON port"
[[ "$MEMORY_MB" =~ ^[0-9]+$ ]] && (( MEMORY_MB >= 768 )) || fail "memory must be at least 768 MiB"
(( MINECRAFT_PORT != RCON_PORT )) || fail "Minecraft and RCON ports must differ"

if [ "$INSTANCE" = "main" ]; then
    MC_SERVICE="minecraft"
    BOT_SERVICE="discord-bot"
    MONITOR_SERVICE="minecraft-monitor"
    UNIT_SUFFIX=""
else
    MC_SERVICE="minecraft-$INSTANCE"
    BOT_SERVICE="discord-bot-$INSTANCE"
    MONITOR_SERVICE="minecraft-monitor-$INSTANCE"
    UNIT_SUFFIX="-$INSTANCE"
fi

echo "Installation plan"
echo "  Directory:         $INSTALL_DIR"
echo "  Instance:          $INSTANCE"
echo "  Minecraft/Paper:   $MINECRAFT_VERSION"
echo "  Minecraft port:    $MINECRAFT_PORT"
echo "  RCON port:         $RCON_PORT"
echo "  JVM memory:        ${MEMORY_MB} MiB"
echo "  Java executable:   $JAVA_BIN"
echo "  Discord bot:       $WITH_DISCORD"
echo "  Install services:  $INSTALL_SERVICES"
echo "  Service names:     $MC_SERVICE, $MONITOR_SERVICE"
[ "$WITH_DISCORD" = true ] && echo "                     $BOT_SERVICE"

if [ "$DRY_RUN" = true ]; then
    echo "Dry run complete; no files changed."
    exit 0
fi

command -v python3 >/dev/null || fail "Python 3 is required"
command -v "$JAVA_BIN" >/dev/null || fail "Java executable not found: $JAVA_BIN"
JAVA_BIN=$(command -v "$JAVA_BIN")
JAVA_MAJOR=$("$JAVA_BIN" -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
REQUIRED_JAVA=21
[[ "$MINECRAFT_VERSION" = 26.* ]] && REQUIRED_JAVA=25
[[ "$JAVA_MAJOR" =~ ^[0-9]+$ ]] && (( JAVA_MAJOR >= REQUIRED_JAVA )) ||
    fail "Minecraft $MINECRAFT_VERSION requires Java $REQUIRED_JAVA+"

if [ "$ACCEPT_EULA" != true ]; then
    [ "$NON_INTERACTIVE" = false ] || fail "pass --accept-eula after reviewing https://aka.ms/MinecraftEULA"
    read -r -p "Accept the Minecraft EULA (https://aka.ms/MinecraftEULA)? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || fail "EULA not accepted"
fi

get_env_value() {
    local key="$1"
    [ -f "$INSTALL_DIR/.env" ] || return 0
    sed -n "s/^${key}=//p" "$INSTALL_DIR/.env" | tail -1
}

RCON_PASSWORD="${RCON_PASSWORD:-$(get_env_value RCON_PASSWORD)}"
if [ -z "$RCON_PASSWORD" ]; then
    RCON_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
fi

DISCORD_TOKEN="${DISCORD_TOKEN:-$(get_env_value DISCORD_TOKEN)}"
NOTIFICATION_CHANNEL_ID="${NOTIFICATION_CHANNEL_ID:-$(get_env_value NOTIFICATION_CHANNEL_ID)}"
IDLE_TIMEOUT_MINUTES="${IDLE_TIMEOUT_MINUTES:-$(get_env_value IDLE_TIMEOUT_MINUTES)}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-$(get_env_value CHECK_INTERVAL_SECONDS)}"
IDLE_TIMEOUT_MINUTES="${IDLE_TIMEOUT_MINUTES:-30}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-60}"

if [ "$WITH_DISCORD" = true ] && [ -z "$DISCORD_TOKEN" ]; then
    if [ "$NON_INTERACTIVE" = true ]; then
        fail "DISCORD_TOKEN is required unless --no-discord is used"
    fi
    read -r -s -p "Discord bot token: " DISCORD_TOKEN
    echo
    [ -n "$DISCORD_TOKEN" ] || fail "Discord token cannot be empty; use --no-discord to skip it"
fi

umask 077
cat > "$INSTALL_DIR/.env" <<EOF
DISCORD_TOKEN=$DISCORD_TOKEN
NOTIFICATION_CHANNEL_ID=$NOTIFICATION_CHANNEL_ID
RCON_PASSWORD=$RCON_PASSWORD
RCON_HOST=localhost
RCON_PORT=$RCON_PORT
MINECRAFT_VERSION=$MINECRAFT_VERSION
MINECRAFT_PORT=$MINECRAFT_PORT
JAVA_BIN=$JAVA_BIN
MINECRAFT_SERVICE=$MC_SERVICE
IDLE_TIMEOUT_MINUTES=$IDLE_TIMEOUT_MINUTES
CHECK_INTERVAL_SECONDS=$CHECK_INTERVAL_SECONDS
STATE_FILE=$INSTALL_DIR/mc-manager/server_state.txt
EOF
chmod 600 "$INSTALL_DIR/.env"
umask 022

mkdir -p "$INSTALL_DIR/server"

set_property() {
    local file="$1"
    local key="$2"
    local value="$3"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

if [ ! -f "$INSTALL_DIR/server/server.properties" ]; then
    sed \
        -e "s|__MINECRAFT_PORT__|$MINECRAFT_PORT|g" \
        -e "s|__RCON_PORT__|$RCON_PORT|g" \
        -e "s|CHANGE_THIS_PASSWORD|$RCON_PASSWORD|g" \
        "$INSTALL_DIR/server/server.properties.example" \
        > "$INSTALL_DIR/server/server.properties"
else
    set_property "$INSTALL_DIR/server/server.properties" server-port "$MINECRAFT_PORT"
    set_property "$INSTALL_DIR/server/server.properties" query.port "$MINECRAFT_PORT"
    set_property "$INSTALL_DIR/server/server.properties" rcon.port "$RCON_PORT"
    set_property "$INSTALL_DIR/server/server.properties" rcon.password "$RCON_PASSWORD"
fi
echo "eula=true" > "$INSTALL_DIR/server/eula.txt"

sed \
    -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    -e "s|__MEMORY_MB__|$MEMORY_MB|g" \
    -e "s|__JAVA_BIN__|$JAVA_BIN|g" \
    "$INSTALL_DIR/server/start.sh.template" \
    > "$INSTALL_DIR/server/start.sh"
chmod 755 "$INSTALL_DIR/server/start.sh"

render_unit() {
    local template="$1"
    local output="$2"
    sed \
        -e "s|__USER__|$INSTALL_USER|g" \
        -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        "$template" > "$output"
}

MC_UNIT="$INSTALL_DIR/minecraft${UNIT_SUFFIX}.service"
BOT_UNIT="$INSTALL_DIR/discord-bot/discord-bot${UNIT_SUFFIX}.service"
MONITOR_UNIT="$INSTALL_DIR/mc-manager/minecraft-monitor${UNIT_SUFFIX}.service"
render_unit "$INSTALL_DIR/minecraft.service.template" "$MC_UNIT"
render_unit "$INSTALL_DIR/discord-bot/discord-bot.service.template" "$BOT_UNIT"
render_unit "$INSTALL_DIR/mc-manager/minecraft-monitor.service.template" "$MONITOR_UNIT"

INSTALLED_VERSION=""
[ ! -f "$INSTALL_DIR/server/.paper-version" ] ||
    INSTALLED_VERSION=$(cat "$INSTALL_DIR/server/.paper-version")
if [ ! -f "$INSTALL_DIR/server/server.jar" ] || [ "$INSTALLED_VERSION" != "$MINECRAFT_VERSION" ]; then
    echo "Downloading the latest stable Paper build for $MINECRAFT_VERSION..."
    python3 - "$MINECRAFT_VERSION" "$INSTALL_DIR/server/server.jar" <<'PY'
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request

version, target_name = sys.argv[1:]
user_agent = "pi-minecraft-server/1.0 (https://github.com/bruno-espino/pi-minecraft-server)"
api_url = f"https://fill.papermc.io/v3/projects/paper/versions/{version}/builds"
request = urllib.request.Request(api_url, headers={"User-Agent": user_agent})
with urllib.request.urlopen(request, timeout=30) as response:
    builds = json.load(response)
stable = next((build for build in builds if build.get("channel") == "STABLE"), None)
if not stable:
    raise SystemExit(f"No stable Paper build found for {version}")
download = stable["downloads"]["server:default"]
target = Path(target_name)
partial = target.with_suffix(".jar.part")
request = urllib.request.Request(download["url"], headers={"User-Agent": user_agent})
with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
    shutil.copyfileobj(response, output)
expected = download.get("checksums", {}).get("sha256")
if expected:
    actual = hashlib.sha256(partial.read_bytes()).hexdigest()
    if actual != expected:
        partial.unlink(missing_ok=True)
        raise SystemExit("Paper download checksum mismatch")
partial.replace(target)
print(f"Downloaded {download['name']}")
PY
    printf '%s\n' "$MINECRAFT_VERSION" > "$INSTALL_DIR/server/.paper-version"
fi

if [ ! -x "$INSTALL_DIR/venv/bin/python" ]; then
    python3 -m venv "$INSTALL_DIR/venv" ||
        fail "could not create venv; install the python3-venv OS package"
fi
if [ "$WITH_DISCORD" = true ]; then
    "$INSTALL_DIR/venv/bin/python" -m pip install -q -r "$INSTALL_DIR/discord-bot/requirements.txt"
fi

if [ "$INSTALL_SERVICES" = true ]; then
    if [ "$NON_INTERACTIVE" = false ]; then
        read -r -p "Install and enable the listed systemd services? [y/N] " answer
        [[ "$answer" =~ ^[Yy]$ ]] || fail "service installation cancelled"
    fi

    sudo install -m 644 "$MC_UNIT" "/etc/systemd/system/$MC_SERVICE.service"
    sudo install -m 644 "$MONITOR_UNIT" "/etc/systemd/system/$MONITOR_SERVICE.service"
    if [ "$WITH_DISCORD" = true ]; then
        sudo install -m 644 "$BOT_UNIT" "/etc/systemd/system/$BOT_SERVICE.service"
    fi

    sudoers_tmp=$(mktemp)
    cat > "$sudoers_tmp" <<EOF
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start $MC_SERVICE
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop $MC_SERVICE
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart $MC_SERVICE
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl status $MC_SERVICE
EOF
    sudo visudo -cf "$sudoers_tmp" >/dev/null
    sudo install -m 440 "$sudoers_tmp" "/etc/sudoers.d/minecraft-$INSTANCE"
    find "$sudoers_tmp" -delete

    sudo systemctl daemon-reload
    sudo systemctl enable "$MC_SERVICE" "$MONITOR_SERVICE"
    [ "$WITH_DISCORD" = false ] || sudo systemctl enable "$BOT_SERVICE"

    if [ "$START_SERVICES" = true ]; then
        sudo systemctl start "$MC_SERVICE" "$MONITOR_SERVICE"
        [ "$WITH_DISCORD" = false ] || sudo systemctl start "$BOT_SERVICE"
    fi
fi

echo "Installation complete."
echo "Run ./test.sh to validate the generated configuration."
