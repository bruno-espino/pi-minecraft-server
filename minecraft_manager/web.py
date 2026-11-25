"""The monitoring page (charts of the recorded metrics) and /metrics for scrapers."""

import asyncio
from pathlib import Path
import time

from aiohttp import web

from . import metrics

WEB_DIR = Path(__file__).resolve().parent / "web"
FILES = {"/": "index.html", "/uPlot.iife.min.js": "uPlot.iife.min.js", "/uPlot.min.css": "uPlot.min.css"}
PROMETHEUS_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def create_app(config, store, state):
    app = web.Application()

    def static(name):
        async def handler(request):
            return web.FileResponse(WEB_DIR / name, headers={"Cache-Control": "no-cache"})

        return handler

    async def series(request):
        try:
            hours = float(request.query.get("hours", 24))
        except ValueError:
            raise web.HTTPBadRequest(text="hours must be a number")
        hours = min(max(hours, 1), store.keep_days * 24)
        now = time.time()
        rows = await asyncio.to_thread(store.read, now - hours * 3600)
        return web.json_response({
            "label": config.server_label,
            "now": int(now),
            "hours": hours,
            "latest": state.get("latest") or (rows[-1] if rows else None),
            "series": metrics.downsample(rows),
        })

    async def prometheus(request):
        return web.Response(body=metrics.prometheus(state.get("latest")).encode(), headers={"Content-Type": PROMETHEUS_TYPE})

    for path, name in FILES.items():
        app.router.add_get(path, static(name))
    app.router.add_get("/api/series", series)
    app.router.add_get("/metrics", prometheus)
    return app


async def serve(config, store, state):
    """Start the page on MONITOR_PORT (all interfaces); log and carry on if the port is taken."""
    runner = web.AppRunner(create_app(config, store, state), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, port=config.monitor_port).start()
    except OSError as error:
        metrics.log(f"monitoring page unavailable on port {config.monitor_port}: {error}")
        return None
    metrics.log(f"monitoring page on port {config.monitor_port}")
    return runner
