# Minecraft Server for Raspberry Pi

A Minecraft server for a group of friends, on a Raspberry Pi 5 or any small
Debian or Ubuntu machine. One installer sets up Paper (plugins) or Fabric
(mods), and the server starts from Discord and shuts down when nobody plays.

- **Guided install** that also gets Java and sizes memory to the machine; rerun it to update
- **Mods and plugins from Modrinth** with their dependencies, plus a one-file
  **modpack for players** with the exact versions the server runs
- **Discord bot:** `!up` starts the server, `!status`, `!ip`, `!mods`; a message when it shuts down
- **Idle shutdown** after 30 minutes without players, so the machine is free
  the rest of the time; starts again after a power cut
- **Nightly backups** that skip unchanged worlds, and one-command restore
- **`mcserver`** for status, console, logs, backups, terrain pregeneration and updates

## Quick start

On a Raspberry Pi, install **Raspberry Pi OS Lite (64-bit)** with
[Raspberry Pi Imager](https://www.raspberrypi.com/software/) (enable SSH in its
settings), then log in and run:

```bash
sudo apt install -y git
git clone https://github.com/bruno-espino/pi-minecraft-server.git
cd pi-minecraft-server
./install.sh
mcserver start
```

The installer asks a few questions: Paper or Fabric, memory, whether players
have official accounts, the world type and an optional Discord bot. Each has a
default you can accept with Enter. Players on your network then connect to the
address it prints, and [players elsewhere](#playing-from-outside-your-network)
need one more step.

## What you need

| | Recommended | Minimum |
|---|---|---|
| Machine | Raspberry Pi 5, 8 GB | Any 64-bit machine with 2 GB RAM (Paper) or 4 GB (mods) |
| System | Raspberry Pi OS Lite (64-bit), Debian 12+, Ubuntu 22.04+ | Debian-based with systemd and `python3` |
| Storage | SSD (NVMe or USB) | SD card (slower worlds, more wear) |
| Pi extras | Active Cooler or a cooled case; the official 27 W power supply | |

The installer adds `python3-venv` with apt if it is missing and downloads Java
(Eclipse Temurin, into `java/`) unless a new enough one is installed.

Tested on a Raspberry Pi 5 (8 GB) with Raspberry Pi OS based on Debian 12, and
with fresh installs on x86-64 Debian 12, Debian 13 and Ubuntu 24.04.

## Install

The installer shows a summary before it changes anything, then:

1. writes `.env` (mode 600) with every setting, so later runs keep them
2. downloads Java if needed, the server, and the mods or plugins
3. creates `server/` with `server.properties`, `start.sh` and the world
4. installs three systemd units: `minecraft`, `minecraft-manager` (bot and idle
   shutdown) and `minecraft-backup.timer`, a sudo rule that lets the manager
   start and stop `minecraft`, and the `mcserver` command

Options skip their question, and `--yes` skips them all for scripted installs.
Later runs keep the saved settings and only ask what is missing; add `--guided`
to answer every question again. `./install.sh --help` lists all options:

| Option | Purpose |
|---|---|
| `--server paper\|fabric` | Server software |
| `--version 26.3` | Minecraft version |
| `--memory 4096` | Maximum Java heap in MiB; `auto` (the default) uses half the RAM, up to 8 GiB |
| `--online-mode false` | Allow players without official accounts (see [Security](#security)) |
| `--whitelist on\|off` | Only let listed players join; new installs start with it off |
| `--world-type normal` | World type for a new world: `normal`, `large-biomes`, `amplified`, `flat`, or a mod's type |
| `--new-world` | Move the current world to `backups/old-worlds/` and start fresh |
| `--port 25565`, `--rcon-port 25575` | Game and local console ports |
| `--no-services` | Skip systemd; start the server yourself with `server/start.sh` |

The world type is fixed when a world is created, so pick it before the first
start (or together with `--new-world`). Some world-generation mods need their
own type: BetterEnd and BetterNether only generate their terrain in a world made
with `--world-type wover:normal`, whose overworld is the vanilla one, so they
combine with overworld mods such as Terralith. The installer suggests it when
they are in `mods.txt`.

Everything the installer creates (`.env`, `server/`, `backups/`, `java/`,
`.venv/`) is ignored by git. `mcserver update` pulls the latest version of this
project and reruns the installer, which also updates the server, mods and Java
to their newest builds for your Minecraft version.

## Day to day

| Command | Does |
|---|---|
| `mcserver status` | Running or not, players, tick time, memory, disk, backups, temperature |
| `mcserver start`, `stop`, `restart` | Stopping saves the world first, and asks when players are online |
| `mcserver console` | Type console commands (`op Steve`, `whitelist add Steve`, `difficulty hard`) |
| `mcserver cmd COMMAND` | Run one console command |
| `mcserver logs` | Follow the server log |
| `mcserver backup`, `backups` | Back up now; list backups |
| `mcserver restore [BACKUP]` | Replace the world with a backup (default: the newest) |
| `mcserver pregen 3000 [nether\|end]` | Generate terrain ahead of play; see [Performance](#performance) |
| `mcserver update` | Update this project, the server, mods and Java |

To make yourself an operator: `mcserver cmd op YOUR_NAME`.

Backups run nightly into `backups/` (the newest seven are kept) and include the
world, `server.properties`, player lists, mod configs and your mod list.
`mcserver restore` stops the server, moves the current world to
`backups/old-worlds/` (nothing is deleted) and unpacks the backup's world.

## Mods and plugins

List Modrinth project names (from `https://modrinth.com/mod/<name>`) in
`mods.txt` for Fabric or `plugins.txt` for Paper, then rerun `./install.sh` and
`mcserver restart`. The first install creates these from `mods.example.txt` and
`plugins.example.txt`, which hold server-side performance mods and tools only.
Your lists are not tracked by git, so updates never change your choices.

For each project the installer downloads the newest build for your Minecraft
version, checks its hash, and adds required dependencies. It stops with a list
if any mod has no build for that version. Client-only mods you list (Sodium,
shaders, minimaps) are skipped on the server but offered to players. Mods it
installed earlier and you removed from the list are deleted; jars you add by
hand are left alone.

**Players** need Fabric and the same gameplay mods as the server. The installer
writes a modpack, `server/client-pack.mrpack`, with the exact versions the
server runs; the Discord bot shares it with `!mods`. Players import it in the
[Modrinth App](https://modrinth.com/app) or [Prism Launcher](https://prismlauncher.org/)
(Add instance, Import). The pack only lists download links and hashes, so it's
a few KB and redistributes no mod files.

- **Required in the pack:** mods that run on both sides (blocks, items) and
  everything they depend on, such as Fabric API and libraries.
- **Optional:** client-only mods you list (Sodium) and mods tagged `client` in
  `mods.txt`, for example `jei client`. The tag also makes a mod optional when
  Modrinth marks it required on clients, such as a minimap.
- **Left out:** server-only mods and performance mods like Lithium.

When mods change (including after `mcserver update`), players import the new pack.

## Playing from outside your network

Players on your Wi-Fi connect to the machine's local address (shown by
`mcserver status`). For friends elsewhere, either:

- **Forward a port:** in your router's settings, forward TCP port 25565 to the
  machine's local address, and give it a fixed (reserved) address there.
  Friends connect to your public IP, which `!ip` shows. If it changes often, a
  dynamic DNS name helps; put it in `SERVER_ADDRESS` in `.env`. Some internet
  providers (CGNAT, many mobile connections) don't allow incoming connections;
  then use a tunnel.
- **Use a tunnel** such as [playit.gg](https://playit.gg), which gives you a
  public address without touching the router.

Forward only the game port, never the RCON port.

### Bedrock players

Phones, tablets and consoles run Bedrock Edition. The
[Geyser](https://geysermc.org) plugin or mod (`geyser` in `plugins.txt` or
`mods.txt`) lets them join a Java server; forward UDP port 19132 for it. See
Geyser's documentation for accounts (Floodgate) and settings.

## Discord

Create an application in the
[Discord Developer Portal](https://discord.com/developers/applications), add a
bot, enable **Message Content Intent**, copy its token, and invite it with View
Channels, Send Messages, Read Message History and Attach Files (for the `!mods`
pack). Give the token to the installer (`./install.sh --guided` on an existing
install).

| Command | Does |
|---|---|
| `!up` | Starts the server and reports when it is ready |
| `!status` | Online or offline, and who is playing |
| `!ip` | Connection address |
| `!mods` | Mods players need, with the modpack attached (Fabric) |
| `!help` | Command list |

The bot posts to `NOTIFICATION_CHANNEL_ID` when the server shuts down for
inactivity or finishes a pregeneration. `SERVER_ADDRESS` shows a hostname instead
of the public IP.

## Settings in `.env`

The installer owns `.env` but keeps your values. After editing it, run
`sudo systemctl restart minecraft-manager`. Besides the options above:

| Setting | Default | Purpose |
|---|---|---|
| `IDLE_TIMEOUT_MINUTES` | 30 | Minutes without players before shutdown |
| `AUTO_SHUTDOWN` | true | `false` keeps the server running |
| `CHECK_INTERVAL_SECONDS` | 60 | How often the player count is checked |
| `BACKUP_KEEP` | 7 | Number of backups to keep |
| `NOTIFICATION_CHANNEL_ID` | | Discord channel for shutdown messages |
| `SERVER_ADDRESS` | | Hostname shown by `!ip` and `!status` |

Game settings (difficulty, MOTD, view distance, max players) live in
`server/server.properties`; restart the server after changing them. The
installer only manages the port, RCON, online-mode, whitelist and world-type lines.

## Performance

- **Generating new terrain is the expensive part.** On a Pi, exploring
  ungenerated land causes multi-second lag spikes; generated land doesn't.
  Before inviting players, run `mcserver pregen 3000` (Chunky must be in your
  list, as in the examples), and `mcserver pregen 2000 nether` or `end` if
  they will travel there. It runs inside the server, players can join
  meanwhile, and idle shutdown waits for it. A 3000-block radius is about
  140,000 chunks, roughly 40 minutes on a Pi 5.
- **Distances:** new installs use `view-distance=8` and `simulation-distance=6`.
  Lowering `simulation-distance` to 4 is the biggest saving when it lags.
- **Watch it:** `mcserver status` shows the average tick time; above 50 ms the
  game slows down. In game, `/spark tps` and `/spark profiler` find the cause
  (spark is in `mods.example.txt` and built into Paper).
- **Memory:** the heap starts at 1 GiB and grows up to `--memory`. Java's
  default garbage collector settings work well; extra JVM flags aren't needed.
- **Keep the Pi cool.** A Pi 5 slows itself down from about 80 °C, which shows
  as lag; `mcserver status` reports it. Leave room around the case, and keep its
  vents and fan free of dust.

## Troubleshooting

| Problem | Try |
|---|---|
| Players can't connect | `mcserver status` to see it's running; use the address it shows; from outside, see [port forwarding](#playing-from-outside-your-network); if a firewall is on: `sudo ufw allow 25565/tcp` |
| "Mods do not match" or registry errors when joining | The player's mods differ from the server's: import the current pack from `!mods` again |
| The server stops by itself | Idle shutdown after `IDLE_TIMEOUT_MINUTES`; `!up` or `mcserver start` brings it back |
| The server crashes on start | `mcserver logs`, or `journalctl -u minecraft -n 100`; a mod without a build for your version is the usual cause |
| The bot is offline | `journalctl -u minecraft-manager -n 50`; check the token and Message Content Intent |
| Lag | See [Performance](#performance); `mcserver status` shows tick time and throttling |
| Under-voltage warning | Use the official 27 W power supply; SSDs and USB devices need the extra current |

## Security

- RCON listens only on the machine; never forward its port.
- With `--online-mode false`, the server doesn't check accounts, so anyone can join
  with any username, including an operator's. Keep the operator list short, or
  use the whitelist if the server is public.
- Whitelist without a restart: `mcserver cmd whitelist add NAME`, then
  `mcserver cmd whitelist on`.
- `.env` and `server/server.properties` hold the Discord token and RCON
  password; they are readable only by your user.

## Uninstall

```bash
sudo systemctl disable --now minecraft minecraft-manager minecraft-backup.timer
sudo rm /etc/systemd/system/minecraft{,-manager,-backup}.service \
    /etc/systemd/system/minecraft-backup.timer /etc/sudoers.d/minecraft /usr/local/bin/mcserver
sudo systemctl daemon-reload
```

Then delete the checkout, after copying `backups/` somewhere if you want to keep your worlds.

## License

[MIT](LICENSE)
