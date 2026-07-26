# Minecraft Server for Raspberry Pi

A small Paper Minecraft server for Raspberry Pi 5 with Discord control and
automatic idle shutdown.

## Features

- Paper configured for an 8 GB Raspberry Pi
- `!ip`, `!status`, and `!up` Discord commands
- Graceful shutdown after 30 minutes without players
- Isolated named instances for safe testing
- Generated RCON password and protected `.env`
- systemd services for Minecraft, Discord, and the idle monitor

## Requirements

- Raspberry Pi OS, Debian, or Ubuntu
- Java 25 for the default Paper 26.1.2 release
- Python 3 with the `venv` module
- A Discord bot token if Discord control is wanted

## Install

```bash
git clone https://github.com/bruno-espino/pi-minecraft-server.git
cd pi-minecraft-server
./install.sh --install-services
```

The installer asks for EULA acceptance, a Discord token, and confirmation
before changing system services. It downloads a stable Paper build, generates
one root `.env`, creates a Python virtual environment, and enables the units.

Start and inspect the installation:

```bash
./manage.sh start
./manage.sh status
./test.sh
```

To omit Discord:

```bash
./install.sh --no-discord --install-services
```

For an unattended installation, provide the token through the environment:

```bash
DISCORD_TOKEN='...' ./install.sh \
  --accept-eula --non-interactive --install-services
```

## Discord setup

Create a bot in the
[Discord Developer Portal](https://discord.com/developers/applications), enable
the Message Content intent, and invite it with View Channel, Send Messages, and
Read Message History permissions.

| Command | Purpose |
|---|---|
| `!ip` | Show the Java server address |
| `!status` | Show server and player status |
| `!up` | Start Minecraft |

Set `NOTIFICATION_CHANNEL_ID` in `.env` to announce idle shutdowns.

## Configuration

The installer owns these generated files:

- `.env` — bot, RCON, ports, timeout, and service name
- `server/server.properties` — Minecraft and RCON configuration
- `server/start.sh` — JVM memory and launch command
- generated `.service` files — systemd definitions

Rerun the installer with options to change generated settings:

```text
--minecraft-version VERSION
--minecraft-port PORT
--rcon-port PORT
--memory MB
--java-bin PATH
--instance NAME
--no-discord
--install-services
--start
--dry-run
```

The defaults are Paper 26.1.2, authenticated Java Edition on port `25565`,
local RCON on `25575`, and 3584 MiB of memory. Paper 26.1+ requires Java 25;
older 1.21.x releases use Java 21. Bedrock support is not installed or advertised.
Forward only the Minecraft port through the router; never expose the RCON port.

## Safe staging instance

A named instance gets unique unit names. Give it unique ports and a smaller
memory allocation:

```bash
./install.sh \
  --instance staging \
  --minecraft-port 25566 \
  --rcon-port 25576 \
  --memory 1280 \
  --no-discord \
  --accept-eula \
  --non-interactive
```

Run it manually from `server/start.sh`, or add `--install-services` after
reviewing the generated configuration. Do not run two servers simultaneously
unless the machine has enough free memory.

## Operations

```bash
./manage.sh start [instance]
./manage.sh stop [instance]
./manage.sh restart [instance]
./manage.sh status [instance]
sudo journalctl -u minecraft -f
```

The idle monitor does not start Minecraft merely because the monitor itself
starts. Minecraft is started explicitly or through `!up`.

## Security

- Online authentication and secure profiles are enabled by default.
- `.env` is created with mode `600`.
- RCON uses an automatically generated password and should not be forwarded
  through the router.
- Discord commands are available to members who can access the bot's channel.
- Do not commit `.env`, server data, or generated service files.

## Troubleshooting

Run `./test.sh`, then inspect the relevant journal:

```bash
sudo journalctl -u minecraft -n 100
sudo journalctl -u discord-bot -n 100
sudo journalctl -u minecraft-monitor -n 100
```

Paper can take a minute to generate its first world. If installation cannot
create `venv`, install the distribution's `python3-venv` package.

## Uninstall system services

Stop the instance, remove its three unit files and corresponding
`/etc/sudoers.d/minecraft-INSTANCE` file, then run:

```bash
sudo systemctl daemon-reload
```

Worlds, configuration, and secrets remain in the cloned directory until
removed manually.
