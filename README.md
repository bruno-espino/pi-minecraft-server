# Minecraft Server for Raspberry Pi

A Paper or Fabric Minecraft server for a Raspberry Pi 5 (8 GB), with a Discord
bot to start it, automatic shutdown when nobody is playing, and nightly backups.

- `install.sh` installs or updates everything and can be rerun safely
- Paper (plugins) or Fabric (mods), with mods and plugins downloaded from Modrinth
- Discord: `!up`, `!status`, `!ip`, `!help`, plus a message when the server shuts down
- Shuts down after 30 minutes without players; starts again after a power cut
- Nightly backups that skip unchanged worlds and keep the newest seven

## Requirements

- Raspberry Pi OS / Debian / Ubuntu with systemd, `python3` and `python3-venv`
- Java 25 for Minecraft 26.x (the installer finds it under `/usr/lib/jvm`)
- Optional: a Discord bot token

## Install

```bash
git clone https://github.com/bruno-espino/pi-minecraft-server.git
cd pi-minecraft-server
./install.sh --server fabric --version 26.3
```

The installer asks you to accept the Minecraft EULA and for a Discord token
(leave it empty to run without Discord), shows a summary, and then:

1. writes `.env` (mode 600) with every setting, so later runs keep them
2. downloads the server jar and the mods or plugins
3. creates `server/` with `server.properties`, `start.sh` and the world
4. installs three systemd units: `minecraft`, `minecraft-manager` (bot and idle
   shutdown) and `minecraft-backup.timer`, plus a sudo rule that lets the
   manager start and stop `minecraft`

Run `./install.sh --help` for all options. Useful ones:

| Option | Purpose |
|---|---|
| `--server paper\|fabric` | Server software |
| `--version 26.3` | Minecraft version |
| `--memory 4096` | Maximum Java heap in MiB |
| `--online-mode false` | Allow players without official accounts (see Security) |
| `--new-world` | Move the current world to `backups/old-worlds/` and start fresh |

Everything the installer creates (`.env`, `server/`, `backups/`, `.venv/`) is
ignored by git, so updating is `git pull && ./install.sh`.

## Mods and plugins

List Modrinth project names (from `https://modrinth.com/mod/<name>`) in
`mods.txt` for Fabric or `plugins.txt` for Paper, then rerun `./install.sh`.
The first install creates these from `mods.example.txt` and
`plugins.example.txt`, which hold only server-side performance mods and
tools. Your lists are not tracked by git, so `git pull` never changes your
choices, and `backup.sh` includes them in each backup.
For each project it downloads the newest build for your Minecraft version,
checks its hash, and adds required dependencies. It stops with a list if any mod
has no build for that version. It skips client-only mods you list directly
(Sodium, shaders, minimaps) but always installs required dependencies, and removes mods it installed earlier that are no longer listed. Jars you add by
hand are left alone.

Players need Fabric and the same gameplay mods as the server. For Fabric,
`install.sh` also writes a player modpack, `server/client-pack.mrpack`, with the
exact versions the server runs, and the Discord bot shares it with `!mods`.
Players import it in the Modrinth App or Prism Launcher. The pack only lists
Modrinth download links and hashes, so it's a few KB and redistributes no mod files.

- **Required in the pack:** mods that run on both sides (blocks, items) and
  everything they depend on, such as Fabric API and libraries.
- **Optional:** client-only mods you list (Sodium) and mods tagged `client` in
  `mods.txt`, for example `jei client`.
- **Left out:** server-only mods and performance mods like Lithium.

Restart the server after changing mods: `sudo systemctl restart minecraft`.

## Discord

Create an application in the
[Discord Developer Portal](https://discord.com/developers/applications), add a
bot, enable **Message Content Intent**, and invite it with View Channels, Send
Messages, Read Message History and Attach Files (for the `!mods` pack).

| Command | Does |
|---|---|
| `!up` | Starts the server and reports when it is ready |
| `!status` | Online or offline, and who is playing |
| `!ip` | Connection address |
| `!mods` | Mods players need, with the modpack attached (Fabric) |
| `!help` | Command list |

Set `NOTIFICATION_CHANNEL_ID` in `.env` to post a message when the server shuts
down for inactivity, and `SERVER_ADDRESS` to show a hostname instead of the
public IP. Restart the manager afterwards: `sudo systemctl restart minecraft-manager`.

## Settings in `.env`

The installer owns `.env` but keeps your values. Besides the options above:

| Setting | Default | Purpose |
|---|---|---|
| `IDLE_TIMEOUT_MINUTES` | 30 | Minutes without players before shutdown |
| `AUTO_SHUTDOWN` | true | Set to false during long jobs such as pregeneration |
| `CHECK_INTERVAL_SECONDS` | 60 | How often the player count is checked |
| `BACKUP_KEEP` | 7 | Number of backups to keep |
| `NOTIFICATION_CHANNEL_ID` | | Discord channel for shutdown messages |
| `SERVER_ADDRESS` | | Hostname shown by `!ip` and `!status` |

Game settings (difficulty, MOTD, view distance) live in `server/server.properties`.
The installer only manages the port, RCON and online-mode lines there.

## Day to day

```bash
sudo systemctl start|stop|restart minecraft     # the server
systemctl status minecraft minecraft-manager    # what is running
journalctl -u minecraft -f                      # server console output
journalctl -u minecraft-manager -f              # bot and idle shutdown
.venv/bin/python -m minecraft_manager rcon list # run a console command
./backup.sh                                     # back up now
```

`systemctl stop minecraft` saves the world through the console before stopping.

### Restoring a backup

```bash
sudo systemctl stop minecraft
mv server/world server/world.broken
tar -xzf backups/world-YYYYMMDD-HHMMSS.tar.gz -C server
sudo systemctl start minecraft
```

## Performance on a Pi 5

- **Memory:** the server starts with a 1 GiB heap and can grow to `--memory`.
  On Paper this used about 1.5 GiB with a few players, where a fixed 3.5 GiB heap
  held 4 GiB from startup. Java 25's default garbage collector settings kept 20
  TPS; extra JVM flags were not needed.
- **New terrain is the expensive part.** Exploring ungenerated land caused
  multi-second stalls; pregenerated land did not. Before inviting players, run
  for example `chunky radius 1500` then `chunky start` from the console, with
  `AUTO_SHUTDOWN=false` until it finishes. Vanilla and Fabric pause an empty
  server after a minute; if pregeneration stalls, set
  `pause-when-empty-seconds=-1` in `server.properties` while it runs.
- **Profiling:** `spark` is in `mods.example.txt` and built into Paper. Use
  `/spark profiler` or `/spark tps` in game.
- Keep the Pi cool: it reports throttling with `vcgencmd get_throttled`.

## Security

- Forward only the Minecraft port on your router. RCON listens on the Pi and
  should never be forwarded.
- With `--online-mode false`, the server doesn't check accounts, so anyone can join
  with any username, including an operator's. Keep the operator list short, or
  use a whitelist or an authentication mod if the server is public.
