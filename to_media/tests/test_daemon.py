#!/usr/bin/env python3
"""Tests for daemon.py: background start/stop/status via pidfiles."""

import os
import shutil
import sys
import tempfile
import time
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib import daemon  # noqa: E402


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pidfile = os.path.join(self.tmp, "sub", "thing.pid")

    def test_nothing_is_running_before_anything_starts(self):
        self.assertIsNone(daemon.status(self.pidfile))

    def test_a_missing_pidfile_stops_cleanly(self):
        self.assertTrue(daemon.stop(self.pidfile))

    def test_spawn_writes_a_pidfile_for_a_live_process(self):
        pid = daemon.spawn_background(["sleep", "5"], self.pidfile)
        self.addCleanup(lambda: daemon.stop(self.pidfile))
        self.assertEqual(daemon.read_pid(self.pidfile), pid)
        self.assertEqual(daemon.status(self.pidfile), pid)

    def test_stop_kills_the_process_and_removes_the_pidfile(self):
        daemon.spawn_background(["sleep", "30"], self.pidfile)
        self.assertTrue(daemon.stop(self.pidfile, timeout=5))
        self.assertFalse(os.path.exists(self.pidfile))

    def test_spawn_writes_the_log_where_asked(self):
        log = os.path.join(self.tmp, "out.log")
        daemon.spawn_background(["sh", "-c", "echo hello"], self.pidfile, log_path=log)
        self.addCleanup(lambda: daemon.stop(self.pidfile))
        for _ in range(20):
            if os.path.exists(log) and os.path.getsize(log):
                break
            time.sleep(0.1)
        with open(log) as handle:
            self.assertIn("hello", handle.read())

    def test_a_stale_pid_reports_not_running(self):
        os.makedirs(os.path.dirname(self.pidfile), exist_ok=True)
        with open(self.pidfile, "w") as handle:
            handle.write("999999999")
        self.assertIsNone(daemon.status(self.pidfile))


if __name__ == "__main__":
    unittest.main()
