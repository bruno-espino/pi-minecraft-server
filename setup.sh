#!/bin/bash
# =============================================================================
# Minecraft Server Quick Setup Script
# Downloads Java and Paper MC server
#
# For full installation including Discord bot and auto-shutdown,
# use install.sh instead.
# =============================================================================

set -e

# Detect install directory
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Minecraft Server Quick Setup ==="
echo ""
echo "Install directory: $INSTALL_DIR"
echo ""

# Install Java 21 (required for modern Minecraft versions)
echo "[1/4] Installing Java 21 from Adoptium (Eclipse Temurin)..."

# Add Adoptium repository
sudo apt install -y wget apt-transport-https gpg
wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | sudo gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg 2>/dev/null || true
echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release) main" | sudo tee /etc/apt/sources.list.d/adoptium.list > /dev/null

sudo apt update
sudo apt install -y temurin-21-jre

# Verify Java installation
echo ""
java -version
echo ""

# Create server directory if it doesn't exist
echo "[2/4] Setting up server directory..."
mkdir -p "$INSTALL_DIR/server"

# Download Paper MC (optimized for performance - better than vanilla for Pi)
echo ""
echo "[3/4] Downloading Paper MC server (1.21.4)..."
# Paper is much more performant than vanilla, especially on ARM
PAPER_URL="https://api.papermc.io/v2/projects/paper/versions/1.21.4/builds/224/downloads/paper-1.21.4-224.jar"
wget -O "$INSTALL_DIR/server/server.jar" "$PAPER_URL"

# Accept EULA
echo ""
echo "[4/4] Accepting Minecraft EULA..."
echo "eula=true" > "$INSTALL_DIR/server/eula.txt"

# Copy server.properties template if it doesn't exist
if [ ! -f "$INSTALL_DIR/server/server.properties" ] && [ -f "$INSTALL_DIR/server/server.properties.example" ]; then
    cp "$INSTALL_DIR/server/server.properties.example" "$INSTALL_DIR/server/server.properties"
    echo "Created server.properties from template"
fi

echo ""
echo "=== Quick Setup Complete! ==="
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit server.properties and set a secure rcon.password:"
echo "     nano $INSTALL_DIR/server/server.properties"
echo ""
echo "  2. Run the full installer for Discord bot and auto-shutdown:"
echo "     ./install.sh"
echo ""
echo "Or to just start the server manually:"
echo "  cd $INSTALL_DIR/server && java -jar server.jar --nogui"
echo ""
