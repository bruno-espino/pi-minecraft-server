import json
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from minecraft_manager import metrics, server, web
from minecraft_manager.config import Config

DAY = 86400
# 2026-01-01 00:00 UTC
START = 1767225600


def write(root, path, text):
    path = Path(root) / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class FakeMachine:
    """A /proc and /sys tree under a temporary directory."""

    def __init__(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        write(self.root, "proc/loadavg", "0.52 0.40 0.30 1/200 1234\n")
        write(self.root, "proc/meminfo", "MemTotal: 8000000 kB\nMemFree: 1000000 kB\nMemAvailable: 6000000 kB\n")
        write(self.root, "sys/class/thermal/thermal_zone0/type", "cpu-thermal\n")
        write(self.root, "sys/class/thermal/thermal_zone0/temp", "61250\n")
        self.cpu(busy=1000, idle=9000)
        self.process(42, jiffies=100, rss_kb=2 * 1024 * 1024)

    def cpu(self, busy, idle):
        # user nice system idle iowait irq softirq steal guest guest_nice
        write(self.root, "proc/stat", f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 2 3 4\n")

    def process(self, pid, jiffies, rss_kb):
        fields = ["S"] + ["0"] * 10 + [str(jiffies), "0"] + ["0"] * 30
        write(self.root, f"proc/{pid}/stat", f"{pid} (java server) " + " ".join(fields) + "\n")
        write(self.root, f"proc/{pid}/status", f"Name:\tjava\nVmRSS:\t {rss_kb} kB\n")

    def sampler(self, throttled=None):
        return metrics.Sampler(root=self.root, disk=self.root, throttled=lambda: throttled)


class SamplerTests(unittest.TestCase):
    def setUp(self):
        self.machine = FakeMachine()
        self.addCleanup(self.machine.directory.cleanup)

    def test_first_sample_has_no_cpu_yet(self):
        row = self.machine.sampler().sample(now=START)
        self.assertNotIn("cpu", row)
        self.assertEqual(row["time"], START)
        self.assertEqual(row["load"], 0.52)
        self.assertEqual(row["mem_total"], 7812)
        self.assertEqual(row["mem_used"], 1953)  # total minus available
        self.assertEqual(row["temp"], 61.2)
        self.assertEqual(row["up"], 0)
        self.assertNotIn("throttled", row)

    def test_cpu_shares_between_samples(self):
        sampler = self.machine.sampler(throttled=4)
        sampler.sample(pid=42, now=START)
        self.machine.cpu(busy=1300, idle=9700)  # 300 busy of 1000 jiffies
        self.machine.process(42, jiffies=350, rss_kb=3 * 1024 * 1024)  # 250 of them Minecraft's
        row = sampler.sample(pid=42, now=START + 60)
        self.assertEqual(row["cpu"], 30.0)
        self.assertEqual(row["server_cpu"], 25.0)
        self.assertEqual(row["server_mem"], 3072)
        self.assertEqual(row["up"], 1)
        self.assertEqual(row["throttled"], 4)

    def test_a_new_server_process_starts_its_cpu_over(self):
        sampler = self.machine.sampler()
        sampler.sample(pid=42, now=START)
        self.machine.process(43, jiffies=10, rss_kb=1024)
        row = sampler.sample(pid=43, now=START + 60)
        self.assertNotIn("server_cpu", row)
        self.assertEqual(row["server_mem"], 1)

    def test_gone_process_is_skipped(self):
        row = self.machine.sampler().sample(pid=99, now=START)
        self.assertEqual(row["up"], 1)
        self.assertNotIn("server_mem", row)

    def test_clock_waits_for_timesyncd(self):
        root = self.machine.root
        self.assertTrue(metrics.clock_synchronized(root))  # no timesyncd: trust the clock
        (root / "run/systemd/timesync").mkdir(parents=True)
        self.assertFalse(metrics.clock_synchronized(root))
        (root / "run/systemd/timesync/synchronized").touch()
        self.assertTrue(metrics.clock_synchronized(root))


class TickTests(unittest.TestCase):
    def test_tick_query(self):
        reply = ("Average time per tick: 12.6ms (Target: 50.0ms)Percentiles: "
                 "P50: 10.3ms P95: 31.0ms P99: 48.0ms, sample: 100")
        self.assertEqual(server.parse_tick(reply), (12.6, 31.0))

    def test_paper_mspt(self):
        reply = "§6Server tick times §e(§7avg§e/§7min§e/§7max§e)§6 from last 5s§7,§6 10s§7,§6 1m§e:\n§6◴ §a1.2§7/§a0.4§7/§a3.1§e, §a1.3§7/§a0.4§7/§a5.0§e, §a1.1§7/§a0.3§7/§a9.8"
        self.assertEqual(server.parse_tick(reply), (1.1, None))

    def test_unknown(self):
        self.assertEqual(server.parse_tick("Unknown or incomplete command"), (None, None))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = metrics.Store(self.directory.name, keep_days=2)

    def test_rows_round_trip_across_days(self):
        self.store.append({"time": START - 60, "cpu": 10.0, "players": 1})
        self.store.append({"time": START + 60, "cpu": 20.5, "tick": 12.0})
        self.assertEqual([p.name for p in self.store.files()], ["2025-12-31.csv", "2026-01-01.csv"])
        rows = self.store.read(START - 3600)
        self.assertEqual(rows, [{"time": START - 60, "cpu": 10.0, "players": 1.0},
                                {"time": START + 60, "cpu": 20.5, "tick": 12.0}])
        self.assertEqual(self.store.read(START), rows[1:])
        self.assertEqual(self.store.read(START - 3600, until=START), rows[:1])

    def test_old_days_are_pruned(self):
        self.store.append({"time": START, "cpu": 1})
        self.store.append({"time": START + DAY, "cpu": 1})
        self.store.append({"time": START + 3 * DAY, "cpu": 1})
        self.assertEqual([p.stem for p in self.store.files()], ["2026-01-02", "2026-01-04"])


class DownsampleTests(unittest.TestCase):
    def test_keeps_peaks_and_averages_the_rest(self):
        rows = [{"time": START + i * 60, "cpu": float(i), "tick_p95": 200.0 if i == 7 else 10.0} for i in range(100)]
        columns = metrics.downsample(rows, points=10)
        self.assertEqual(len(columns["time"]), 10)
        self.assertEqual(columns["cpu"][0], 4.5)
        self.assertEqual(columns["tick_p95"][0], 200.0)
        self.assertEqual(columns["tick_p95"][1], 10.0)
        self.assertEqual(columns["players"], [None] * 10)

    def test_gaps_become_nulls(self):
        rows = [{"time": START, "cpu": 1.0}, {"time": START + 60, "cpu": 2.0}, {"time": START + 3600, "cpu": 3.0}]
        columns = metrics.downsample(rows)
        self.assertEqual(columns["cpu"], [1.0, 2.0, None, 3.0])

    def test_empty(self):
        self.assertEqual(metrics.downsample([])["time"], [])


class PrometheusTests(unittest.TestCase):
    def test_units_and_missing_values(self):
        text = metrics.prometheus(
            {"time": START, "cpu": 25.0, "mem_used": 1024, "disk_free": 419.4, "tick": 12.5, "players": 3}
        )
        self.assertIn("mcserver_disk_free_bytes 450327320986\n", text)
        self.assertIn("mcserver_cpu_ratio 0.25\n", text)
        self.assertIn("mcserver_memory_used_bytes 1073741824\n", text)
        self.assertIn("mcserver_tick_seconds 0.0125\n", text)
        self.assertIn("# TYPE mcserver_players gauge\nmcserver_players 3\n", text)
        self.assertIn(f"mcserver_sample_timestamp_seconds {START}\n", text)
        self.assertNotIn("temperature", text)

    def test_no_sample_yet(self):
        self.assertEqual(metrics.prometheus(None), "\n")


class SummaryTests(unittest.TestCase):
    def test_report(self):
        rows = [{"time": START + i * 60, "cpu": 20.0, "mem_used": 4096, "mem_total": 8192, "temp": 60.0 + i,
                 "throttled": 4 if i > 8 else 0, "up": 1, "server_cpu": 15.0, "server_mem": 3072,
                 "tick": 10.0, "tick_p95": 80.0 if i == 5 else 20.0, "players": 2 + (i == 5)} for i in range(10)]
        text = metrics.summary(rows, 24)
        self.assertIn("10 samples, server up 10 min", text)
        self.assertIn("average 20%, peak 20% (the server averaged 15% while running)", text)
        self.assertIn("peak 4.0 of 8.0 GiB in use; the server peaked at 3.0 GiB", text)
        self.assertIn("peak 69 °C", text)
        self.assertIn("throttled for 1 min", text)
        self.assertIn("average 10.0 ms with players online, worst 80 ms; 1 min above 50 ms", text)
        self.assertIn("Players      peak 3", text)
        self.assertIn("80 ms, 3 players", text)

    def test_nothing_recorded(self):
        self.assertIn("No samples", metrics.summary([], 6))


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        store = metrics.Store(self.directory.name)
        import time

        now = int(time.time())
        for i in range(5):
            store.append({"time": now - (5 - i) * 60, "cpu": 10.0 + i, "players": i})
        self.state = {"latest": {"time": now, "cpu": 12.0, "players": 4, "up": 1}}
        config = Config(rcon_password="x", minecraft_version="26.3", server_type="fabric")
        self.client = TestClient(TestServer(web.create_app(config, store, self.state)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_page_and_chart_library(self):
        page = await self.client.get("/")
        self.assertEqual(page.status, 200)
        self.assertIn("uPlot.iife.min.js", await page.text())
        self.assertEqual((await self.client.get("/uPlot.iife.min.js")).status, 200)
        self.assertEqual((await self.client.get("/metrics.py")).status, 404)

    async def test_series(self):
        response = await self.client.get("/api/series?hours=6")
        data = json.loads(await response.text())
        self.assertEqual(data["label"], "Minecraft 26.3 (Fabric)")
        self.assertEqual(data["series"]["cpu"], [10.0, 11.0, 12.0, 13.0, 14.0])
        self.assertEqual(data["latest"]["players"], 4)
        self.assertEqual((await self.client.get("/api/series?hours=x")).status, 400)

    async def test_prometheus(self):
        response = await self.client.get("/metrics")
        self.assertTrue(response.headers["Content-Type"].startswith("text/plain; version=0.0.4"))
        self.assertIn("mcserver_players 4\n", await response.text())


if __name__ == "__main__":
    unittest.main()
