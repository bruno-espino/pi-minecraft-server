"""The long-running manager: idle shutdown, plus Discord control when configured."""

import asyncio
import time

from . import server
from .idle import IdleTracker


def log(message):
    print(message, flush=True)


async def watch_idle(config, notify=None):
    """Stop the server after IDLE_TIMEOUT_MINUTES with nobody online."""
    tracker = IdleTracker(config.idle_timeout_minutes * 60)
    last_state = None
    while True:
        try:
            running = await asyncio.to_thread(server.is_running)
            players = await asyncio.to_thread(server.get_players, config) if running else None
            count = players.count if players else None
            state = (running, count)
            if state != last_state:
                log(f"server {'running' if running else 'stopped'}, players: {'?' if count is None else count}")
                last_state = state
            if tracker.observe(running, count, time.monotonic()) and config.auto_shutdown:
                log(f"no players for {config.idle_timeout_minutes} minutes; stopping the server")
                stopped = await asyncio.to_thread(server.stop_for_inactivity, config)
                tracker.reset()
                log("server stopped" if stopped else "server did not stop")
                if stopped and notify:
                    await notify(
                        f"**Server shut down** after {config.idle_timeout_minutes} minutes "
                        "without players. Use `!up` to start it again."
                    )
        except Exception as error:  # keep watching whatever happens
            log(f"idle check failed: {type(error).__name__}: {error}")
        await asyncio.sleep(config.check_interval_seconds)


def run(config):
    if not config.discord_token:
        log("DISCORD_TOKEN not set; running idle shutdown only")
        asyncio.run(watch_idle(config))
        return
    from .bot import create_bot  # discord.py is only needed with a token

    create_bot(config).run(config.discord_token)
