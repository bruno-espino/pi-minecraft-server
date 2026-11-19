#!/bin/bash
# Install or update the Minecraft server, its Discord/idle manager and backups.
# Safe to rerun: settings are kept in .env and only changed by options you pass.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$DIR/server"

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

Run without options for a guided setup; options skip their question.

  --server paper|fabric     Server software (default: paper, or the current one)
  --version VERSION         Minecraft version (default: 26.3, or the current one)
  --memory MB|auto          Maximum Java heap in MiB (default: auto, half the RAM)
  --port PORT               Minecraft port (default: 25565)
  --rcon-port PORT          Local RCON port (default: 25575)
  --online-mode true|false  Require official Minecraft accounts (default: true)
  --whitelist on|off        Only let listed players join (new installs: off)
  --world-type TYPE         World type for a new world: normal, large-biomes,
                            amplified, flat, or a mod's type such as wover:normal
  --new-world               Archive the current world so the next start makes a new one
  --update-mods             Move mods or plugins to their newest builds (otherwise the
                            versions in mods.lock / plugins.lock are kept)
  --no-services             Skip systemd units, sudo rules and the backup timer
  --accept-eula             Accept https://aka.ms/MinecraftEULA without asking
  --guided                  Ask about every setting, also when updating
  --yes                     Do not ask questions (leaves Discord unset if not given)
  -h, --help                Show this help

Java is downloaded (Eclipse Temurin, into java/) unless a new enough one is
installed. Mods (Fabric) and plugins (Paper) come from Modrinth project names
listed in mods.txt and plugins.txt, created from the .example.txt files on the
first install. DISCORD_TOKEN can be passed as an environment variable.
EOF
}

fail() { echo "Error: $*" >&2; exit 1; }
env_value() { if [ -f "$DIR/.env" ]; then sed -n "s/^$1=//p" "$DIR/.env" | tail -1; fi; }
ask() { [ "$YES" = true ] && return 0; read -r -p "$1 [y/N] " reply; [[ "$reply" =~ ^[Yy]$ ]]; }
# Guided questions. yes_no QUESTION Y|N; prompt_value VAR QUESTION DEFAULT REGEX ERROR
yes_no() {
    local reply hint="[y/N]"
    [ "$2" = N ] || hint="[Y/n]"
    while true; do
        read -r -p "$1 $hint " reply || fail "no answer"
        case "${reply:-$2}" in [Yy]*) return 0 ;; [Nn]*) return 1 ;; esac
    done
}
prompt_value() {
    local reply shown=""
    [ -z "$3" ] || shown=" [$3]"
    while true; do
        read -r -p "$2$shown: " reply || fail "no answer"
        reply="${reply:-$3}"
        [[ "$reply" =~ $4 ]] && break
        echo "  $5"
    done
    printf -v "$1" '%s' "$reply"
}
# Half the installed RAM, counted in whole GiB (8 GiB boards report a bit less),
# between 1 and 8 GiB. The rest covers the OS and Java's memory outside the heap.
RAM_MIB=$(( $(sed -n 's/^MemTotal: *\([0-9]*\) kB/\1/p' /proc/meminfo) / 1024 ))
RAM_GIB=$(( (RAM_MIB + 1023) / 1024 ))
auto_memory() {
    local mb=$(( RAM_GIB * 512 ))
    (( mb >= 1024 )) || mb=1024
    (( mb <= 8192 )) || mb=8192
    echo "$mb"
}

SERVER_TYPE="" VERSION="" MEMORY_MB="" PORT="" RCON_PORT="" ONLINE_MODE="" WHITELIST="" WORLD_TYPE=""
NEW_WORLD=false SERVICES=true ACCEPT_EULA=false YES=false GUIDED=false UPDATE_MODS=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --server) SERVER_TYPE="${2:?}"; shift 2 ;;
        --version) VERSION="${2:?}"; shift 2 ;;
        --memory) MEMORY_MB="${2:?}"; shift 2 ;;
        --port) PORT="${2:?}"; shift 2 ;;
        --rcon-port) RCON_PORT="${2:?}"; shift 2 ;;
        --online-mode) ONLINE_MODE="${2:?}"; shift 2 ;;
        --whitelist) WHITELIST="${2:?}"; shift 2 ;;
        --world-type) WORLD_TYPE="${2:?}"; shift 2 ;;
        --new-world) NEW_WORLD=true; shift ;;
        --update-mods) UPDATE_MODS=(--update); shift ;;
        --no-services) SERVICES=false; shift ;;
        --accept-eula) ACCEPT_EULA=true; shift ;;
        --guided) GUIDED=true; shift ;;
        --yes) YES=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "unknown option: $1" ;;
    esac
done

[ "$EUID" -ne 0 ] || fail "run as your normal user; the script uses sudo where needed"
if [ "$GUIDED" = true ]; then
    [ "$YES" = false ] || fail "--guided and --yes cannot be combined"
    [ -t 0 ] || fail "--guided needs a terminal"
fi
# A first install from a terminal is guided; reruns only ask with --guided.
[ "$YES" = true ] || [ ! -t 0 ] || [ -f "$DIR/.env" ] || GUIDED=true
if [ "$SERVICES" = true ] && [ ! -d /run/systemd/system ]; then
    fail "systemd is not running here; pass --no-services and start the server with server/start.sh"
fi

packages=()
command -v python3 >/dev/null || packages+=(python3)
if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then packages+=(python3-venv); fi
if (( ${#packages[@]} )); then
    command -v apt-get >/dev/null || fail "install ${packages[*]} and rerun"
    ask "Install ${packages[*]} with apt (needs sudo)?" || fail "${packages[*]} are required"
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${packages[@]}"
fi

# Options override .env, which overrides defaults.
GIVEN_SERVER_TYPE="$SERVER_TYPE" GIVEN_VERSION="$VERSION" GIVEN_MEMORY="$MEMORY_MB"
GIVEN_ONLINE_MODE="$ONLINE_MODE" GIVEN_WORLD_TYPE="$WORLD_TYPE"
PREVIOUS_TYPE="$(env_value SERVER_TYPE)"
SERVER_TYPE="${SERVER_TYPE:-${PREVIOUS_TYPE:-paper}}"
VERSION="${VERSION:-$(env_value MINECRAFT_VERSION)}"; VERSION="${VERSION:-26.3}"
MEMORY_MB="${MEMORY_MB:-$(env_value MEMORY_MB)}"; MEMORY_MB="${MEMORY_MB:-auto}"
[ "$MEMORY_MB" != auto ] || MEMORY_MB="$(auto_memory)"
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
CURRENT_WHITELIST=""
[ ! -f "$SERVER_DIR/server.properties" ] ||
    CURRENT_WHITELIST="$(sed -n 's/^white-list=//p' "$SERVER_DIR/server.properties" | tail -1)"

if [ "$GUIDED" = true ]; then
    echo "Minecraft server setup. Press Enter to keep the value in [brackets]."
    echo
    if [ -z "$GIVEN_SERVER_TYPE" ]; then
        echo "Server software:"
        echo "  1) Paper   plugins; players join with the unmodified game"
        echo "  2) Fabric  mods; players install a modpack that the installer builds"
        choice=1
        [ "$SERVER_TYPE" = paper ] || choice=2
        prompt_value choice "Choice" "$choice" '^[12]$' "enter 1 or 2"
        SERVER_TYPE=paper
        [ "$choice" = 1 ] || SERVER_TYPE=fabric
    fi
    [ -n "$GIVEN_VERSION" ] ||
        prompt_value VERSION "Minecraft version" "$VERSION" '^[0-9][0-9A-Za-z.+-]*$' "for example 26.3"
    [ -n "$GIVEN_MEMORY" ] ||
        prompt_value MEMORY_MB "Memory for the server in MiB (this machine has $RAM_GIB GiB)" \
            "$MEMORY_MB" '^[0-9]+$' "enter a number of MiB, for example 4096"
    if [ -z "$GIVEN_ONLINE_MODE" ]; then
        default=Y
        [ "$ONLINE_MODE" = true ] || default=N
        if yes_no "Do all players have official Minecraft: Java Edition accounts?" "$default"; then
            ONLINE_MODE=true
        else
            ONLINE_MODE=false
            echo "  Online mode is off: anyone can join with any name, so keep the operator list short."
        fi
    fi
    if [ -z "$WHITELIST" ]; then
        default=N
        [ "$CURRENT_WHITELIST" != true ] || default=Y
        WHITELIST=off
        if yes_no "Only let players you add join (whitelist)?" "$default"; then WHITELIST=on; fi
    fi
fi

[[ "$SERVER_TYPE" =~ ^(paper|fabric)$ ]] || fail "--server must be paper or fabric"
[[ "$ONLINE_MODE" =~ ^(true|false)$ ]] || fail "--online-mode must be true or false"
[[ "$WHITELIST" =~ ^(|on|off)$ ]] || fail "--whitelist must be on or off"
if ! [[ "$MEMORY_MB" =~ ^[0-9]+$ ]] || (( MEMORY_MB < 1024 )); then
    fail "--memory must be auto or at least 1024"
fi
for p in "$PORT" "$RCON_PORT"; do
    if ! [[ "$p" =~ ^[0-9]+$ ]] || (( p < 1024 || p > 65535 )); then
        fail "invalid port: $p"
    fi
done
(( PORT != RCON_PORT )) || fail "the Minecraft and RCON ports must differ"

ADDON_LIST="$DIR/plugins.txt" ADDON_DIR="$SERVER_DIR/plugins"
[ "$SERVER_TYPE" = paper ] || { ADDON_LIST="$DIR/mods.txt"; ADDON_DIR="$SERVER_DIR/mods"; }
ADDON_EXAMPLE="${ADDON_LIST%.txt}.example.txt"
if [ ! -f "$ADDON_LIST" ] && [ -f "$ADDON_EXAMPLE" ]; then
    cp "$ADDON_EXAMPLE" "$ADDON_LIST"
    [ "$GUIDED" = true ] ||
        echo "Created $(basename "$ADDON_LIST") from $(basename "$ADDON_EXAMPLE"); edit it to choose your own"
fi
if [ "$GUIDED" = true ]; then
    kind=plugins
    [ "$SERVER_TYPE" = paper ] || kind=mods
    echo "$(basename "$ADDON_LIST") lists the $kind to install, one Modrinth name per line."
    editor="${VISUAL:-${EDITOR:-nano}}"
    if command -v "${editor%% *}" >/dev/null && yes_no "Edit it now with ${editor%% *}?" N; then
        # shellcheck disable=SC2086  # EDITOR may include arguments
        $editor "$ADDON_LIST"
    fi
fi

LEVEL=""
[ ! -f "$SERVER_DIR/server.properties" ] || LEVEL="$(sed -n 's/^level-name=//p' "$SERVER_DIR/server.properties" | tail -1)"
LEVEL="${LEVEL:-world}"
[[ "$LEVEL" =~ ^[A-Za-z0-9._][A-Za-z0-9._-]*$ ]] || fail "unsupported level-name: $LEVEL"
WORLD_EXISTS=false
[ ! -f "$SERVER_DIR/$LEVEL/level.dat" ] || WORLD_EXISTS=true
CREATES_WORLD=true
if [ "$WORLD_EXISTS" = true ] && [ "$NEW_WORLD" = false ]; then CREATES_WORLD=false; fi
# server.properties stores the world type with an escaped colon (minecraft\:normal).
CURRENT_WORLD_TYPE=""
[ ! -f "$SERVER_DIR/server.properties" ] ||
    CURRENT_WORLD_TYPE="$(sed -n 's/^level-type=//p' "$SERVER_DIR/server.properties" | tail -1 | sed 's/\\:/:/g')"
CURRENT_WORLD_TYPE="${CURRENT_WORLD_TYPE:-minecraft:normal}"
# Some world-generation mods only take effect in a world created with their own
# type; with the vanilla type they load but keep vanilla terrain.
NEEDS_WOVER=false
if [ -f "$ADDON_LIST" ] && grep -qE '^[[:space:]]*(betterend|betternether)([[:space:]#]|$)' "$ADDON_LIST"; then
    NEEDS_WOVER=true
fi
if [ "$GUIDED" = true ] && [ -z "$GIVEN_WORLD_TYPE" ] && [ "$CREATES_WORLD" = true ]; then
    default=normal
    if [ "$NEEDS_WOVER" = true ]; then
        default=wover:normal
        echo "BetterEnd/BetterNether need the wover:normal world type (its overworld is the vanilla one)."
    fi
    prompt_value WORLD_TYPE "World type: normal, large-biomes, amplified, flat, or a mod's type" \
        "$default" '^[a-z0-9_.:/-]+$' "for example normal or wover:normal"
fi
case "$WORLD_TYPE" in
    normal|large-biomes|amplified|flat) WORLD_TYPE="minecraft:${WORLD_TYPE//-/_}" ;;
esac
[[ "$WORLD_TYPE" =~ ^(|[a-z0-9_.-]+:[a-z0-9_./-]+)$ ]] ||
    fail "--world-type must be normal, large-biomes, amplified, flat or namespace:name"
if [ -n "$WORLD_TYPE" ] && [ "$WORLD_TYPE" != "$CURRENT_WORLD_TYPE" ] && [ "$CREATES_WORLD" = false ]; then
    fail "the world type only applies when a world is created; add --new-world to start one as $WORLD_TYPE"
fi
WORLD_TYPE="${WORLD_TYPE:-$CURRENT_WORLD_TYPE}"
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
# A Java the installer downloaded is kept up to date; one installed another way
# is used as long as it is new enough.
JAVA_BIN="$(env_value JAVA_BIN)"
MANAGED_JAVA=false
if [[ "$JAVA_BIN" == "$DIR/java/"* ]]; then
    MANAGED_JAVA=true
elif [ -z "$JAVA_BIN" ] || ! java_ok "$JAVA_BIN"; then
    JAVA_BIN=""
    for candidate in "$(command -v java || true)" /usr/lib/jvm/*/bin/java; do
        if java_ok "$candidate"; then
            JAVA_BIN="$(readlink -f "$candidate")"
            break
        fi
    done
    [ -n "$JAVA_BIN" ] || MANAGED_JAVA=true
fi
JAVA_LABEL="$JAVA_BIN"
WHITELIST_LABEL="${WHITELIST:-off}"
[ -n "$WHITELIST" ] || [ "$CURRENT_WHITELIST" != true ] || WHITELIST_LABEL=on
if [ "$MANAGED_JAVA" = true ]; then
    JAVA_LABEL="Eclipse Temurin in java/ (downloaded and kept up to date)"
fi

if ! grep -qs '^eula=true' "$SERVER_DIR/eula.txt" && [ "$ACCEPT_EULA" = false ]; then
    [ "$YES" = false ] || fail "pass --accept-eula after reading https://aka.ms/MinecraftEULA"
    ask "Accept the Minecraft EULA (https://aka.ms/MinecraftEULA)?" || fail "the EULA must be accepted"
fi
if [ "$YES" = false ] && { [ -z "$DISCORD_TOKEN" ] || [ "$GUIDED" = true ]; }; then
    [ "$GUIDED" = false ] ||
        echo "A Discord bot lets players start the server with !up (setup steps are in the README)."
    shown=""
    [ -z "$DISCORD_TOKEN" ] || shown=" [keep the current one]"
    read -r -s -p "Discord bot token (leave empty to run without Discord)$shown: " reply
    echo
    DISCORD_TOKEN="${reply:-$DISCORD_TOKEN}"
fi
if [ "$GUIDED" = true ] && [ -n "$DISCORD_TOKEN" ]; then
    prompt_value NOTIFICATION_CHANNEL_ID "Discord channel ID for shutdown messages (optional)" \
        "$NOTIFICATION_CHANNEL_ID" '^[0-9]*$' "a channel ID is a number (Copy Channel ID in Discord)"
    prompt_value SERVER_ADDRESS "Address players connect to, shown by !ip (empty: the public IP)" \
        "$SERVER_ADDRESS" '^[A-Za-z0-9.:-]*$' "a hostname or IP address, optionally with :port"
fi

cat <<EOF

  Directory      $DIR
  Server         $SERVER_TYPE $VERSION
  Java           $JAVA_REQUIRED+, $JAVA_LABEL
  Add-ons        $(basename "$ADDON_LIST") -> ${ADDON_DIR#"$DIR"/}
  Memory         up to $MEMORY_MB MiB of $RAM_GIB GiB
  Ports          $PORT (game), $RCON_PORT (RCON, local only)
  Online mode    $ONLINE_MODE
  Whitelist      $WHITELIST_LABEL
  Discord        $([ -n "$DISCORD_TOKEN" ] && echo enabled || echo disabled)
  New world      $NEW_WORLD$([ "$WORLD_EXISTS" = true ] && [ "$NEW_WORLD" = true ] && echo " (current world is archived to backups/)")
  World type     $WORLD_TYPE$([ "$CREATES_WORLD" = false ] && echo " (existing world)")
  systemd        $SERVICES

EOF
if (( MEMORY_MB > RAM_MIB - 1024 )); then
    echo "Warning: $MEMORY_MB MiB leaves less than 1 GiB for the system; consider --memory auto."
    echo
fi
if [ "$SERVER_TYPE" = fabric ] && (( RAM_GIB < 4 )); then
    echo "Warning: mods usually need 4 GiB of RAM or more; Paper runs on less."
    echo
fi
if [[ "$WORLD_TYPE" != wover:* ]] && [ "$CREATES_WORLD" = true ] && [ "$NEEDS_WOVER" = true ]; then
    echo "Note: BetterEnd/BetterNether only generate their terrain in a world created with"
    echo "      --world-type wover:normal. Rerun with it now; it cannot be changed later."
    echo
fi
ask "Continue?" || fail "cancelled"

if [ "$MANAGED_JAVA" = true ]; then
    if java_path="$(cd "$DIR" && python3 -m minecraft_manager.provision java-install "$JAVA_REQUIRED" "$DIR/java")"; then
        JAVA_BIN="$java_path"
    elif java_ok "$JAVA_BIN"; then
        echo "Warning: could not check for a newer Java; keeping $JAVA_BIN"
    else
        fail "could not download Java $JAVA_REQUIRED; install it yourself (e.g. Temurin) and rerun"
    fi
    java_ok "$JAVA_BIN" || fail "the downloaded Java does not run on this system"
fi

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
        local value="${2//\\/\\\\}"
        value="${value//&/\\&}"
        value="${value//|/\\|}"
        sed -i "s|^$1=.*|$1=$value|" "$SERVER_DIR/server.properties"
    else
        printf '%s=%s\n' "$1" "$2" >> "$SERVER_DIR/server.properties"
    fi
}
if [ ! -f "$SERVER_DIR/server.properties" ]; then
    printf '%s\n' "motd=Raspberry Pi Minecraft Server" "max-players=10" \
        "view-distance=8" "simulation-distance=6" > "$SERVER_DIR/server.properties"
fi
# Minecraft 26.x turns the whitelist on for new servers, which locks everyone
# out of an empty list. Set it explicitly once; afterwards only --whitelist
# changes it, so `whitelist on` from the console survives reruns.
grep -q '^white-list=' "$SERVER_DIR/server.properties" || WHITELIST="${WHITELIST:-off}"
case "$WHITELIST" in
    on) set_property white-list true ;;
    off) set_property white-list false ;;
esac
set_property server-port "$PORT"
set_property enable-rcon true
set_property rcon.port "$RCON_PORT"
set_property rcon.password "$RCON_PASSWORD"
set_property broadcast-rcon-to-ops false
set_property online-mode "$ONLINE_MODE"
set_property level-type "${WORLD_TYPE//:/\\:}"
set_property enforce-secure-profile "$ONLINE_MODE"
chmod 600 "$SERVER_DIR/server.properties"
echo "eula=true" > "$SERVER_DIR/eula.txt"

(cd "$DIR" && python3 -m minecraft_manager.provision server-jar "$SERVER_TYPE" "$VERSION" "$SERVER_DIR")
if [ -f "$ADDON_LIST" ]; then
    (cd "$DIR" && python3 -m minecraft_manager.provision addons "$SERVER_TYPE" "$VERSION" "$ADDON_LIST" "$ADDON_DIR" \
        "${UPDATE_MODS[@]}")
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
    sudo ln -sfn "$DIR/mcserver" /usr/local/bin/mcserver
    if systemctl is-active --quiet minecraft; then
        echo "Minecraft is running the previous setup; restart it when nobody is playing:"
        echo "  mcserver restart"
    fi
fi

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
if [ "$SERVICES" = true ]; then
    echo "Done. Start the server with !up in Discord or: mcserver start"
    echo "Run mcserver for status, the console, backups and more."
else
    echo "Done. Start the server with: server/start.sh"
fi
echo "Players on your network connect to ${LAN_IP:-the address of this machine}:$PORT; for players"
echo "elsewhere, forward port $PORT on your router (see the README)."
