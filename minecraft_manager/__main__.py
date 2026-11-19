"""Entry point.

    python -m minecraft_manager             run the manager (systemd runs this)
    python -m minecraft_manager rcon CMD    run one console command, e.g. `rcon list`
    python -m minecraft_manager console     type console commands interactively
    python -m minecraft_manager stop [PID]  stop the server cleanly (systemd ExecStop)
"""

import os
from pathlib import Path
import sys

from .config import Config

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path=ENV_FILE):
    """Fill missing variables from the installer's .env (systemd already loads it)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def stop_and_wait(config, pid, timeout=110):
    """systemd ExecStop: save and stop through RCON, then wait for the process.

    Vanilla and Fabric servers do not reliably log or save on SIGINT/SIGTERM,
    so a clean `stop` is preferred; systemd still signals the process if this
    returns while it is running.
    """
    import time

    from .rcon import RCONClient, RCONError

    try:
        with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password) as rcon:
            rcon.command("stop")
    except RCONError as error:
        print(f"RCON stop failed: {error}")
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and Path(f"/proc/{pid}").exists():
        time.sleep(1)


def console(config):
    """A small interactive console over RCON (`mcserver console`)."""
    from .rcon import RCONClient, RCONError, strip_formatting

    try:
        import readline  # noqa: F401  (line editing and history for input())
    except ImportError:
        pass
    try:
        with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password) as rcon:
            print("Server console. Type commands without the slash; Ctrl-D or `exit` leaves.")
            while True:
                try:
                    line = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if line in ("exit", "quit"):
                    return
                if line:
                    reply = strip_formatting(rcon.command(line.removeprefix("/")))
                    if reply.strip():
                        print(reply.rstrip())
    except RCONError as error:
        raise SystemExit(f"console unavailable: {error}") from error


def main(argv):
    load_env_file()
    config = Config.from_env()
    if argv[:1] == ["rcon"] and len(argv) > 1:
        from .rcon import RCONClient, RCONError, strip_formatting

        try:
            with RCONClient("127.0.0.1", config.rcon_port, config.rcon_password) as rcon:
                print(strip_formatting(rcon.command(" ".join(argv[1:]))))
        except RCONError as error:
            raise SystemExit(str(error)) from error
        return
    if argv == ["console"]:
        console(config)
        return
    if argv[:1] == ["stop"] and len(argv) <= 2:
        # systemd also runs ExecStop after the server exited by itself; then
        # there is no MAINPID and nothing to do.
        if len(argv) == 2:
            stop_and_wait(config, int(argv[1]))
        return
    if argv:
        raise SystemExit(__doc__)
    from .app import run

    run(config)


if __name__ == "__main__":
    main(sys.argv[1:])
