# Minecraft Server for Raspberry Pi

A Paper or Fabric Minecraft server for a Raspberry Pi 5 or any small Debian or
Ubuntu machine, with a Discord bot to start it, automatic shutdown when nobody
is playing, and nightly backups.

- `install.sh` installs or updates everything, including Java, and can be rerun safely
- Paper (plugins) or Fabric (mods) from Modrinth, plus a modpack for players
- Discord: `!up`, `!status`, `!ip`, `!mods`, `!help`, plus a message when the server shuts down
- Shuts down after 30 minutes without players; starts again after a power cut
- Nightly backups that skip unchanged worlds and keep the newest seven
- `mcserver` for status, console, restore, pregeneration and updates

## Requirements

- A 64-bit Raspberry Pi OS, Debian 12+ or Ubuntu 22.04+ with systemd
- 4 GB of RAM or more for mods (2 GB is enough for Paper); an SSD is better than an SD card
- Optional: a Discord bot token

The installer adds `python3-venv` if it is missing and downloads Java (Eclipse
Temurin, into `java/`) unless a new enough one is installed. Tested on a
Raspberry Pi 5 with Raspberry Pi OS (Debian 12), and on x86-64 Debian 12,
Debian 13 and Ubuntu 24.04.

## Install

```bash
sudo apt install -y git
git clone https://github.com/bruno-espino/pi-minecraft-server.git
cd pi-minecraft-server
./install.sh
mcserver start
```

The first run asks a few questions (Paper or Fabric, memory, accounts, world
type, Discord) with defaults, shows a summary, and then:

1. writes `.env` (mode 600) with every setting, so later runs keep them
2. downloads Java if needed, the server jar and the mods or plugins
3. creates `server/` with `server.properties`, `start.sh` and the world
4. installs three systemd units: `minecraft`, `minecraft-manager` (bot and idle
   shutdown) and `minecraft-backup.timer`, a sudo rule that lets the manager
   start and stop `minecraft`, and the `mcserver` command

Options skip their question, `--yes` skips them all, and `--guided` asks them
again on a later run. Run `./install.sh --help` for all options. Useful ones:

| Option | Purpose |
|---|---|
| `--server paper\|fabric` | Server software |
| `--version 26.3` | Minecraft version |
| `--memory 4096` | Maximum Java heap in MiB; `auto` (default) uses half the RAM, up to 8 GiB |
| `--online-mode false` | Allow players without official accounts (see Security) |
| `--whitelist on\|off` | Only let listed players join; new installs start with it off |
| `--world-type normal` | World type for a new world: `normal`, `large-biomes`, `amplified`, `flat`, or a mod's type |
| `--new-world` | Move the current world to `backups/old-worlds/` and start fresh |
| `--update-mods` | Move mods or plugins to their newest builds |

The world type is fixed when a world is created, so pick it before the first
start (or together with `--new-world`). Some world-generation mods need their
own type: BetterEnd and BetterNether only generate their terrain in a world made
with `--world-type wover:normal`, whose overworld is the vanilla one, so they
combine with overworld mods such as Terralith. The installer suggests it when
they are in `mods.txt`.

Everything the installer creates (`.env`, `server/`, `backups/`, `java/`,
`.venv/`) is ignored by git, so `mcserver update` (`git pull` and a rerun)
never touches your settings.

## Day to day

| Command | Does |
|---|---|
| `mcserver status` | Players, tick time, memory, disk, backups, temperature |
| `mcserver start\|stop\|restart` | Stopping saves the world first |
| `mcserver console` | Server console, e.g. `op NAME`, `whitelist add NAME` |
| `mcserver cmd COMMAND` | Run one console command |
| `mcserver logs` | Follow the server log |
| `mcserver backup`, `backups` | Back up now; list backups |
| `mcserver restore [BACKUP]` | Restore a backup (default: the newest); the current world moves to `backups/old-worlds/` |
| `mcserver pregen 3000 [nether\|end]` | Generate terrain ahead of play (see Performance) |
| `mcserver update [--mods]` | Update this project, the server and Java; `--mods` also updates mods |

## Mods and plugins

List Modrinth project names (from `https://modrinth.com/mod/<name>`) in
`mods.txt` for Fabric or `plugins.txt` for Paper, then rerun `./install.sh`
and `mcserver restart`. The first install creates these from
`mods.example.txt` and `plugins.example.txt`, which hold only server-side
performance mods and tools. Your lists are not tracked by git, and `backup.sh`
includes them in each backup.

For each project it downloads the newest build for your Minecraft version,
checks its hash, and adds required dependencies. It stops with a list if any mod
has no build for that version. It skips client-only mods you list directly
(Sodium, shaders, minimaps) but always installs required dependencies, and
removes mods it installed earlier that are no longer listed. Jars you add by
hand are left alone.

The exact versions are saved in `mods.lock` (or `plugins.lock`), so later runs
and updates keep them, and players' packs keep working. A mod you add gets its
newest build; `--update-mods` (or `mcserver update --mods`) moves everything to
the newest builds, as does a new Minecraft version.

Players need Fabric and the same gameplay mods as the server. For Fabric,
`install.sh` also writes a player modpack, `server/client-pack.mrpack`, with the
exact versions the server runs, and the Discord bot shares it with `!mods`.
Players import it in the Modrinth App or Prism Launcher, and again whenever mods
change. The pack only lists Modrinth download links and hashes, so it's a few
KB and redistributes no mod files.

- **Required in the pack:** mods that run on both sides (blocks, items) and
  everything they depend on, such as Fabric API and libraries.
- **Optional:** client-only mods you list (Sodium) and mods tagged `client` in
  `mods.txt`, for example `jei client`. The tag also makes a mod optional when
  Modrinth marks it required on clients, such as a minimap.
- **Left out:** server-only mods and performance mods like Lithium.

Bedrock players (phones, consoles) can join through
[Geyser](https://geysermc.org) (`geyser` in the list, UDP port 19132); see its
documentation.

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
down for inactivity or finishes pregenerating, and `SERVER_ADDRESS` to show a
hostname instead of the public IP. Restart the manager afterwards:
`sudo systemctl restart minecraft-manager`.

## Settings in `.env`

The installer owns `.env` but keeps your values. Besides the options above:

| Setting | Default | Purpose |
|---|---|---|
| `IDLE_TIMEOUT_MINUTES` | 30 | Minutes without players before shutdown |
| `AUTO_SHUTDOWN` | true | Set to false to keep the server running |
| `CHECK_INTERVAL_SECONDS` | 60 | How often the player count is checked |
| `BACKUP_KEEP` | 7 | Number of backups to keep |
| `NOTIFICATION_CHANNEL_ID` | | Discord channel for shutdown messages |
| `SERVER_ADDRESS` | | Hostname shown by `!ip` and `!status` |

Game settings (difficulty, MOTD, view distance) live in `server/server.properties`.
The installer only manages the port, RCON, online-mode, whitelist and world-type lines there.

## Playing from outside your network

Players on your network connect to the address `mcserver status` shows. For
others, forward TCP port 25565 on your router to the machine, or use a tunnel
such as [playit.gg](https://playit.gg) if you can't (for example behind CGNAT).

## Performance on a Pi 5

- **New terrain is the expensive part.** Exploring ungenerated land causes
  multi-second stalls; pregenerated land does not. Before inviting players, run
  `mcserver pregen 3000` (about 40 minutes); idle shutdown waits for it.
- **Lag:** `mcserver status` shows the tick time (above 50 ms the game slows
  down); lowering `simulation-distance` (6 by default) to 4 helps most. Use
  `/spark profiler` in game to find the cause.
- **Memory:** the server starts with a 1 GiB heap and grows up to `--memory`.
  Java 25's default garbage collector settings keep 20 TPS; extra JVM flags
  are not needed.
- **Keep the Pi cool:** it slows down from about 80 °C, and `mcserver status`
  reports throttling and under-voltage.

## Security

- Forward only the Minecraft port on your router. RCON listens on the machine
  and should never be forwarded.
- With `--online-mode false`, the server doesn't check accounts, so anyone can join
  with any username, including an operator's. Keep the operator list short, or
  use a whitelist or an authentication mod if the server is public.
- Whitelist from the console, no restart needed: `mcserver cmd whitelist add NAME`,
  then `mcserver cmd whitelist on`.

## Uninstall

```bash
sudo systemctl disable --now minecraft minecraft-manager minecraft-backup.timer
sudo rm /etc/systemd/system/minecraft{,-manager,-backup}.service \
    /etc/systemd/system/minecraft-backup.timer /etc/sudoers.d/minecraft /usr/local/bin/mcserver
```

Then delete the checkout (keep `backups/` if you want your worlds).

## License

[MIT](LICENSE)
