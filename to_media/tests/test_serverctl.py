#!/usr/bin/env python3
"""Tests for server/worker/jobs/status/cancel/retry command wiring, and the
--queue prompts, against a real (subprocess) background server."""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib import cli, queueclient, serverctl  # noqa: E402
from to_medialib.config import config_dir, load_config, save_config  # noqa: E402
from to_medialib.daemon import status as daemon_status  # noqa: E402
from to_medialib.jobs import Job  # noqa: E402
from to_medialib.runner import Policy  # noqa: E402


def has_ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


class ConfigIsolatedTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "config")
        self.saved_env = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.home
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.saved_env is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.saved_env

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def call(self, *argv, prog="to_media"):
        out = io.StringIO()
        saved = sys.stderr
        sys.stderr = err = io.StringIO()
        try:
            code = cli.main(list(argv), prog=prog, out=out)
        finally:
            sys.stderr = saved
        return code, out.getvalue(), err.getvalue()


class ServerLifecycleTests(ConfigIsolatedTestCase):
    def stop_server(self):
        self.call("server", "--stop")

    def test_server_starts_in_the_background_and_can_be_stopped(self):
        code, out, err = self.call("server", "--advertise", "127.0.0.1")
        self.addCleanup(self.stop_server)
        self.assertEqual(code, 0, err)
        self.assertIn("started in the background", out)
        self.assertIn("tomedia://", out)
        pidfile = os.path.join(config_dir(), "server.pid")
        self.assertIsNotNone(daemon_status(pidfile))

        code, out, _ = self.call("server", "--status")
        self.assertEqual(code, 0)
        self.assertIn("running", out)

        code, out, _ = self.call("server", "--stop")
        self.assertEqual(code, 0)
        self.assertIsNone(daemon_status(pidfile))

    def test_starting_again_while_running_does_not_spawn_a_second_one(self):
        self.call("server", "--advertise", "127.0.0.1")
        self.addCleanup(self.stop_server)
        pidfile = os.path.join(config_dir(), "server.pid")
        first_pid = daemon_status(pidfile)
        code, out, _ = self.call("server", "--advertise", "127.0.0.1")
        self.assertEqual(code, 0)
        self.assertIn("already running", out)
        self.assertEqual(daemon_status(pidfile), first_pid)

    def test_join_info_prints_the_join_string(self):
        self.call("server", "--advertise", "127.0.0.1")
        self.addCleanup(self.stop_server)
        code, out, _ = self.call("server", "--join-info")
        self.assertEqual(code, 0)
        self.assertIn("tomedia://", out)

    def test_new_token_changes_the_join_string(self):
        self.call("server", "--advertise", "127.0.0.1")
        self.addCleanup(self.stop_server)
        _, before, _ = self.call("server", "--join-info")
        self.call("server", "--new-token")
        _, after, _ = self.call("server", "--join-info")
        self.assertNotEqual(before, after)

class ServerNotRunningTests(ConfigIsolatedTestCase):
    def test_stopping_when_nothing_is_running_says_so(self):
        code, out, _ = self.call("server", "--stop")
        self.assertEqual(code, 0)
        self.assertIn("stopped", out)

    def test_status_when_nothing_is_running(self):
        code, out, _ = self.call("server", "--status")
        self.assertEqual(code, 1)
        self.assertIn("not running", out)


class WorkerJoinTests(ConfigIsolatedTestCase):
    def test_worker_with_no_join_and_nothing_remembered_explains_itself(self):
        code, out, err = self.call("worker")
        self.assertEqual(code, 2)
        self.assertIn("join string", err)

    def test_worker_status_when_nothing_is_running(self):
        code, out, _ = self.call("worker", "--status")
        self.assertEqual(code, 1)
        self.assertIn("not running", out)


class JobsStatusClientTests(ConfigIsolatedTestCase):
    def stop_server(self):
        self.call("server", "--stop")

    def setUp(self):
        super().setUp()
        code, out, err = self.call("server", "--advertise", "127.0.0.1")
        self.assertEqual(code, 0, err)
        self.addCleanup(self.stop_server)
        parser = load_config()
        self.join = serverctl.join_string(parser["server"])
        from to_medialib.client import Client
        self.client = Client(self.join.url(), token=self.join.token)

    def test_jobs_and_status_with_no_server_remembered_locally(self):
        # this test's config already has a server remembered by setUp
        code, out, err = self.call("jobs")
        self.assertEqual(code, 0, err)

    def test_a_submitted_batch_shows_up_in_jobs_and_status(self):
        job = Job("mp3", ["/in/a.flac"], "/out/a.mp3", {}).to_dict()
        self.client.submit("mp3", [{"job": job, "policy": Policy().to_dict()}], label="mine")
        code, out, err = self.call("jobs")
        self.assertEqual(code, 0, err)
        self.assertIn("a.mp3", out)
        code, out, err = self.call("status")
        self.assertEqual(code, 0, err)
        self.assertIn("mine", out)

    def test_cancel_and_retry_a_batch_through_the_cli(self):
        job = Job("mp3", ["/in/a.flac"], "/out/a.mp3", {}).to_dict()
        batch = self.client.submit("mp3", [{"job": job, "policy": Policy().to_dict()}])
        code, out, err = self.call("cancel", "--batch", str(batch))
        self.assertEqual(code, 0, err)
        self.assertIn("cancelled 1", out)
        code, out, err = self.call("retry", "--batch", str(batch))
        self.assertEqual(code, 0, err)
        self.assertIn("retried 1", out)


class QueueResolveTests(ConfigIsolatedTestCase):
    def test_choosing_to_cancel_gives_up_cleanly(self):
        out, err = io.StringIO(), io.StringIO()
        client = queueclient.resolve_queue_client(ask=lambda prompt: "3", out=out, err=err)
        self.assertIsNone(client)
        self.assertIn("start a server", out.getvalue())

    def test_starting_a_server_from_the_prompt_works(self):
        out, err = io.StringIO(), io.StringIO()
        answers = iter(["1", "1"])  # choose "start a server", then advertise "hostname"
        client = queueclient.resolve_queue_client(ask=lambda prompt: next(answers), out=out, err=err)
        self.addCleanup(lambda: self.call("server", "--stop"))
        self.assertIsNotNone(client)
        self.assertEqual(client.health()["ok"], True)

    def test_pasting_a_join_string_works(self):
        code, _, _ = self.call("server", "--advertise", "127.0.0.1")
        self.assertEqual(code, 0)
        self.addCleanup(lambda: self.call("server", "--stop"))
        real_join = serverctl.join_string(load_config()["server"])
        # forget the remembered server so resolve_queue_client has to prompt
        parser = load_config()
        parser.remove_section("client")
        save_config(parser)

        out, err = io.StringIO(), io.StringIO()
        answers = iter(["2", str(real_join)])
        client = queueclient.resolve_queue_client(ask=lambda prompt: next(answers), out=out, err=err)
        self.assertIsNotNone(client)
        self.assertEqual(client.health()["ok"], True)


@unittest.skipUnless(has_ffmpeg(), "ffmpeg/ffprobe not installed")
class QueueSubmitTests(ConfigIsolatedTestCase):
    def test_queue_submits_and_follow_reports_completion(self):
        code, _, err = self.call("server", "--advertise", "127.0.0.1")
        self.assertEqual(code, 0, err)
        self.addCleanup(lambda: self.call("server", "--stop"))

        wav = self.path("in.wav")
        os.makedirs(self.tmp, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", wav],
                      check=True)
        code, out, err = self.call("mp3", "--queue", wav, "-o", self.tmp)
        self.assertEqual(code, 0, err)
        self.assertIn("queued as batch", out)

        parser = load_config()
        client_join = serverctl.join_string(parser["server"])
        from to_medialib.client import Client
        from to_medialib.worker import run_forever
        client = Client(client_join.url(), token=client_join.token)
        stop_after = {"n": 0}
        run_forever(client, wid="w1", capabilities=["mp3"], stop=lambda: (stop_after.__setitem__(
            "n", stop_after["n"] + 1) or stop_after["n"] > 5), sleep=lambda s: None)
        self.assertTrue(os.path.exists(self.path("in.mp3")))


if __name__ == "__main__":
    unittest.main()
