#!/bin/bash
# Install or update the Minecraft server, its Discord/idle manager and backups.
# Safe to rerun: settings are kept in .env and only changed by options you pass.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$DIR/server"

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

  --server paper|fabric     Server software (default: paper, or the current one)
  --version VERSION         Minecraft version (default: 26.3, or the current one)
  --memory MB               Maximum Java heap in MiB (default: 4096)
  --port PORT               Minecraft port (default: 25565)
  --rcon-port PORT          Local RCON port (default: 25575)
  --online-mode true|false  Require official Minecraft accounts (default: true)
  --new-world               Archive the current world so the next start makes a new one
  --no-services             Skip systemd units, sudo rules and the backup timer
  --accept-eula             Accept https://aka.ms/MinecraftEULA without asking
  --yes                     Do not ask questions (leaves Discord unset if not given)
  -h, --help                Show this help

Mods (Fabric) and plugins (Paper) come from Modrinth project names listed in
mods.txt and plugins.txt. DISCORD_TOKEN can be passed as an environment variable.
EOF
}

fail() { echo "Error: $*" >&2; exit 1; }
env_value() { [ -f "$DIR/.env" ] && sed -n "s/^$1=//p" "$DIR/.env" | tail -1 || true; }
ask() { [ "$YES" = true ] && return 0; read -r -p "$1 [y/N] " reply; [[ "$reply" =~ ^[Yy]$ ]]; }

SERVER_TYPE="" VERSION="" MEMORY_MB="" PORT="" RCON_PORT="" ONLINE_MODE=""
NEW_WORLD=false SERVICES=true ACCEPT_EULA=false YES=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --server) SERVER_TYPE="${2:?}"; shift 2 ;;
        --version) VERSION="${2:?}"; shift 2 ;;
        --memory) MEMORY_MB="${2:?}"; shift 2 ;;
        --port) PORT="${2:?}"; shift 2 ;;
        --rcon-port) RCON_PORT="${2:?}"; shift 2 ;;
        --online-mode) ONLINE_MODE="${2:?}"; shift 2 ;;
        --new-world) NEW_WORLD=true; shift ;;
        --no-services) SERVICES=false; shift ;;
        --accept-eula) ACCEPT_EULA=true; shift ;;
        --yes) YES=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "unknown option: $1" ;;
    esac
done

[ "$EUID" -ne 0 ] || fail "run as your normal user; the script uses sudo where needed"
command -v python3 >/dev/null || fail "python3 is required"
python3 -c 'import venv, ensurepip' 2>/dev/null || fail "install the python3-venv package"

# Options override .env, which overrides defaults.
PREVIOUS_TYPE="$(env_value SERVER_TYPE)"
SERVER_TYPE="${SERVER_TYPE:-${PREVIOUS_TYPE:-paper}}"
VERSION="${VERSION:-$(env_value MINECRAFT_VERSION)}"; VERSION="${VERSION:-26.3}"
MEMORY_MB="${MEMORY_MB:-$(env_value MEMORY_MB)}"; MEMORY_MB="${MEMORY_MB:-4096}"
PORT="${PORT:-$(env_value MINECRAFT_PORT)}"; PORT="${PORT:-25565}"
RCON_PORT="${RCON_PORT:-$(env_value RCON_PORT)}"; RCON_PORT="${RCON_PORT:-25575}"
ONLINE_MODE="${ONLINE_MODE:-$(env_value ONLINE_MODE)}"; ONLINE_MODE="${ONLINE_MODE:-true}"
RCON_PASSWORD="$(env_value RCON_PASSWORD)"
RCON_PASSWORD="${RCON_PASSWORD:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')}"
DISCORD_TOKEN="${DISCORD_TOKEN:-$(env_value DISCORD_TOKEN)}"
NOTIFICATION_CHANNEL_ID="${NOTIFICATION_CHANNEL_ID:-$(env_value NOTIFICATION_CHANNEL_ID)}"
SERVER_ADDRESS="${SERVER_ADDRESS:-$(env_value SERVER_ADDRESS)}"
IDLE_TIMEOUT_MINUTES="$(env_value IDLE_TIMEOUT_MINUTES)"
CHECK_INTERVAL_SECONDS="$(env_value CHECK_INTERVAL_SECONDS)"
AUTO_SHUTDOWN="$(env_value AUTO_SHUTDOWN)"
BACKUP_KEEP="$(env_value BACKUP_KEEP)"

[[ "$SERVER_TYPE" =~ ^(paper|fabric)$ ]] || fail "--server must be paper or fabric"
[[ "$ONLINE_MODE" =~ ^(true|false)$ ]] || fail "--online-mode must be true or false"
if ! [[ "$MEMORY_MB" =~ ^[0-9]+$ ]] || (( MEMORY_MB < 1024 )); then
    fail "--memory must be at least 1024"
fi
for p in "$PORT" "$RCON_PORT"; do
    if ! [[ "$p" =~ ^[0-9]+$ ]] || (( p < 1024 || p > 65535 )); then
        fail "invalid port: $p"
    fi
done
(( PORT != RCON_PORT )) || fail "the Minecraft and RCON ports must differ"

LEVEL=""
[ ! -f "$SERVER_DIR/server.properties" ] || LEVEL="$(sed -n 's/^level-name=//p' "$SERVER_DIR/server.properties" | tail -1)"
LEVEL="${LEVEL:-world}"
[[ "$LEVEL" =~ ^[A-Za-z0-9._-]+$ ]] || fail "unsupported level-name: $LEVEL"
WORLD_EXISTS=false
[ ! -f "$SERVER_DIR/$LEVEL/level.dat" ] || WORLD_EXISTS=true
if [ "$WORLD_EXISTS" = true ] && [ -n "$PREVIOUS_TYPE" ] && [ "$PREVIOUS_TYPE" != "$SERVER_TYPE" ] &&
   [ "$NEW_WORLD" = false ]; then
    fail "the existing world was made by $PREVIOUS_TYPE; pass --new-world to archive it and start fresh"
fi

echo "Checking Minecraft $VERSION..."
JAVA_REQUIRED="$(cd "$DIR" && python3 -m minecraft_manager.provision java-major "$VERSION")"
java_ok() {
    local major
    [ -x "$1" ] || return 1
    major="$("$1" -version 2>&1 | sed -n '1s/.*version "\([0-9]*\).*/\1/p')"
    [[ "$major" =~ ^[0-9]+$ ]] && (( major >= JAVA_REQUIRED ))
}
JAVA_BIN="$(env_value JAVA_BIN)"
if [ -z "$JAVA_BIN" ] || ! java_ok "$JAVA_BIN"; then
    JAVA_BIN=""
    for candidate in "$(command -v java || true)" /usr/lib/jvm/*/bin/java; do
        if java_ok "$candidate"; then
            JAVA_BIN="$(readlink -f "$candidate")"
            break
        fi
    done
fi
[ -n "$JAVA_BIN" ] || fail "Minecraft $VERSION needs Java $JAVA_REQUIRED or newer; install it (e.g. Temurin or Corretto) and rerun"

if ! grep -qs '^eula=true' "$SERVER_DIR/eula.txt" && [ "$ACCEPT_EULA" = false ]; then
    [ "$YES" = false ] || fail "pass --accept-eula after reading https://aka.ms/MinecraftEULA"
    ask "Accept the Minecraft EULA (https://aka.ms/MinecraftEULA)?" || fail "the EULA must be accepted"
fi
if [ -z "$DISCORD_TOKEN" ] && [ "$YES" = false ]; then
    read -r -s -p "Discord bot token (leave empty to run without Discord): " DISCORD_TOKEN
    echo
fi

ADDON_LIST="$DIR/plugins.txt" ADDON_DIR="$SERVER_DIR/plugins"
[ "$SERVER_TYPE" = paper ] || { ADDON_LIST="$DIR/mods.txt"; ADDON_DIR="$SERVER_DIR/mods"; }
cat <<EOF

  Directory      $DIR
  Server         $SERVER_TYPE $VERSION, Java $JAVA_REQUIRED+ at $JAVA_BIN
  Add-ons        $(basename "$ADDON_LIST") -> ${ADDON_DIR#"$DIR"/}
  Memory         up to $MEMORY_MB MiB
  Ports          $PORT (game), $RCON_PORT (RCON, local only)
  Online mode    $ONLINE_MODE
  Discord        $([ -n "$DISCORD_TOKEN" ] && echo enabled || echo disabled)
  New world      $NEW_WORLD$([ "$WORLD_EXISTS" = true ] && [ "$NEW_WORLD" = true ] && echo " (current world is archived to backups/)")
  systemd        $SERVICES

EOF
ask "Continue?" || fail "cancelled"

umask 077
cat > "$DIR/.env" <<EOF
# Written by install.sh; values are kept when it reruns.
SERVER_TYPE=$SERVER_TYPE
MINECRAFT_VERSION=$VERSION
MINECRAFT_PORT=$PORT
RCON_PORT=$RCON_PORT
RCON_PASSWORD=$RCON_PASSWORD
ONLINE_MODE=$ONLINE_MODE
MEMORY_MB=$MEMORY_MB
JAVA_BIN=$JAVA_BIN
DISCORD_TOKEN=$DISCORD_TOKEN
NOTIFICATION_CHANNEL_ID=$NOTIFICATION_CHANNEL_ID
SERVER_ADDRESS=$SERVER_ADDRESS
IDLE_TIMEOUT_MINUTES=${IDLE_TIMEOUT_MINUTES:-30}
CHECK_INTERVAL_SECONDS=${CHECK_INTERVAL_SECONDS:-60}
AUTO_SHUTDOWN=${AUTO_SHUTDOWN:-true}
BACKUP_KEEP=${BACKUP_KEEP:-7}
EOF
umask 022
mkdir -p "$SERVER_DIR" "$DIR/backups"

if [ "$NEW_WORLD" = true ] && [ "$WORLD_EXISTS" = true ]; then
    ! systemctl is-active --quiet minecraft || fail "stop the server before archiving its world"
    archive="$DIR/backups/old-worlds/$(date +%Y%m%d-%H%M%S)-${PREVIOUS_TYPE:-unknown}"
    mkdir -p "$archive"
    for world in "$LEVEL" "${LEVEL}_nether" "${LEVEL}_the_end"; do
        [ ! -e "$SERVER_DIR/$world" ] || mv "$SERVER_DIR/$world" "$archive/"
    done
    echo "Archived the previous world to ${archive#"$DIR"/}"
fi

set_property() {
    if grep -q "^$1=" "$SERVER_DIR/server.properties"; then
        sed -i "s|^$1=.*|$1=$2|" "$SERVER_DIR/server.properties"
    else
        printf '%s=%s\n' "$1" "$2" >> "$SERVER_DIR/server.properties"
    fi
}
if [ ! -f "$SERVER_DIR/server.properties" ]; then
    printf '%s\n' "motd=Raspberry Pi Minecraft Server" "max-players=10" \
        "view-distance=8" "simulation-distance=6" > "$SERVER_DIR/server.properties"
fi
set_property server-port "$PORT"
set_property enable-rcon true
set_property rcon.port "$RCON_PORT"
set_property rcon.password "$RCON_PASSWORD"
set_property broadcast-rcon-to-ops false
set_property online-mode "$ONLINE_MODE"
set_property enforce-secure-profile "$ONLINE_MODE"
chmod 600 "$SERVER_DIR/server.properties"
echo "eula=true" > "$SERVER_DIR/eula.txt"

(cd "$DIR" && python3 -m minecraft_manager.provision server-jar "$SERVER_TYPE" "$VERSION" "$SERVER_DIR")
if [ -f "$ADDON_LIST" ]; then
    (cd "$DIR" && python3 -m minecraft_manager.provision addons "$SERVER_TYPE" "$VERSION" "$ADDON_LIST" "$ADDON_DIR")
fi

JAR="paper.jar"
[ "$SERVER_TYPE" = paper ] || JAR="fabric-server-launch.jar"
sed -e "s|__JAVA_BIN__|$JAVA_BIN|" -e "s|__MEMORY_MB__|$MEMORY_MB|" -e "s|__JAR__|$JAR|" \
    "$DIR/templates/start.sh" > "$SERVER_DIR/start.sh"
chmod 755 "$SERVER_DIR/start.sh"

echo "Installing the manager's Python environment..."
[ -x "$DIR/.venv/bin/python" ] || python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --quiet --disable-pip-version-check -e "$DIR"

if [ "$SERVICES" = true ]; then
    USER_NAME="$(id -un)"
    for legacy in discord-bot minecraft-monitor; do  # replaced by minecraft-manager
        if systemctl cat "$legacy.service" >/dev/null 2>&1; then
            echo "Removing the old $legacy service"
            sudo systemctl disable --now "$legacy.service"
            sudo rm -f "/etc/systemd/system/$legacy.service"
        fi
    done
    for unit in minecraft.service minecraft-manager.service minecraft-backup.service minecraft-backup.timer; do
        sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" "$DIR/templates/$unit" |
            sudo tee "/etc/systemd/system/$unit" >/dev/null
    done
    rules="$(mktemp)"
    printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl start minecraft, /usr/bin/systemctl stop minecraft\n' \
        "$USER_NAME" > "$rules"
    sudo visudo -cqf "$rules"
    sudo install -m 440 "$rules" /etc/sudoers.d/minecraft
    rm -f "$rules"
    sudo systemctl daemon-reload
    sudo systemctl enable --quiet minecraft.service minecraft-manager.service
    sudo systemctl enable --now --quiet minecraft-backup.timer
    sudo systemctl restart minecraft-manager.service
    if systemctl is-active --quiet minecraft; then
        echo "Minecraft is running the previous setup; restart it when nobody is playing:"
        echo "  sudo systemctl restart minecraft"
    fi
fi

echo
if [ "$SERVICES" = true ]; then
    echo "Done. Start the server with !up in Discord or: sudo systemctl start minecraft"
else
    echo "Done. Start the server with: server/start.sh"
fi
