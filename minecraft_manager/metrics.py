"""Machine and server metrics for the monitoring page and `mcserver stats`.

Once a minute the manager records CPU, memory, disk, temperature, the server's
own CPU and memory, tick time and players. Samples go to one CSV file per day
(UTC) in metrics/, kept for 30 days. The web page charts them, and /metrics
serves the latest sample in the Prometheus text format for Telegraf,
Prometheus, Grafana Agent or Netdata.
"""

import asyncio
import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import shutil
import subprocess
import time

CHECKOUT = Path(__file__).resolve().parent.parent
METRICS_DIR = CHECKOUT / "metrics"
KEEP_DAYS = 30
INTERVAL_SECONDS = 60
FIELDS = [
    "time", "cpu", "load", "mem_used", "mem_total", "disk_free", "temp", "throttled",
    "up", "server_cpu", "server_mem", "tick", "tick_p95", "players",
]
# Downsampling keeps the maximum of these instead of the mean, so spikes stay visible.
PEAK_FIELDS = {"temp", "throttled", "up", "tick_p95", "players"}
MIB, GIB = 2**20, 2**30
# Prometheus metric for each field: (name, help, multiplier to base units).
PROMETHEUS = {
    "cpu": ("mcserver_cpu_ratio", "Machine CPU use, 0 to 1", 0.01),
    "load": ("mcserver_load1", "Load average over 1 minute", 1),
    "mem_used": ("mcserver_memory_used_bytes", "Memory in use (total minus available)", MIB),
    "mem_total": ("mcserver_memory_total_bytes", "Installed memory", MIB),
    "disk_free": ("mcserver_disk_free_bytes", "Free space on the server's disk", GIB),
    "temp": ("mcserver_temperature_celsius", "CPU temperature", 1),
    "throttled": (
        "mcserver_throttled_flags",
        "Raspberry Pi throttling now: 1 under-voltage, 2 frequency capped, 4 throttled, 8 soft temperature limit",
        1,
    ),
    "up": ("mcserver_server_up", "1 while the Minecraft server runs", 1),
    "server_cpu": ("mcserver_server_cpu_ratio", "Minecraft's share of the machine's CPU, 0 to 1", 0.01),
    "server_mem": ("mcserver_server_memory_bytes", "Memory used by the Minecraft process", MIB),
    "tick": ("mcserver_tick_seconds", "Average time per tick; the game slows down above 0.05", 0.001),
    "tick_p95": ("mcserver_tick_p95_seconds", "95th percentile time per tick", 0.001),
    "players": ("mcserver_players", "Players online", 1),
}
THERMAL_TYPES = ("cpu-thermal", "cpu_thermal", "x86_pkg_temp", "soc_thermal")


def log(message):
    print(message, flush=True)


def read_throttled():
    """Current Raspberry Pi throttling flags (the low bits of get_throttled), or None elsewhere."""
    if not shutil.which("vcgencmd"):
        return None
    try:
        result = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5)
        return int(result.stdout.strip().partition("=")[2], 16) & 0xF
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def clock_synchronized(root=Path("/")):
    """False until systemd-timesyncd sets the clock after boot (a Pi has no clock battery)."""
    state = Path(root) / "run/systemd/timesync"
    return not state.is_dir() or (state / "synchronized").exists()


class Sampler:
    """Reads /proc and /sys; CPU percentages compare with the previous call."""

    def __init__(self, root=Path("/"), disk=CHECKOUT, throttled=read_throttled):
        self.root = Path(root)
        self.disk = disk
        self.read_throttled = throttled
        self._cpu = None  # (busy, total) jiffies
        self._process = None  # (pid, process jiffies, total jiffies)

    def _read(self, path):
        return (self.root / path).read_text()

    def cpu_times(self):
        values = [int(v) for v in self._read("proc/stat").splitlines()[0].split()[1:9]]
        total = sum(values)  # user nice system idle iowait irq softirq steal
        return total - values[3] - values[4], total

    def temperature(self):
        chosen = None
        for zone in sorted((self.root / "sys/class/thermal").glob("thermal_zone*")):
            try:
                kind = (zone / "type").read_text().strip()
            except OSError:
                continue
            chosen = chosen or zone
            if kind in THERMAL_TYPES:
                chosen = zone
                break
        try:
            return round(int((chosen / "temp").read_text()) / 1000, 1) if chosen else None
        except (OSError, ValueError):
            return None

    def process(self, pid, total):
        """(CPU % of the machine since the last sample, resident MiB) for pid."""
        try:
            fields = self._read(f"proc/{pid}/stat").rpartition(")")[2].split()
            jiffies = int(fields[11]) + int(fields[12])  # utime + stime
            status = self._read(f"proc/{pid}/status")
        except (OSError, IndexError, ValueError):
            self._process = None
            return None, None
        rss = next((int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")), None)
        cpu = None
        if self._process and self._process[0] == pid and total > self._process[2]:
            cpu = round(100 * (jiffies - self._process[1]) / (total - self._process[2]), 1)
        self._process = (pid, jiffies, total)
        return cpu, round(rss / 1024) if rss is not None else None

    def sample(self, pid=None, now=None):
        row = {"time": int(time.time() if now is None else now)}
        busy, total = self.cpu_times()
        if self._cpu and total > self._cpu[1]:
            row["cpu"] = round(100 * (busy - self._cpu[0]) / (total - self._cpu[1]), 1)
        self._cpu = (busy, total)
        row["load"] = float(self._read("proc/loadavg").split()[0])
        memory = {}
        for line in self._read("proc/meminfo").splitlines():
            key, _, value = line.partition(":")
            memory[key] = int(value.split()[0]) if value.split() else 0
        row["mem_total"] = round(memory["MemTotal"] / 1024)
        row["mem_used"] = round((memory["MemTotal"] - memory.get("MemAvailable", memory["MemFree"])) / 1024)
        try:
            row["disk_free"] = round(shutil.disk_usage(self.disk).free / GIB, 1)
        except OSError:
            pass
        row["temp"] = self.temperature()
        row["throttled"] = self.read_throttled()
        row["up"] = int(pid is not None)
        if pid is not None:
            row["server_cpu"], row["server_mem"] = self.process(pid, total)
        return {key: value for key, value in row.items() if value is not None}


def _day(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")


class Store:
    """Samples as one CSV file per UTC day, pruned after keep_days."""

    def __init__(self, directory=METRICS_DIR, keep_days=KEEP_DAYS):
        self.directory = Path(directory)
        self.keep_days = keep_days

    def files(self):
        return sorted(self.directory.glob("????-??-??.csv"))

    def append(self, row):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{_day(row['time'])}.csv"
        new = not path.exists()
        with path.open("a", newline="") as file:
            writer = csv.DictWriter(file, FIELDS, extrasaction="ignore")
            if new:
                writer.writeheader()
            writer.writerow(row)
        if new:
            self.prune(row["time"])

    def prune(self, now):
        cutoff = _day(now - self.keep_days * 86400)
        for path in self.files():
            if path.stem < cutoff:
                path.unlink(missing_ok=True)

    def read(self, since, until=None):
        """Samples from since to until (Unix seconds), oldest first."""
        first, rows = _day(since), []
        for path in self.files():
            if path.stem < first:
                continue
            try:
                with path.open(newline="") as file:
                    for record in csv.DictReader(file):
                        row = {}
                        for key, value in record.items():
                            if key in FIELDS and value:
                                try:
                                    row[key] = float(value)
                                except ValueError:
                                    pass
                        if "time" in row and row["time"] >= since and (until is None or row["time"] <= until):
                            row["time"] = int(row["time"])
                            rows.append(row)
            except OSError:
                continue
        rows.sort(key=lambda row: row["time"])
        return rows


def downsample(rows, points=800, interval=INTERVAL_SECONDS):
    """Chart columns with at most about `points` buckets.

    Buckets average most fields but keep the maximum of PEAK_FIELDS. A missing
    stretch (the manager or the machine was off) becomes a null, so charts show
    a gap rather than a line across it.
    """
    columns = {field: [] for field in FIELDS}
    if not rows:
        return columns
    start = rows[0]["time"]
    width = max(interval, math.ceil((rows[-1]["time"] - start + 1) / points))
    buckets = {}
    for row in rows:
        buckets.setdefault((row["time"] - start) // width, []).append(row)
    previous = None
    for key in sorted(buckets):
        if previous is not None and key - previous > 1 and width * (key - previous) > 3 * interval:
            for field in FIELDS:
                columns[field].append(start + (previous + 1) * width if field == "time" else None)
        previous = key
        group = buckets[key]
        columns["time"].append(group[0]["time"])
        for field in FIELDS[1:]:
            values = [row[field] for row in group if field in row]
            if not values:
                columns[field].append(None)
            elif field in PEAK_FIELDS:
                columns[field].append(round(max(values), 1))
            else:
                columns[field].append(round(sum(values) / len(values), 1))
    return columns


def _number(value):
    return str(int(value)) if float(value).is_integer() else f"{value:.6g}"


def prometheus(row):
    """The sample in the Prometheus text exposition format."""
    lines = []
    for field, (name, description, scale) in PROMETHEUS.items():
        if row and field in row:
            lines += [f"# HELP {name} {description}", f"# TYPE {name} gauge", f"{name} {_number(row[field] * scale)}"]
    if row:
        lines += [
            "# HELP mcserver_sample_timestamp_seconds When these values were measured",
            "# TYPE mcserver_sample_timestamp_seconds gauge",
            f"mcserver_sample_timestamp_seconds {row['time']}",
        ]
    return "\n".join(lines) + "\n"


def _when(timestamp):
    return time.strftime("%a %H:%M", time.localtime(timestamp))


def _duration(minutes):
    hours, minutes = divmod(round(minutes), 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes} min"


def summary(rows, hours, interval=INTERVAL_SECONDS):
    """Text report for `mcserver stats`."""
    if not rows:
        return f"No samples in the last {hours:g} hours (monitoring records one per minute while the manager runs)."

    def values(field, where=None):
        return [row[field] for row in rows if field in row and (where is None or where(row))]

    per_minute = interval / 60
    up = values("up", lambda row: row["up"] > 0)
    lines = [f"Last {hours:g} hours: {len(rows)} samples, server up {_duration(len(up) * per_minute)}"]
    cpu, server_cpu = values("cpu"), values("server_cpu")
    if cpu:
        text = f"average {sum(cpu) / len(cpu):.0f}%, peak {max(cpu):.0f}%"
        if server_cpu:
            text += f" (the server averaged {sum(server_cpu) / len(server_cpu):.0f}% while running)"
        lines.append(f"{'CPU':12} {text}")
    used, total, server_mem = values("mem_used"), values("mem_total"), values("server_mem")
    if used:
        text = f"peak {max(used) / 1024:.1f} of {max(total) / 1024:.1f} GiB in use"
        if server_mem:
            text += f"; the server peaked at {max(server_mem) / 1024:.1f} GiB"
        lines.append(f"{'Memory':12} {text}")
    temp = values("temp")
    if temp:
        hottest = max((row for row in rows if "temp" in row), key=lambda row: row["temp"])
        text = f"average {sum(temp) / len(temp):.0f} °C, peak {hottest['temp']:.0f} °C ({_when(hottest['time'])})"
        throttled = values("throttled", lambda row: row["throttled"] > 0)
        if throttled:
            text += f"; throttled for {_duration(len(throttled) * per_minute)}"
        lines.append(f"{'Temperature':12} {text}")
    played = [row for row in rows if row.get("players", 0) > 0 and "tick" in row]
    if played:
        ticks = [row["tick"] for row in played]
        worst = [row.get("tick_p95", row["tick"]) for row in played]
        slow = sum(1 for value in worst if value > 50)
        lines.append(
            f"{'Tick':12} average {sum(ticks) / len(ticks):.1f} ms with players online, worst {max(worst):.0f} ms; "
            f"{_duration(slow * per_minute)} above 50 ms"
        )
    players = values("players")
    if players:
        busiest = max((row for row in rows if "players" in row), key=lambda row: (row["players"], row["time"]))
        lines.append(f"{'Players':12} peak {busiest['players']:.0f} ({_when(busiest['time'])})")
    if played:
        slowest = sorted(played, key=lambda row: row.get("tick_p95", row["tick"]), reverse=True)[:5]
        slowest = [row for row in slowest if row.get("tick_p95", row["tick"]) > 50]
        if slowest:
            lines.append(
                f"{'Slowest':12} "
                + ", ".join(
                    f"{_when(row['time'])} ({row.get('tick_p95', row['tick']):.0f} ms, {row['players']:.0f} players)"
                    for row in slowest
                )
            )
    return "\n".join(lines)


async def monitor(config, store=None, sampler=None, state=None):
    """Record a sample every minute and serve the monitoring page; runs forever."""
    from . import server, web

    store = store or Store()
    sampler = sampler or Sampler()
    state = {} if state is None else state
    await web.serve(config, store, state)
    await asyncio.to_thread(sampler.sample)  # the first CPU figures need a previous reading
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        try:
            if not clock_synchronized():
                continue
            pid = await asyncio.to_thread(server.main_pid)
            row = await asyncio.to_thread(sampler.sample, pid)
            if pid is not None:
                players, tick, p95 = await asyncio.to_thread(server.server_stats, config)
                row.update({key: value for key, value in (("players", players), ("tick", tick), ("tick_p95", p95))
                            if value is not None})
            await asyncio.to_thread(store.append, row)
            state["latest"] = row
        except Exception as error:  # keep recording whatever happens
            log(f"metrics sample failed: {type(error).__name__}: {error}")
