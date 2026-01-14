#!/bin/bash
# Stops all three services at once

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}Stopping Minecraft server services...${NC}"
echo ""

# Stop Auto-shutdown monitor first (so it doesn't interfere)
echo -n "Stopping auto-shutdown monitor... "
if sudo systemctl stop minecraft-monitor 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}~${NC} (may not be running)"
fi

# Stop Discord bot
echo -n "Stopping Discord bot... "
if sudo systemctl stop discord-bot 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}~${NC} (may not be running)"
fi

# Stop Minecraft server last (gives it time to save)
echo -n "Stopping Minecraft server... "
if sudo systemctl stop minecraft 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}~${NC} (may not be running)"
fi

echo ""
echo -e "${BLUE}Waiting for services to fully stop...${NC}"
sleep 2

echo ""
echo -e "${BLUE}Final service status:${NC}"
echo ""

# Show status of all services
sudo systemctl status minecraft discord-bot minecraft-monitor --no-pager | grep -E "(●|Active:|Loaded:)" || true

echo ""
echo -e "${GREEN}Done!${NC}"
echo ""
echo "All services stopped. Start again with:"
echo "  ./start-all.sh"
echo ""
