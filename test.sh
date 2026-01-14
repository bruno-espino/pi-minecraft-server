#!/bin/bash
# Tests that everything is configured correctly

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           Minecraft Server - Configuration Test               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

ERRORS=0
WARNINGS=0

# Helper functions

pass() {
    echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
    echo -e "  ${RED}✗${NC} $1"
    ((ERRORS++))
}

warn() {
    echo -e "  ${YELLOW}!${NC} $1"
    ((WARNINGS++))
}

info() {
    echo -e "  ${BLUE}→${NC} $1"
}

# Check required files

echo -e "${BLUE}[1/6] Checking required files...${NC}"

if [ -f "$INSTALL_DIR/.env" ]; then
    pass ".env file exists"
else
    fail ".env file not found - run ./install.sh first"
fi

if [ -f "$INSTALL_DIR/server/server.properties" ]; then
    pass "server.properties exists"
else
    fail "server.properties not found - run ./install.sh first"
fi

if [ -f "$INSTALL_DIR/server/server.jar" ]; then
    pass "server.jar exists"
else
    warn "server.jar not found - server won't start without it"
    info "Run ./install.sh and choose to download Paper MC"
fi

if [ -f "$INSTALL_DIR/server/start.sh" ]; then
    pass "start.sh exists"
    if [ -x "$INSTALL_DIR/server/start.sh" ]; then
        pass "start.sh is executable"
    else
        fail "start.sh is not executable - run: chmod +x server/start.sh"
    fi
else
    fail "start.sh not found - run ./install.sh first"
fi

echo ""

# Check Java

echo -e "${BLUE}[2/6] Checking Java installation...${NC}"

if command -v java &> /dev/null; then
    JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2)
    JAVA_MAJOR=$(echo "$JAVA_VERSION" | cut -d'.' -f1)
    
    if [ "$JAVA_MAJOR" -ge 21 ] 2>/dev/null; then
        pass "Java $JAVA_VERSION installed (21+ required)"
    elif [ "$JAVA_MAJOR" -ge 17 ] 2>/dev/null; then
        warn "Java $JAVA_VERSION installed (21+ recommended, 17+ minimum)"
    else
        fail "Java $JAVA_VERSION is too old (need 17+, recommend 21+)"
    fi
else
    fail "Java not found - install Java 21: sudo apt install temurin-21-jre"
fi

echo ""

# Check Discord config

echo -e "${BLUE}[3/6] Checking Discord configuration...${NC}"

if [ -f "$INSTALL_DIR/.env" ]; then
    DISCORD_TOKEN=$(grep -E "^DISCORD_TOKEN=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d'=' -f2)
    
    if [ -z "$DISCORD_TOKEN" ]; then
        fail "DISCORD_TOKEN is not set in .env"
        info "Get a token from: https://discord.com/developers/applications"
    elif [ "$DISCORD_TOKEN" = "your_discord_bot_token_here" ]; then
        fail "DISCORD_TOKEN is still the placeholder value"
        info "Get a token from: https://discord.com/developers/applications"
    elif [[ ${#DISCORD_TOKEN} -lt 50 ]]; then
        warn "DISCORD_TOKEN looks too short (expected 70+ characters)"
    else
        pass "DISCORD_TOKEN is set (${#DISCORD_TOKEN} characters)"
    fi
    
    NOTIFICATION_CHANNEL=$(grep -E "^NOTIFICATION_CHANNEL_ID=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d'=' -f2)
    if [ -z "$NOTIFICATION_CHANNEL" ]; then
        warn "NOTIFICATION_CHANNEL_ID not set (shutdown notifications disabled)"
        info "To enable: right-click a Discord channel > Copy ID > add to .env"
    else
        pass "NOTIFICATION_CHANNEL_ID is set"
    fi
else
    fail "Cannot check Discord config - .env file missing"
fi

echo ""

# Check RCON config

echo -e "${BLUE}[4/6] Checking RCON configuration...${NC}"

if [ -f "$INSTALL_DIR/.env" ] && [ -f "$INSTALL_DIR/server/server.properties" ]; then
    ENV_RCON_PASS=$(grep -E "^RCON_PASSWORD=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d'=' -f2)
    PROP_RCON_PASS=$(grep -E "^rcon.password=" "$INSTALL_DIR/server/server.properties" 2>/dev/null | cut -d'=' -f2)
    
    if [ -z "$ENV_RCON_PASS" ]; then
        fail "RCON_PASSWORD not set in .env"
    elif [ "$ENV_RCON_PASS" = "change_this_password" ]; then
        fail "RCON_PASSWORD is still the default - run ./install.sh to generate one"
    else
        pass "RCON_PASSWORD is set in .env"
    fi
    
    if [ -z "$PROP_RCON_PASS" ]; then
        fail "rcon.password not set in server.properties"
    elif [ "$PROP_RCON_PASS" = "CHANGE_THIS_PASSWORD" ]; then
        fail "rcon.password is still the default in server.properties"
    else
        pass "rcon.password is set in server.properties"
    fi
    
    if [ -n "$ENV_RCON_PASS" ] && [ -n "$PROP_RCON_PASS" ]; then
        if [ "$ENV_RCON_PASS" = "$PROP_RCON_PASS" ]; then
            pass "RCON passwords match!"
        else
            fail "RCON passwords DO NOT match!"
            info ".env has: $ENV_RCON_PASS"
            info "server.properties has: $PROP_RCON_PASS"
            info "These must be identical for the bot and monitor to work"
        fi
    fi
    
    # Check if RCON is enabled
    RCON_ENABLED=$(grep -E "^enable-rcon=" "$INSTALL_DIR/server/server.properties" 2>/dev/null | cut -d'=' -f2)
    if [ "$RCON_ENABLED" = "true" ]; then
        pass "RCON is enabled in server.properties"
    else
        fail "RCON is not enabled - set enable-rcon=true in server.properties"
    fi
else
    fail "Cannot check RCON config - config files missing"
fi

echo ""

# Check Python dependencies

echo -e "${BLUE}[5/6] Checking Python dependencies...${NC}"

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    pass "Python $PYTHON_VERSION installed"
else
    fail "Python 3 not found"
fi

if python3 -c "import discord" 2>/dev/null; then
    DISCORD_PY_VERSION=$(python3 -c "import discord; print(discord.__version__)" 2>/dev/null)
    pass "discord.py $DISCORD_PY_VERSION installed"
else
    fail "discord.py not installed - run: pip install discord.py"
fi

echo ""

# Check systemd services

echo -e "${BLUE}[6/6] Checking systemd services...${NC}"

check_service() {
    local service=$1
    local service_file="/etc/systemd/system/${service}.service"
    
    if [ -f "$service_file" ]; then
        pass "$service service is installed"
        
        if systemctl is-enabled "$service" &>/dev/null; then
            pass "$service is enabled (auto-start on boot)"
        else
            warn "$service is not enabled for auto-start"
            info "Enable with: sudo systemctl enable $service"
        fi
        
        if systemctl is-active "$service" &>/dev/null; then
            pass "$service is currently running"
        else
            info "$service is not running (this is OK before first start)"
        fi
    else
        warn "$service service not installed"
        info "Install with: sudo cp $INSTALL_DIR/${service}.service /etc/systemd/system/"
    fi
}

check_service "minecraft"

# Discord bot service file is in a subdirectory
if [ -f "/etc/systemd/system/discord-bot.service" ]; then
    pass "discord-bot service is installed"
    if systemctl is-enabled "discord-bot" &>/dev/null; then
        pass "discord-bot is enabled (auto-start on boot)"
    else
        warn "discord-bot is not enabled for auto-start"
    fi
else
    warn "discord-bot service not installed"
fi

if [ -f "/etc/systemd/system/minecraft-monitor.service" ]; then
    pass "minecraft-monitor service is installed"
    if systemctl is-enabled "minecraft-monitor" &>/dev/null; then
        pass "minecraft-monitor is enabled (auto-start on boot)"
    else
        warn "minecraft-monitor is not enabled for auto-start"
    fi
else
    warn "minecraft-monitor service not installed"
fi

echo ""

# Summary

echo "═══════════════════════════════════════════════════════════════"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}All checks passed! Your setup looks good.${NC}"
    echo ""
    echo "Start the server with:"
    echo -e "  ${BLUE}sudo systemctl start minecraft${NC}"
    echo -e "  ${BLUE}sudo systemctl start discord-bot${NC}"
    echo -e "  ${BLUE}sudo systemctl start minecraft-monitor${NC}"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}Setup OK with $WARNINGS warning(s).${NC}"
    echo ""
    echo "You can probably start the server, but review the warnings above."
else
    echo -e "${RED}Found $ERRORS error(s) and $WARNINGS warning(s).${NC}"
    echo ""
    echo "Please fix the errors above before starting the server."
    echo "Most issues can be resolved by running ./install.sh"
fi

echo ""
exit $ERRORS
