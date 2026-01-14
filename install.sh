#!/bin/bash
# Minecraft Server Installer for Raspberry Pi 5

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Detect current user and installation directory
INSTALL_USER="${SUDO_USER:-$USER}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║       Minecraft Server for Raspberry Pi - Installer           ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
echo -e "Install directory: ${GREEN}$INSTALL_DIR${NC}"
echo -e "Running as user:   ${GREEN}$INSTALL_USER${NC}"
echo ""

# Check if running with appropriate permissions
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Note: Some steps require sudo. You may be prompted for your password.${NC}"
    echo ""
fi

# Helper functions

generate_password() {
    # Generate a random 16-character alphanumeric password
    # Works on systems without openssl by falling back to /dev/urandom
    if command -v openssl &> /dev/null; then
        openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 16
    else
        tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 16
    fi
}

generate_from_template() {
    local template="$1"
    local output="$2"
    
    if [ ! -f "$template" ]; then
        echo -e "${RED}Error: Template not found: $template${NC}"
        return 1
    fi
    
    sed -e "s|__USER__|$INSTALL_USER|g" \
        -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        "$template" > "$output"
    
    echo -e "  ${GREEN}✓${NC} Generated: $output"
}

# Step 1: Generate config files from templates

echo -e "${BLUE}[1/7] Generating configuration files from templates...${NC}"

# Generate start.sh
generate_from_template "$INSTALL_DIR/server/start.sh.template" "$INSTALL_DIR/server/start.sh"
chmod +x "$INSTALL_DIR/server/start.sh"

# Generate service files
generate_from_template "$INSTALL_DIR/minecraft.service.template" "$INSTALL_DIR/minecraft.service"
generate_from_template "$INSTALL_DIR/discord-bot/discord-bot.service.template" "$INSTALL_DIR/discord-bot/discord-bot.service"
generate_from_template "$INSTALL_DIR/mc-manager/minecraft-monitor.service.template" "$INSTALL_DIR/mc-manager/minecraft-monitor.service"

echo ""

# Step 2: Check/Install Java 21

echo -e "${BLUE}[2/7] Checking Java installation...${NC}"

if command -v java &> /dev/null; then
    JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [ "$JAVA_VERSION" -ge 21 ] 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Java $JAVA_VERSION is already installed"
    else
        echo -e "  ${YELLOW}!${NC} Java $JAVA_VERSION found, but Java 21+ is recommended"
        read -p "  Install Java 21? (y/N): " install_java
        if [[ "$install_java" =~ ^[Yy]$ ]]; then
            echo "  Installing Java 21..."
            sudo apt install -y wget apt-transport-https gpg
            wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | sudo gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg 2>/dev/null || true
            echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release) main" | sudo tee /etc/apt/sources.list.d/adoptium.list > /dev/null
            sudo apt update
            sudo apt install -y temurin-21-jre
            echo -e "  ${GREEN}✓${NC} Java 21 installed"
        fi
    fi
else
    echo -e "  ${YELLOW}!${NC} Java not found"
    read -p "  Install Java 21? (y/N): " install_java
    if [[ "$install_java" =~ ^[Yy]$ ]]; then
        echo "  Installing Java 21..."
        sudo apt install -y wget apt-transport-https gpg
        wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | sudo gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg 2>/dev/null || true
        echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release) main" | sudo tee /etc/apt/sources.list.d/adoptium.list > /dev/null
        sudo apt update
        sudo apt install -y temurin-21-jre
        echo -e "  ${GREEN}✓${NC} Java 21 installed"
    else
        echo -e "  ${RED}Warning: Java is required to run the Minecraft server${NC}"
    fi
fi

echo ""

# Step 3: Download Paper MC (if needed)

echo -e "${BLUE}[3/7] Checking Minecraft server...${NC}"

if [ -f "$INSTALL_DIR/server/server.jar" ]; then
    echo -e "  ${GREEN}✓${NC} server.jar already exists"
else
    read -p "  Download Paper MC 1.21.4? (y/N): " download_paper
    if [[ "$download_paper" =~ ^[Yy]$ ]]; then
        echo "  Downloading Paper MC..."
        PAPER_URL="https://api.papermc.io/v2/projects/paper/versions/1.21.4/builds/224/downloads/paper-1.21.4-224.jar"
        wget -q --show-progress -O "$INSTALL_DIR/server/server.jar" "$PAPER_URL"
        echo -e "  ${GREEN}✓${NC} Paper MC downloaded"
        
        # Accept EULA
        echo "eula=true" > "$INSTALL_DIR/server/eula.txt"
        echo -e "  ${GREEN}✓${NC} EULA accepted"
    fi
fi

echo ""

# Step 4: Setup RCON password and config files

echo -e "${BLUE}[4/7] Setting up configuration files...${NC}"

# Generate RCON password if needed (used for both .env and server.properties)
RCON_PASSWORD=""
GENERATED_NEW_PASSWORD=false

if [ -f "$INSTALL_DIR/.env" ]; then
    # Extract existing password from .env
    RCON_PASSWORD=$(grep -E "^RCON_PASSWORD=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d'=' -f2)
fi

if [ -z "$RCON_PASSWORD" ] || [ "$RCON_PASSWORD" = "change_this_password" ]; then
    RCON_PASSWORD=$(generate_password)
    GENERATED_NEW_PASSWORD=true
    echo -e "  ${GREEN}✓${NC} Generated secure RCON password"
fi

# Setup server.properties
if [ -f "$INSTALL_DIR/server/server.properties" ]; then
    echo -e "  ${GREEN}✓${NC} server.properties already exists"
    # Update RCON password if we generated a new one
    if [ "$GENERATED_NEW_PASSWORD" = true ]; then
        sed -i "s|^rcon.password=.*|rcon.password=$RCON_PASSWORD|" "$INSTALL_DIR/server/server.properties"
        echo -e "  ${GREEN}✓${NC} Updated RCON password in server.properties"
    fi
else
    if [ -f "$INSTALL_DIR/server/server.properties.example" ]; then
        sed "s|CHANGE_THIS_PASSWORD|$RCON_PASSWORD|g" "$INSTALL_DIR/server/server.properties.example" > "$INSTALL_DIR/server/server.properties"
        echo -e "  ${GREEN}✓${NC} Created server.properties with secure password"
    fi
fi

# Setup .env file
if [ -f "$INSTALL_DIR/.env" ]; then
    echo -e "  ${GREEN}✓${NC} .env already exists"
    # Update RCON password if we generated a new one
    if [ "$GENERATED_NEW_PASSWORD" = true ]; then
        sed -i "s|^RCON_PASSWORD=.*|RCON_PASSWORD=$RCON_PASSWORD|" "$INSTALL_DIR/.env"
        echo -e "  ${GREEN}✓${NC} Updated RCON password in .env"
    fi
else
    if [ -f "$INSTALL_DIR/.env.example" ]; then
        sed "s|change_this_password|$RCON_PASSWORD|g" "$INSTALL_DIR/.env.example" > "$INSTALL_DIR/.env"
        echo -e "  ${GREEN}✓${NC} Created .env with secure password"
    fi
fi

# Update STATE_FILE path in .env to use install directory
if [ -f "$INSTALL_DIR/.env" ]; then
    sed -i "s|^STATE_FILE=.*|STATE_FILE=$INSTALL_DIR/mc-manager/server_state.txt|" "$INSTALL_DIR/.env"
fi

echo ""

# Step 5: Configure Discord token

echo -e "${BLUE}[5/7] Configuring Discord bot...${NC}"

# Check if token already set
EXISTING_TOKEN=$(grep -E "^DISCORD_TOKEN=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d'=' -f2)

if [ -n "$EXISTING_TOKEN" ] && [ "$EXISTING_TOKEN" != "your_discord_bot_token_here" ]; then
    echo -e "  ${GREEN}✓${NC} Discord token already configured"
else
    echo ""
    echo -e "  ${YELLOW}To use the Discord bot, you need a bot token.${NC}"
    echo ""
    echo "  If you don't have one yet:"
    echo "    1. Go to https://discord.com/developers/applications"
    echo "    2. Create a new application"
    echo "    3. Go to 'Bot' section and click 'Reset Token'"
    echo "    4. Copy the token"
    echo ""
    read -p "  Enter your Discord bot token (or press Enter to skip): " DISCORD_TOKEN
    
    if [ -n "$DISCORD_TOKEN" ]; then
        # Basic validation - Discord tokens are typically 70+ characters
        if [ ${#DISCORD_TOKEN} -lt 50 ]; then
            echo -e "  ${YELLOW}!${NC} Warning: Token seems short (expected 70+ characters)"
            read -p "  Use this token anyway? (y/N): " use_anyway
            if [[ ! "$use_anyway" =~ ^[Yy]$ ]]; then
                DISCORD_TOKEN=""
            fi
        fi
        
        if [ -n "$DISCORD_TOKEN" ]; then
            sed -i "s|^DISCORD_TOKEN=.*|DISCORD_TOKEN=$DISCORD_TOKEN|" "$INSTALL_DIR/.env"
            echo -e "  ${GREEN}✓${NC} Discord token saved to .env"
        fi
    else
        echo -e "  ${YELLOW}!${NC} Skipped - you'll need to set DISCORD_TOKEN in .env later"
        echo "      ${BLUE}nano $INSTALL_DIR/.env${NC}"
    fi
fi

echo ""

# Step 6: Install Python dependencies

echo -e "${BLUE}[6/7] Installing Python dependencies...${NC}"

if pip3 install -q -r "$INSTALL_DIR/discord-bot/requirements.txt" 2>/dev/null || \
   pip install -q -r "$INSTALL_DIR/discord-bot/requirements.txt" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Python dependencies installed"
else
    echo -e "  ${YELLOW}!${NC} Could not install automatically. Run: pip install discord.py"
fi

echo ""

# Step 7: Install systemd services

echo -e "${BLUE}[7/7] Installing systemd services...${NC}"

read -p "  Install systemd services? (y/N): " install_services
if [[ "$install_services" =~ ^[Yy]$ ]]; then
    # Copy service files
    sudo cp "$INSTALL_DIR/minecraft.service" /etc/systemd/system/
    sudo cp "$INSTALL_DIR/discord-bot/discord-bot.service" /etc/systemd/system/
    sudo cp "$INSTALL_DIR/mc-manager/minecraft-monitor.service" /etc/systemd/system/
    echo -e "  ${GREEN}✓${NC} Service files installed"
    
    # Setup sudoers for passwordless minecraft control
    SUDOERS_FILE="/etc/sudoers.d/minecraft"
    sudo tee "$SUDOERS_FILE" > /dev/null << EOF
# Allow $INSTALL_USER to control minecraft service without password
# Required for Discord bot to start/stop the server
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl start minecraft
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop minecraft
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart minecraft
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl status minecraft
EOF
    sudo chmod 440 "$SUDOERS_FILE"
    echo -e "  ${GREEN}✓${NC} Sudo permissions configured"
    
    # Reload systemd
    sudo systemctl daemon-reload
    echo -e "  ${GREEN}✓${NC} systemd reloaded"
    
    # Enable services
    sudo systemctl enable minecraft
    sudo systemctl enable discord-bot
    sudo systemctl enable minecraft-monitor
    echo -e "  ${GREEN}✓${NC} Services enabled for auto-start"
fi

echo ""

# Done!

echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                    Installation Complete!                      ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
echo -e "${YELLOW}Verify your setup:${NC}"
echo "  ${BLUE}./test.sh${NC}"
echo ""
echo -e "${YELLOW}To start the server:${NC}"
echo "  ${BLUE}sudo systemctl start minecraft${NC}"
echo "  ${BLUE}sudo systemctl start discord-bot${NC}"
echo "  ${BLUE}sudo systemctl start minecraft-monitor${NC}"
echo ""
echo -e "${YELLOW}To view logs:${NC}"
echo "  ${BLUE}sudo journalctl -u minecraft -f${NC}"
echo ""
echo -e "${YELLOW}Discord commands:${NC}"
echo "  !ip     - Get server IP address"
echo "  !status - Check server status"
echo "  !up     - Start the server"
echo ""
