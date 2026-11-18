import unittest

from minecraft_manager.config import Config
from minecraft_manager.idle import IdleTracker
from minecraft_manager.server import Players, parse_player_list

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


if __name__ == "__main__":
    unittest.main()
