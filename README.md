# Minecraft Server for Raspberry Pi

A self-hosted Minecraft server setup for Raspberry Pi 5 with Discord control and auto-shutdown to save power.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Your Raspberry Pi                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │   Discord    │    │  Minecraft   │    │   Auto-Shutdown      │   │
│  │     Bot      │───▶│    Server    │◀───│     Monitor          │   │
│  │  (bot.py)    │    │ (Paper MC)   │    │   (monitor.py)       │   │
│  └──────┬───────┘    └──────────────┘    └──────────┬───────────┘   │
│         │                   ▲                       │               │
│         │                   │ RCON                  │               │
│         │                   │                       │               │
│         └───────────────────┴───────────────────────┘               │
│                    state file communication                          │
└─────────────────────────────────────────────────────────────────────┘
         │                                                    
         │ Discord API                                        
         ▼                                                    
┌─────────────────┐         ┌─────────────────┐
│  Discord Server │         │ Minecraft       │
│  (!ip, !status, │         │ Players         │
│   !up commands) │         │                 │
└─────────────────┘         └─────────────────┘
```

## Features

| Feature | Description |
|---------|-------------|
| **Discord Bot** | Control your server remotely with simple commands |
| `!ip` | Get the server's public IP address |
| `!status` | Check if server is online and see player count |
| `!up` | Start the server remotely from Discord |
| **Auto-Shutdown** | Server stops after 30 minutes of no players |
| **Notifications** | Discord alerts when server auto-stops |
| **Systemd Services** | Proper service management with auto-start on boot |

## How It Works

1. **Discord Bot** listens for commands in your Discord server
2. **Minecraft Server** runs Paper MC with optimized JVM flags for ARM
3. **Auto-Shutdown Monitor** checks player count via RCON every minute
4. When no players are online for 30 minutes, the monitor gracefully stops the server
5. The bot and monitor communicate via a state file to send Discord notifications

## Requirements

- Raspberry Pi 5 with 8GB RAM (also works on other Linux systems)
- Debian/Ubuntu-based OS (Raspberry Pi OS recommended)
- Python 3.11+
- Internet connection

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/bruno-espino/pi-minecraft-server.git
cd pi-minecraft-server
```

### 2. Run the Installer

```bash
chmod +x install.sh
./install.sh
```

The installer will:
- Install Java 21 (if needed)
- Download Paper MC (if needed)
- Auto-generate a secure RCON password
- Prompt for your Discord bot token
- Set up systemd services

### 3. Verify Your Setup

The installer will prompt you for your Discord bot token and auto-generate a secure RCON password.

After installation, verify everything is configured:

```bash
./test.sh
```

### 4. Start Everything

**Easy way** (all services at once):
```bash
./start-all.sh
```

**Or start individually**:
```bash
sudo systemctl start minecraft
sudo systemctl start discord-bot
sudo systemctl start minecraft-monitor
```

## Verifying Your Setup

After installation, run the test script to verify everything is configured:

```bash
./test.sh
```

The test checks:
- Required files exist (.env, server.properties, server.jar)
- Java 21+ is installed
- Discord token is set and valid format
- RCON passwords match in both config files
- Python dependencies are installed
- Systemd services are installed and enabled

## Discord Bot Setup

The installer will prompt you for a Discord bot token. If you don't have one yet, follow these steps:

### Creating Your Discord Bot

1. **Create Application**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application"
   - Give it a name (e.g., "Minecraft Server Bot")
   - Click "Create"

2. **Create Bot User**
   - In the left sidebar, click "Bot"
   - Click "Add Bot" → "Yes, do it!"
   - Under "Privileged Gateway Intents", enable **Message Content Intent** (required for commands)

3. **Get Your Bot Token**
   - Still in the Bot section, click "Reset Token"
   - Copy the token and **save it securely** (you'll need it during installation)
   - ⚠️ Never share this token publicly!

4. **Invite Bot to Your Server**
   - In the left sidebar, click "OAuth2" → "URL Generator"
   - Under Scopes, check: `bot`
   - Under Bot Permissions, check: `Send Messages` and `Read Message History`
   - Copy the generated URL at the bottom
   - Open the URL in your browser and select your Discord server

5. **Optional: Get Channel ID for Notifications**
   - In Discord, go to User Settings → Advanced → Enable "Developer Mode"
   - Right-click the channel where you want shutdown notifications
   - Click "Copy Channel ID"
   - You can add this to `.env` as `NOTIFICATION_CHANNEL_ID` later

**Need help?** See the [official Discord bot guide](https://discord.com/developers/docs/getting-started)

## Project Structure

```
pi-minecraft-server/
├── install.sh                    # Main installer (run this!)
├── test.sh                       # Verify your setup
├── start-all.sh                  # Start all services at once
├── stop-all.sh                   # Stop all services at once
├── setup.sh                      # Quick setup (Java + Paper MC only)
├── .env.example                  # Environment template
├── minecraft.service.template    # Systemd service template
│
├── discord-bot/
│   ├── bot.py                    # Discord bot
│   ├── requirements.txt          # Python dependencies
│   └── discord-bot.service.template
│
├── mc-manager/
│   ├── monitor.py                # Auto-shutdown monitor
│   ├── install.sh                # Monitor-only installer
│   └── minecraft-monitor.service.template
│
├── server/
│   ├── start.sh.template         # Server start script template
│   ├── server.properties.example # Server config template
│   └── ...                       # Server files (generated)
│
└── shared/
    ├── __init__.py
    └── rcon.py                   # Shared RCON client library
```

## Configuration

### Environment Variables

The installer handles most configuration automatically. You only need to provide:

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Your Discord bot token |
| `NOTIFICATION_CHANNEL_ID` | No | Channel ID for shutdown notifications |

**Advanced settings** (have good defaults):
| Variable | Default | Description |
|----------|---------|-------------|
| `RCON_PASSWORD` | Auto-generated | Don't set this - installer generates it |
| `RCON_HOST` | localhost | RCON connection host |
| `RCON_PORT` | 25575 | RCON port |
| `MINECRAFT_PORT` | 25565 | Minecraft Java port |
| `BEDROCK_PORT` | 19132 | Minecraft Bedrock port |
| `IDLE_TIMEOUT_MINUTES` | 30 | Minutes before auto-shutdown |
| `CHECK_INTERVAL_SECONDS` | 60 | How often to check player count |

### JVM Settings

Uses [Aikar's optimized flags](https://docs.papermc.io/paper/aikars-flags) with 3.5GB allocation (leaves ~4.5GB for OS and mods):

```bash
java -Xms3584M -Xmx3584M \
  -XX:+UseG1GC \
  -XX:+ParallelRefProcEnabled \
  -XX:MaxGCPauseMillis=200 \
  # ... and more
```

**Why 3.5GB?** Leaves headroom for:
- OS and background processes (~2GB)
- Plugin overhead (Essentials, Geyser, etc.)
- Chunk generation spikes
- Multiple simultaneous players

Adjust in `server/start.sh.template` if needed. Don't go above 6GB on an 8GB Pi.

## Service Management

### Quick Commands

```bash
# Start all services
./start-all.sh

# Stop all services
./stop-all.sh
```

### Individual Service Control

```bash
# Minecraft server
sudo systemctl start minecraft
sudo systemctl stop minecraft
sudo systemctl status minecraft
sudo journalctl -u minecraft -f  # View logs

# Discord bot
sudo systemctl start discord-bot
sudo systemctl stop discord-bot
sudo systemctl status discord-bot
sudo journalctl -u discord-bot -f

# Auto-shutdown monitor
sudo systemctl start minecraft-monitor
sudo systemctl stop minecraft-monitor
sudo systemctl status minecraft-monitor
sudo journalctl -u minecraft-monitor -f
```

## Troubleshooting

### Server won't start

```bash
# Check logs
sudo journalctl -u minecraft -n 50

# Verify Java installation
java -version  # Should show Java 21+

# Try starting manually
cd server && ./start.sh
```

### Discord bot not responding

```bash
# Check if running
sudo systemctl status discord-bot

# Check logs
sudo journalctl -u discord-bot -n 50

# Verify token is set
grep DISCORD_TOKEN .env
```

### RCON connection failed

- Ensure `enable-rcon=true` in `server/server.properties`
- Verify passwords match in `.env` and `server/server.properties`
- Check that RCON port (25575) is not blocked
- Wait for server to fully start (RCON takes ~30 seconds after server start)

### Auto-shutdown not working

```bash
# Check monitor status
sudo systemctl status minecraft-monitor

# Check logs
sudo journalctl -u minecraft-monitor -f

# Verify RCON_PASSWORD is set correctly
grep RCON_PASSWORD .env
```

## Performance Tips

1. **Use an SSD** - USB 3.0 SSD dramatically improves chunk loading
2. **Reduce view distance** - Set `view-distance=8` or lower in `server.properties`
3. **Limit players** - Pi 5 handles 4-6 players well
4. **Pre-generate world** - Use [Chunky](https://www.spigotmc.org/resources/chunky.81534/) plugin to pre-generate chunks
5. **Use Paper MC** - Already included; much faster than vanilla on ARM

## Updating

To update Paper MC:
```bash
cd server
# Check latest version at https://papermc.io/downloads/paper
wget -O server.jar "https://api.papermc.io/v2/projects/paper/versions/1.21.4/builds/XXX/downloads/paper-1.21.4-XXX.jar"
sudo systemctl restart minecraft
```

## Uninstalling

```bash
# Stop and disable services
sudo systemctl stop minecraft discord-bot minecraft-monitor
sudo systemctl disable minecraft discord-bot minecraft-monitor

# Remove service files
sudo rm /etc/systemd/system/minecraft.service
sudo rm /etc/systemd/system/discord-bot.service
sudo rm /etc/systemd/system/minecraft-monitor.service
sudo rm /etc/sudoers.d/minecraft

# Reload systemd
sudo systemctl daemon-reload
```

## Contributing

Contributions welcome! Open an issue or submit a PR.

## Credits

- [Paper MC](https://papermc.io/) - High-performance Minecraft server
- [Aikar's Flags](https://docs.papermc.io/paper/aikars-flags) - JVM optimization flags
- [discord.py](https://discordpy.readthedocs.io/) - Discord bot framework
