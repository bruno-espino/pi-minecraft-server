#!/bin/bash
# Starts all three services at once

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting Minecraft server services...${NC}"
echo ""

# Start Minecraft server
echo -n "Starting Minecraft server... "
if sudo systemctl start minecraft 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    echo "Failed to start minecraft service. Check: sudo journalctl -u minecraft -n 20"
fi

# Start Discord bot
echo -n "Starting Discord bot... "
if sudo systemctl start discord-bot 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    echo "Failed to start discord-bot service. Check: sudo journalctl -u discord-bot -n 20"
fi

# Start Auto-shutdown monitor
echo -n "Starting auto-shutdown monitor... "
if sudo systemctl start minecraft-monitor 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    echo "Failed to start minecraft-monitor service. Check: sudo journalctl -u minecraft-monitor -n 20"
fi

echo ""
echo -e "${BLUE}Checking service status...${NC}"
echo ""

# Show status of all services
sudo systemctl status minecraft discord-bot minecraft-monitor --no-pager | grep -E "(●|Active:|Loaded:)" || true

echo ""
echo -e "${GREEN}Done!${NC}"
echo ""
echo "View logs with:"
echo "  sudo journalctl -u minecraft -f"
echo "  sudo journalctl -u discord-bot -f"
echo "  sudo journalctl -u minecraft-monitor -f"
echo ""
echo "The Minecraft server takes 30-60 seconds to fully start."
echo "Use Discord command: !status"
