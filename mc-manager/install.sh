#!/bin/bash
# Installation script for Minecraft auto-shutdown monitor only
# For full installation, use the main install.sh in the project root
# Run with: sudo bash install.sh

set -e

echo "=== Minecraft Auto-Shutdown Monitor Installation ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo bash install.sh"
    exit 1
fi

# Detect user and install directory
INSTALL_USER="${SUDO_USER:-$USER}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Install directory: $INSTALL_DIR"
echo "User: $INSTALL_USER"
echo ""

# Generate service file from template if needed
if [ -f "$INSTALL_DIR/mc-manager/minecraft-monitor.service.template" ]; then
    echo "[1/4] Generating service file from template..."
    sed -e "s|__USER__|$INSTALL_USER|g" \
        -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        "$INSTALL_DIR/mc-manager/minecraft-monitor.service.template" > \
        "$INSTALL_DIR/mc-manager/minecraft-monitor.service"
    echo "      Done!"
else
    echo "[1/4] Using existing service file..."
fi

# Install the monitor service
echo "[2/4] Installing monitor service..."
cp "$INSTALL_DIR/mc-manager/minecraft-monitor.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable minecraft-monitor
echo "      Done!"

# Configure sudoers for passwordless minecraft control
echo "[3/4] Configuring sudo permissions..."
SUDOERS_FILE="/etc/sudoers.d/minecraft"
cat > "$SUDOERS_FILE" << EOF
# Allow $INSTALL_USER to start/stop minecraft service without password
# This is needed for the Discord bot to control the server
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl start minecraft
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop minecraft
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart minecraft
$INSTALL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl status minecraft
EOF
chmod 440 "$SUDOERS_FILE"
echo "      Done!"

# Start the monitor service
echo "[4/4] Starting monitor service..."
systemctl start minecraft-monitor
echo "      Done!"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Services status:"
systemctl is-active minecraft && echo "  - minecraft: running" || echo "  - minecraft: stopped"
systemctl is-active minecraft-monitor && echo "  - minecraft-monitor: running" || echo "  - minecraft-monitor: stopped"
echo ""
echo "The server will now automatically shut down after 30 minutes"
echo "of no players. Players can use !up on Discord to restart it."
echo ""
