from pathlib import Path
import tempfile
import unittest
from unittest import mock

from minecraft_manager import server

from minecraft_manager.config import Config
from minecraft_manager.idle import IdleTracker
from minecraft_manager.server import Players, format_mods_message, parse_player_list

MINUTE = 60


class IdleTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = IdleTracker(30 * MINUTE)

    def test_stops_after_timeout_with_nobody_online(self):
        self.assertFalse(self.tracker.observe(True, 0, now=0))
        self.assertFalse(self.tracker.observe(True, 0, now=29 * MINUTE))
        self.assertTrue(self.tracker.observe(True, 0, now=30 * MINUTE))

    def test_players_restart_the_idle_window(self):
        self.tracker.observe(True, 0, now=0)
        self.tracker.observe(True, 2, now=20 * MINUTE)
        self.assertFalse(self.tracker.observe(True, 0, now=45 * MINUTE))
        self.assertTrue(self.tracker.observe(True, 0, now=50 * MINUTE))

    def test_unknown_player_count_never_stops(self):
        self.tracker.observe(True, None, now=0)
        self.assertFalse(self.tracker.observe(True, None, now=60 * MINUTE))
        # ...but the time it was starting up still counts once RCON answers.
        self.assertTrue(self.tracker.observe(True, 0, now=61 * MINUTE))

    def test_stopped_server_resets(self):
        self.tracker.observe(True, 0, now=0)
        self.tracker.observe(False, None, now=10 * MINUTE)
        self.assertFalse(self.tracker.observe(True, 0, now=35 * MINUTE))
        self.assertTrue(self.tracker.observe(True, 0, now=65 * MINUTE))

    def test_starting_at_boot_still_times_out(self):
        # The window starts when the manager first sees the server, so a
        # server started at boot is stopped 30 minutes later if nobody joins.
        self.assertFalse(self.tracker.observe(True, 0, now=1000))
        self.assertTrue(self.tracker.observe(True, 0, now=1000 + 30 * MINUTE))


class PlayerListTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_player_list("There are 0 of a max of 10 players online: "), Players(0, []))

    def test_names_inline(self):
        self.assertEqual(
            parse_player_list("There are 2 of a max of 10 players online: Alex, Sam"),
            Players(2, ["Alex", "Sam"]),
        )

    def test_names_on_group_lines(self):
        self.assertEqual(
            parse_player_list("There are 1 out of maximum 10 players online.\ndefault: Alex"),
            Players(1, ["Alex"]),
        )

    def test_formatting_codes(self):
        self.assertEqual(
            parse_player_list("§6There are §c1§6 of a max of §c10§6 players online: §fAlex"),
            Players(1, ["Alex"]),
        )

    def test_unrecognised(self):
        self.assertIsNone(parse_player_list("Unknown command"))
        self.assertIsNone(parse_player_list(""))


class ModsMessageTests(unittest.TestCase):
    SUMMARY = {
        "minecraft": "26.3", "loader": "0.20.1",
        "required": [{"title": "Fabric API", "url": "https://modrinth.com/mod/fabric-api", "version": "1"}],
        "optional": [],
    }

    def config(self, server_type):
        return Config.from_env({"RCON_PASSWORD": "x", "SERVER_TYPE": server_type, "MINECRAFT_VERSION": "26.3"})

    def test_paper_needs_no_mods(self):
        self.assertIn("needs no mods", format_mods_message(self.config("paper"), None))

    def test_fabric_lists_mods_with_links(self):
        text = format_mods_message(self.config("fabric"), self.SUMMARY)
        self.assertIn("**Required:** [Fabric API](<https://modrinth.com/mod/fabric-api>)", text)
        self.assertIn("**Optional:** none", text)
        self.assertIn("Fabric Loader 0.20.1", text)

    def test_long_lists_drop_links_and_fit_discord(self):
        many = dict(self.SUMMARY, required=[
            {"title": f"Mod {n}", "url": f"https://modrinth.com/mod/mod-{n}", "version": "1"} for n in range(60)
        ])
        text = format_mods_message(self.config("fabric"), many)
        self.assertLessEqual(len(text), 1900)
        self.assertNotIn("https://", text.split("**Required:**")[1])

    def test_missing_summary(self):
        self.assertIn("rerun ./install.sh", format_mods_message(self.config("fabric"), None))


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = Config.from_env({"RCON_PASSWORD": "secret"})
        self.assertEqual(config.rcon_port, 25575)
        self.assertIsNone(config.notification_channel_id)
        self.assertTrue(config.auto_shutdown)
        self.assertEqual(config.server_label, "Minecraft unknown (Paper)")

    def test_values(self):
        config = Config.from_env({
            "RCON_PASSWORD": "secret",
            "SERVER_TYPE": "fabric",
            "MINECRAFT_VERSION": "26.3",
            "NOTIFICATION_CHANNEL_ID": "123",
            "AUTO_SHUTDOWN": "false",
        })
        self.assertEqual(config.server_label, "Minecraft 26.3 (Fabric)")
        self.assertEqual(config.notification_channel_id, 123)
        self.assertFalse(config.auto_shutdown)

    def test_password_required(self):
        with self.assertRaises(SystemExit):
            Config.from_env({})


class PregenTests(unittest.TestCase):
    config = Config(rcon_password="secret")

    def check(self, reply):
        with tempfile.TemporaryDirectory() as tmp:
            hold = Path(tmp) / ".pregen"
            hold.touch()
            rcon = mock.MagicMock()
            rcon.__enter__.return_value.command.return_value = reply
            with mock.patch.object(server, "RCONClient", return_value=rcon):
                return server.pregen_running(self.config, hold), hold.exists()

    def test_running_task_keeps_the_hold(self):
        self.assertEqual(self.check("[Chunky] Task running for minecraft:overworld. Processed: 10 chunks"),
                         (True, True))

    def test_finished_task_clears_the_hold(self):
        self.assertEqual(self.check("[Chunky] No tasks running."), (False, False))

    def test_no_hold_means_no_pregeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(server.pregen_running(self.config, Path(tmp) / ".pregen"))


if __name__ == "__main__":
    unittest.main()
