#!/bin/bash
# Validate generated configuration without printing secrets.

set -u

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ERRORS=0
WARNINGS=0

pass() { echo "PASS: $*"; }
warn() { echo "WARN: $*"; WARNINGS=$((WARNINGS + 1)); }
fail() { echo "FAIL: $*"; ERRORS=$((ERRORS + 1)); }

env_value() {
    local key="$1"
    sed -n "s/^${key}=//p" "$INSTALL_DIR/.env" 2>/dev/null | tail -1
}

for file in .env server/server.properties server/server.jar server/start.sh; do
    [ -f "$INSTALL_DIR/$file" ] && pass "$file exists" || fail "$file is missing"
done

if [ -f "$INSTALL_DIR/.env" ]; then
    mode=$(stat -c '%a' "$INSTALL_DIR/.env")
    [ "$mode" = "600" ] && pass ".env permissions are 600" || fail ".env permissions are $mode, expected 600"

    env_rcon=$(env_value RCON_PASSWORD)
    prop_rcon=$(sed -n 's/^rcon.password=//p' "$INSTALL_DIR/server/server.properties" 2>/dev/null | tail -1)
    [ -n "$env_rcon" ] && [ "$env_rcon" = "$prop_rcon" ] &&
        pass "RCON passwords are configured consistently" ||
        fail "RCON passwords are missing or inconsistent"

    env_port=$(env_value MINECRAFT_PORT)
    prop_port=$(sed -n 's/^server-port=//p' "$INSTALL_DIR/server/server.properties" 2>/dev/null | tail -1)
    [ "$env_port" = "$prop_port" ] &&
        pass "Minecraft ports are consistent" ||
        fail "Minecraft ports are inconsistent"

    service=$(env_value MINECRAFT_SERVICE)
    [ -n "$service" ] && pass "Minecraft service is $service" || fail "MINECRAFT_SERVICE is missing"
fi

java_bin=$(env_value JAVA_BIN)
if [ -n "$java_bin" ] && [ -x "$java_bin" ]; then
    java_major=$("$java_bin" -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
    minecraft_version=$(env_value MINECRAFT_VERSION)
    required_java=21
    [[ "$minecraft_version" = 26.* ]] && required_java=25
    [[ "$java_major" =~ ^[0-9]+$ ]] && (( java_major >= required_java )) &&
        pass "Configured Java $java_major is available" ||
        fail "Minecraft $minecraft_version requires Java $required_java+"
else
    fail "Configured JAVA_BIN is missing or not executable"
fi

[ -x "$INSTALL_DIR/venv/bin/python" ] &&
    pass "Python virtual environment exists" ||
    fail "Python virtual environment is missing"

token=$(env_value DISCORD_TOKEN)
if [ -n "$token" ]; then
    "$INSTALL_DIR/venv/bin/python" -c 'import discord' 2>/dev/null &&
        pass "discord.py is installed" ||
        fail "discord.py is missing"
else
    warn "Discord is not configured"
fi

if "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/test_bot.py" >/dev/null 2>&1; then
    pass "Discord bot helper tests pass"
else
    fail "Discord bot helper tests failed"
fi

shopt -s nullglob
units=(
    "$INSTALL_DIR"/minecraft*.service
    "$INSTALL_DIR"/discord-bot/discord-bot*.service
    "$INSTALL_DIR"/mc-manager/minecraft-monitor*.service
)
if command -v systemd-analyze >/dev/null && [ "${#units[@]}" -gt 0 ]; then
    systemd-analyze verify "${units[@]}" >/dev/null 2>&1 &&
        pass "Generated systemd units validate" ||
        fail "Generated systemd units do not validate"
fi

echo
echo "$ERRORS error(s), $WARNINGS warning(s)"
exit "$ERRORS"
