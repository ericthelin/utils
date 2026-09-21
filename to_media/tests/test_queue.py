#!/usr/bin/env python3
"""Tests for the job queue, server, worker and client of to_media.

Run directly (python3 tests/test_queue.py) or via tests/run_tests.sh.
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib.store import LEASE_SECONDS, Store  # noqa: E402


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def payload(name="a", recipe="mp3"):
    return {"job": {"recipe": recipe, "inputs": [f"/in/{name}.flac"], "output": f"/out/{name}.mp3", "options": {}},
            "policy": {"force": False, "replace": False, "preserve_times": True}}


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.clock = FakeClock()
        self.store = Store(os.path.join(self.tmp, "jobs.db"), clock=self.clock)
        self.addCleanup(self.store.close)

    def batch(self, count=3, recipe="mp3", **kwargs):
        return self.store.add_batch(recipe, [payload(f"f{i}", recipe) for i in range(count)], **kwargs)


class QueueTests(StoreTestCase):
    def test_a_new_batch_is_queued(self):
        batch = self.batch(3)
        counts = self.store.counts(batch)
        self.assertEqual((counts["queued"], counts["running"], counts["done"]), (3, 0, 0))
        self.assertEqual(self.store.batch(batch)["total"], 3)

    def test_claims_come_in_order_and_never_repeat(self):
        self.batch(3)
        first = self.store.claim("w1", ["mp3"])
        second = self.store.claim("w2", ["mp3"])
        self.assertEqual([j["id"] for j in first + second], [1, 2])
        self.assertEqual(first[0]["state"], "running")
        self.assertEqual((first[0]["worker"], first[0]["attempts"]), ("w1", 1))
        self.assertEqual(first[0]["lease_expires"], self.clock.now + LEASE_SECONDS)

    def test_higher_priority_jobs_go_first(self):
        self.batch(2)
        self.batch(1, priority=5)
        self.assertEqual(self.store.claim("w", ["mp3"])[0]["id"], 3)

    def test_a_worker_only_gets_recipes_it_can_run(self):
        self.batch(1, recipe="h264")
        self.assertEqual(self.store.claim("w", ["mp3", "jpg"]), [])
        self.assertEqual(len(self.store.claim("w", ["h264"])), 1)
        self.assertEqual(self.store.claim("w", []), [])

    def test_a_worker_can_claim_several_small_jobs_at_once(self):
        self.batch(5)
        self.assertEqual([j["id"] for j in self.store.claim("w", ["mp3"], limit=3)], [1, 2, 3])
        self.assertEqual(len(self.store.claim("w2", ["mp3"], limit=10)), 2)

    def test_the_payload_comes_back_as_data(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.assertEqual(job["payload"]["job"]["output"], "/out/f0.mp3")

    def test_heartbeat_renews_the_lease_and_records_progress(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.clock.advance(30)
        self.assertEqual(self.store.heartbeat(job["id"], "w", 0.4), {"cancel": False})
        row = self.store.job(job["id"])
        self.assertEqual(row["progress"], 0.4)
        self.assertEqual(row["lease_expires"], self.clock.now + LEASE_SECONDS)

    def test_progress_is_clamped_and_only_the_holder_may_report(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.store.heartbeat(job["id"], "w", 7)
        self.assertEqual(self.store.job(job["id"])["progress"], 1.0)
        self.assertIsNone(self.store.heartbeat(job["id"], "someone-else", 0.5))

    def test_completing_a_job_records_the_result(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.assertTrue(self.store.complete(job["id"], "w", "done", "", "note: x"))
        row = self.store.job(job["id"])
        self.assertEqual((row["state"], row["progress"], row["notes"]), ("done", 1.0, "note: x"))
        self.assertIsNone(row["worker"])
        self.assertFalse(self.store.complete(job["id"], "w", "done"), "a finished job cannot be completed twice")

    def test_only_the_holder_can_complete(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.assertFalse(self.store.complete(job["id"], "thief", "done"))
        self.assertEqual(self.store.job(job["id"])["state"], "running")

    def test_skipped_counts_as_finished(self):
        batch = self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.store.complete(job["id"], "w", "skipped", "output exists")
        self.assertEqual(self.store.batch(batch)["complete"], True)

    def test_a_failure_is_retried_until_the_attempts_run_out(self):
        self.batch(1)
        for attempt in (1, 2):
            job = self.store.claim("w", ["mp3"])[0]
            self.assertEqual(job["attempts"], attempt)
            self.store.complete(job["id"], "w", "failed", "boom")
            self.assertEqual(self.store.job(job["id"])["state"], "queued")
        job = self.store.claim("w", ["mp3"])[0]
        self.store.complete(job["id"], "w", "failed", "boom")
        row = self.store.job(job["id"])
        self.assertEqual((row["state"], row["detail"]), ("failed", "boom"))

    def test_a_released_job_goes_back_without_using_an_attempt(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.store.complete(job["id"], "w", "released")
        row = self.store.job(job["id"])
        self.assertEqual((row["state"], row["attempts"]), ("queued", 0))


class LeaseTests(StoreTestCase):
    def test_a_silent_worker_loses_its_job(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.clock.advance(LEASE_SECONDS - 1)
        self.assertEqual(self.store.reap(), 0)
        self.clock.advance(2)
        self.assertEqual(self.store.reap(), 1)
        row = self.store.job(job["id"])
        self.assertEqual((row["state"], row["worker"], row["detail"]), ("queued", None, "the worker stopped responding"))
        self.assertFalse(self.store.complete(job["id"], "w", "done"), "the old worker's late result is refused")

    def test_a_heartbeat_keeps_the_lease_alive(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        for _ in range(5):
            self.clock.advance(LEASE_SECONDS - 5)
            self.store.heartbeat(job["id"], "w", 0.5)
            self.assertEqual(self.store.reap(), 0)

    def test_a_job_that_keeps_losing_its_worker_eventually_fails(self):
        self.batch(1, max_attempts=2)
        for _ in range(2):
            self.store.claim("w", ["mp3"])
            self.clock.advance(LEASE_SECONDS + 1)
            self.store.reap()
        row = self.store.job(1)
        self.assertEqual(row["state"], "failed")
        self.assertIn("too many times", row["detail"])

    def test_the_new_holder_can_finish_a_job_after_the_first_worker_vanished(self):
        self.batch(1)
        self.store.claim("old", ["mp3"])
        self.clock.advance(LEASE_SECONDS + 1)
        self.store.reap()
        job = self.store.claim("new", ["mp3"])[0]
        self.assertTrue(self.store.complete(job["id"], "new", "done"))


class ManagementTests(StoreTestCase):
    def test_cancelling_queued_jobs_is_immediate(self):
        batch = self.batch(3)
        self.assertEqual(self.store.cancel(batch_id=batch), 3)
        self.assertEqual(self.store.counts(batch)["cancelled"], 3)
        self.assertEqual(self.store.claim("w", ["mp3"]), [])

    def test_cancelling_a_running_job_asks_the_worker_to_stop(self):
        self.batch(1)
        job = self.store.claim("w", ["mp3"])[0]
        self.assertEqual(self.store.cancel(job_ids=[job["id"]]), 1)
        self.assertEqual(self.store.heartbeat(job["id"], "w", 0.3), {"cancel": True})
        self.store.complete(job["id"], "w", "failed", "cancelled")
        self.assertEqual(self.store.job(job["id"])["state"], "cancelled")

    def test_cancel_can_target_single_jobs(self):
        self.batch(3)
        self.store.cancel(job_ids=[2])
        self.assertEqual([j["id"] for j in self.store.jobs(states=["cancelled"])], [2])

    def test_retry_requeues_failed_and_cancelled_jobs_only(self):
        batch = self.batch(3, max_attempts=1)
        first, second = self.store.claim("w", ["mp3"], limit=2)
        self.store.complete(first["id"], "w", "failed", "boom")
        self.store.complete(second["id"], "w", "done")
        self.store.cancel(job_ids=[3])
        self.assertEqual(self.store.retry(batch_id=batch), 2)
        counts = self.store.counts(batch)
        self.assertEqual((counts["queued"], counts["done"], counts["failed"], counts["cancelled"]), (2, 1, 0, 0))
        self.assertEqual(self.store.job(first["id"])["attempts"], 0)

    def test_batch_progress_includes_jobs_still_running(self):
        batch = self.batch(4)
        jobs = self.store.claim("w", ["mp3"], limit=2)
        self.store.complete(jobs[0]["id"], "w", "done")
        self.store.heartbeat(jobs[1]["id"], "w", 0.5)
        summary = self.store.batch(batch)
        self.assertAlmostEqual(summary["progress"], (1 + 0.5) / 4)
        self.assertFalse(summary["complete"])

    def test_the_time_left_is_estimated_from_progress_so_far(self):
        batch = self.batch(4)
        jobs = self.store.claim("w", ["mp3"], limit=4)
        self.clock.advance(100)
        for job in jobs[:2]:
            self.store.complete(job["id"], "w", "done")
        summary = self.store.batch(batch)
        self.assertEqual(summary["progress"], 0.5)
        self.assertAlmostEqual(summary["eta"], 100.0)

    def test_no_estimate_before_any_progress(self):
        batch = self.batch(2)
        self.assertIsNone(self.store.batch(batch)["eta"])
        self.store.claim("w", ["mp3"])
        self.assertIsNone(self.store.batch(batch)["eta"])

    def test_listing_filters_by_state_and_batch_and_pages(self):
        first, second = self.batch(3), self.batch(2)
        self.assertEqual([j["id"] for j in self.store.jobs(batch_id=second)], [4, 5])
        self.assertEqual(len(self.store.jobs(states=["queued"])), 5)
        self.assertEqual([j["id"] for j in self.store.jobs(limit=2, offset=2)], [3, 4])
        self.assertEqual(len(self.store.batches()), 2)
        self.assertEqual(self.store.batches()[0]["id"], second)

    def test_unknown_batch(self):
        self.assertIsNone(self.store.batch(99))
        self.assertIsNone(self.store.job(99))


class WorkerRegistryTests(StoreTestCase):
    def test_workers_are_listed_while_recent_and_show_what_they_run(self):
        self.batch(1)
        self.store.touch_worker("box#1", {"host": "box", "recipes": ["mp3"]})
        self.store.touch_worker("old#1", {"host": "old"})
        self.clock.advance(400)
        self.store.touch_worker("box#1", {"host": "box", "recipes": ["mp3"]})
        job = self.store.claim("box#1", ["mp3"])[0]
        listing = self.store.workers()
        self.assertEqual([w["id"] for w in listing], ["box#1"])
        self.assertEqual(listing[0]["job"], job["id"])
        self.assertEqual(listing[0]["info"]["recipes"], ["mp3"])


class DurabilityTests(unittest.TestCase):
    def test_the_queue_survives_a_restart(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "jobs.db")
        store = Store(path)
        batch = store.add_batch("mp3", [payload("a"), payload("b")])
        store.claim("w", ["mp3"])
        store.close()
        again = Store(path)
        self.addCleanup(again.close)
        counts = again.counts(batch)
        self.assertEqual((counts["queued"], counts["running"]), (1, 1))

    def test_many_threads_never_receive_the_same_job(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        store = Store(os.path.join(tmp, "jobs.db"))
        self.addCleanup(store.close)
        store.add_batch("mp3", [payload(f"f{i}") for i in range(200)])
        got, lock = [], threading.Lock()

        def work(name):
            while True:
                jobs = store.claim(name, ["mp3"], limit=3)
                if not jobs:
                    return
                with lock:
                    got.extend(j["id"] for j in jobs)

        threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(got), list(range(1, 201)))


if __name__ == "__main__":
    unittest.main()
