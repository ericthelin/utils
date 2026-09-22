#!/usr/bin/env python3
"""Tests for the worker: claiming jobs from a real (in-process) server and
running real ffmpeg conversions, including cancellation."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib import recipes  # noqa: E402
from to_medialib.client import Client  # noqa: E402
from to_medialib.jobs import Job  # noqa: E402
from to_medialib.runner import Policy  # noqa: E402
from to_medialib.server import Server  # noqa: E402
from to_medialib.worker import run_claimed, run_forever  # noqa: E402


class SlowRecipe:
    """A fake recipe that reports progress in slow, real-time steps, so a
    test can reliably cancel it while it is "running"."""
    name = "slow"

    def run(self, job, tmp_output, progress=None):
        with open(tmp_output, "w") as handle:
            handle.write("partial")
        for step in range(1, 21):
            time.sleep(0.1)
            if progress:
                progress(step / 20)
        return []


def has_ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


@unittest.skipUnless(has_ffmpeg(), "ffmpeg/ffprobe not installed")
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.server = Server(os.path.join(self.tmp, "jobs.db"), host="127.0.0.1", port=0, token="tok")
        self.server.start()
        self.addCleanup(self.server.stop)
        self.client = Client(f"http://127.0.0.1:{self.server.port}", token="tok")
        self.wav = os.path.join(self.tmp, "in.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        self.wav], check=True)

    def submit_mp3(self, name="out"):
        output = os.path.join(self.tmp, f"{name}.mp3")
        job = Job("mp3", [self.wav], output, {}).to_dict()
        batch = self.client.submit("mp3", [{"job": job, "policy": Policy().to_dict()}])
        return batch, output

    def test_a_claimed_job_is_converted_and_reported_done(self):
        _, output = self.submit_mp3()
        jobs = self.client.claim("w1", ["mp3"])
        self.assertEqual(len(jobs), 1)
        status = run_claimed(self.client, jobs[0], "w1", Policy())
        self.assertEqual(status, "done")
        self.assertTrue(os.path.exists(output))
        self.assertEqual(self.client.job(jobs[0]["id"])["state"], "done")

    def test_an_unknown_recipe_fails_cleanly(self):
        job = Job("nonsense", [self.wav], os.path.join(self.tmp, "x.mp3"), {}).to_dict()
        batch = self.client.submit("nonsense", [{"job": job, "policy": {}}], max_attempts=1)
        jobs = self.client.claim("w1", ["nonsense"])
        self.assertEqual(run_claimed(self.client, jobs[0], "w1", Policy()), "failed")
        self.assertEqual(self.client.job(jobs[0]["id"])["state"], "failed")

    def test_run_forever_processes_a_whole_batch_then_stops(self):
        payloads = [{"job": Job("mp3", [self.wav], os.path.join(self.tmp, f"batch{i}.mp3"), {}).to_dict(),
                    "policy": Policy().to_dict()} for i in range(3)]
        batch = self.client.submit("mp3", payloads)
        stop_after = {"n": 0}

        def stop():
            stop_after["n"] += 1
            return stop_after["n"] > 20

        run_forever(self.client, wid="w1", capabilities=["mp3"], slots=2, stop=stop, sleep=lambda s: None)
        counts = self.client.batch(batch)["counts"]
        self.assertEqual(counts["done"], 3)

    def test_cancelling_a_running_job_stops_the_worker(self):
        output = os.path.join(self.tmp, "long.out")
        job = Job("slow", [self.wav], output, {}).to_dict()
        self.client.submit("slow", [{"job": job, "policy": Policy().to_dict()}])
        job_row = self.client.claim("w1", ["slow"])[0]

        result = {}

        def worker():
            with mock.patch.object(recipes, "get", return_value=SlowRecipe()):
                result["status"] = run_claimed(self.client, job_row, "w1", Policy())

        with mock.patch("to_medialib.worker.HEARTBEAT_INTERVAL", 0.05):
            thread = threading.Thread(target=worker)
            thread.start()
            for _ in range(50):
                if self.client.job(job_row["id"])["progress"] > 0:
                    break
                time.sleep(0.05)
            self.client.cancel(job_id=job_row["id"])
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.client.job(job_row["id"])["state"], "cancelled")
        self.assertFalse(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()
