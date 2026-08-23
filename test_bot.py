#!/usr/bin/env python3
"""Small dependency-free tests for Discord bot helpers."""

import os
import runpy
import unittest

os.environ.setdefault('DISCORD_TOKEN', 'test')
os.environ.setdefault('RCON_PASSWORD', 'test')

BOT = runpy.run_path(
    os.path.join(os.path.dirname(__file__), 'discord-bot', 'bot.py'),
    run_name='bot_tests'
)
parse_player_list = BOT['parse_player_list']


class PlayerListTests(unittest.TestCase):
    def test_empty_new_format(self):
        self.assertEqual(
            parse_player_list('There are 0 of a max of 10 players online: '),
            (0, '')
        )

    def test_names_new_format(self):
        self.assertEqual(
            parse_player_list('There are 2 of a max of 10 players online: Alex, Sam'),
            (2, 'Alex, Sam')
        )

    def test_names_plugin_multiline_format(self):
        self.assertEqual(
            parse_player_list(
                'There are 1 out of maximum 10 players online.\ndefault: Alex'
            ),
            (1, 'Alex')
        )

    def test_unrecognized_response(self):
        self.assertEqual(parse_player_list('Server is starting'), (-1, ''))


if __name__ == '__main__':
    unittest.main()
