#!/usr/bin/env python3
"""Tests for the tomedia:// join string."""

import os
import sys
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib.join import InvalidJoinString, Join, parse  # noqa: E402


class JoinTests(unittest.TestCase):
    def test_a_join_string_round_trips(self):
        join = Join(token="tok", hosts=["box"], port=7878, server_id="ab12")
        self.assertEqual(parse(str(join)), join)

    def test_several_hosts_round_trip(self):
        join = Join(token="tok", hosts=["box", "10.0.0.5"], port=7878, server_id="ab12")
        self.assertEqual(parse(str(join)).hosts, ["box", "10.0.0.5"])

    def test_the_server_id_is_optional(self):
        parsed = parse("tomedia://tok@box:7878")
        self.assertEqual(parsed, Join(token="tok", hosts=["box"], port=7878, server_id=""))

    def test_the_url_uses_the_first_host(self):
        join = Join(token="tok", hosts=["box", "10.0.0.5"], port=7878)
        self.assertEqual(join.url(), "http://box:7878")

    def test_not_a_join_string_at_all(self):
        with self.assertRaises(InvalidJoinString):
            parse("http://box:7878")

    def test_a_join_string_without_a_token_is_rejected(self):
        with self.assertRaises(InvalidJoinString):
            parse("tomedia://box:7878")

    def test_a_join_string_without_a_port_is_rejected(self):
        with self.assertRaises(InvalidJoinString):
            parse("tomedia://tok@box")


if __name__ == "__main__":
    unittest.main()
