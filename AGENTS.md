# pi-minecraft-server

Paper or Fabric Minecraft server for a Raspberry Pi 5 (8 GB), with a Discord
bot, idle shutdown and backups. It runs from a git checkout; `install.sh`
sets everything up from there.

## Layout

- `install.sh`: the only setup entry point; idempotent, settings persist in `.env`
- `backup.sh`: world backup with retention, run nightly by `minecraft-backup.timer`
- `minecraft_manager/`: one Python process (`python -m minecraft_manager`)
  - `app.py` idle-shutdown loop; `bot.py` Discord commands; `server.py` systemd/RCON helpers
  - `idle.py` pure idle logic using `time.monotonic()` (the Pi has no RTC battery, so the wall clock jumps at boot)
  - `provision.py` stdlib-only downloads for `install.sh` (Paper, Fabric, Modrinth, Mojang Java version)
    and the player pack (`server/client-pack.mrpack`, `server/client-mods.json`) used by `!mods`
- `templates/`: systemd units and `start.sh`; `__USER__`/`__DIR__` are filled in by `install.sh`
- `mods.example.txt` / `plugins.example.txt`: shared defaults (performance mods and tools only)
- Generated and ignored: `.env`, `server/`, `backups/`, `.venv/`, and the local
  `mods.txt` / `plugins.txt` each install edits (never commit them)

## Rules

- Keep it one server per checkout; multi-instance support was removed on purpose.
- Stop the server through RCON `stop` (`ExecStop`); vanilla/Fabric do not reliably save on signals.
- Keep `--online-mode false` working: groups without official accounts rely on it.
- Keep the repo neutral, like any open-source project: no deployment logs, server
  names, personal mod lists, player names or dates in files or commit messages.
  Per-install notes stay in untracked files (e.g. a local `STATUS.md`).
- Never print `.env` or `server/server.properties`: they hold the Discord token and RCON password.
- The Pi runs Python 3.11; keep the code compatible.

## Checks

```bash
uv run python -m unittest discover -s tests -v
bash -n install.sh backup.sh
```

On the Pi, test changes in a throwaway checkout with `--no-services` and other
ports (`--port 25566 --rcon-port 25576`) before touching the live services.
