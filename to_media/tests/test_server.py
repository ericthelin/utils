#!/usr/bin/env python3
"""Tests for the job server's HTTP API and status page."""

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib.server import Server  # noqa: E402


def payload(name="a"):
    return {"job": {"recipe": "mp3", "inputs": [f"/in/{name}.flac"], "output": f"/out/{name}.mp3", "options": {}},
            "policy": {}}


class ServerTestCase(unittest.TestCase):
    token = "s3cret"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.server = Server(os.path.join(self.tmp, "jobs.db"), host="127.0.0.1", port=0, token=self.token)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f"http://127.0.0.1:{self.server.port}"

    def call(self, method, path, body=None, token="s3cret", raw=False):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                text = resp.read()
                return resp.status, (text if raw else json.loads(text))
        except urllib.error.HTTPError as error:
            text = error.read()
            return error.code, (text if raw else json.loads(text))


class AuthTests(ServerTestCase):
    def test_a_request_without_the_token_is_rejected(self):
        status, data = self.call("GET", "/batches", token=None)
        self.assertEqual((status, data["error"]), (401, "unauthorized"))

    def test_a_request_with_the_wrong_token_is_rejected(self):
        status, _ = self.call("GET", "/batches", token="nope")
        self.assertEqual(status, 401)

    def test_health_needs_no_token(self):
        status, data = self.call("GET", "/health", token=None)
        self.assertEqual((status, data["ok"]), (200, True))

    def test_the_status_page_accepts_the_token_in_the_query_string(self):
        status, body = self.call("GET", f"/status?token={self.token}", token=None, raw=True)
        self.assertEqual(status, 200)
        self.assertIn(b"to_media server", body)

    def test_the_status_page_still_needs_a_token(self):
        status, _ = self.call("GET", "/status", token=None, raw=True)
        self.assertEqual(status, 401)

    def test_a_server_with_no_token_configured_needs_none(self):
        server = Server(os.path.join(self.tmp, "open.db"), host="127.0.0.1", port=0, token=None)
        server.start()
        self.addCleanup(server.stop)
        req = urllib.request.Request(f"http://127.0.0.1:{server.port}/batches")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)


class ApiTests(ServerTestCase):
    def submit(self, count=2, **kwargs):
        status, data = self.call("POST", "/batches",
                                 {"recipe": "mp3", "payloads": [payload(f"f{i}") for i in range(count)], **kwargs})
        self.assertEqual(status, 200)
        return data["batch"]

    def test_submitting_a_batch_needs_a_recipe_and_payloads(self):
        status, data = self.call("POST", "/batches", {"recipe": "mp3", "payloads": []})
        self.assertEqual(status, 400)
        self.assertIn("payloads", data["error"])

    def test_the_full_life_of_a_job(self):
        batch = self.submit(1)
        status, data = self.call("POST", "/claims", {"worker": "w1", "recipes": ["mp3"]})
        self.assertEqual(status, 200)
        job = data["jobs"][0]
        self.assertEqual(job["state"], "running")

        status, data = self.call("POST", f"/jobs/{job['id']}/heartbeat", {"worker": "w1", "progress": 0.5})
        self.assertEqual((status, data["cancel"]), (200, False))

        status, data = self.call("POST", f"/jobs/{job['id']}/complete", {"worker": "w1", "status": "done"})
        self.assertEqual((status, data["ok"]), (200, True))

        status, data = self.call("GET", f"/jobs/{job['id']}")
        self.assertEqual((status, data["state"]), (200, "done"))

        status, data = self.call("GET", f"/batches/{batch}")
        self.assertTrue(data["complete"])

    def test_completing_with_the_wrong_worker_is_a_conflict(self):
        self.submit(1)
        _, data = self.call("POST", "/claims", {"worker": "w1", "recipes": ["mp3"]})
        job_id = data["jobs"][0]["id"]
        status, data = self.call("POST", f"/jobs/{job_id}/complete", {"worker": "thief", "status": "done"})
        self.assertEqual((status, data["error"]), (409, "this worker no longer holds that job"))

    def test_heartbeat_reports_a_pending_cancel(self):
        self.submit(1)
        _, data = self.call("POST", "/claims", {"worker": "w1", "recipes": ["mp3"]})
        job_id = data["jobs"][0]["id"]
        self.call("POST", f"/jobs/{job_id}/cancel")
        status, data = self.call("POST", f"/jobs/{job_id}/heartbeat", {"worker": "w1", "progress": 0.1})
        self.assertEqual(data["cancel"], True)

    def test_claim_reports_the_recipe_it_asked_for(self):
        self.submit(1)
        status, data = self.call("POST", "/claims", {"worker": "w1", "recipes": ["h264"]})
        self.assertEqual((status, data["jobs"]), (200, []))

    def test_listing_jobs_can_filter_by_state_and_batch(self):
        first = self.submit(2)
        second = self.submit(1)
        status, data = self.call("GET", f"/jobs?batch={second}")
        self.assertEqual(len(data["jobs"]), 1)
        status, data = self.call("GET", "/jobs?state=queued")
        self.assertEqual(len(data["jobs"]), 3)

    def test_a_missing_job_or_batch_is_404(self):
        status, data = self.call("GET", "/jobs/999")
        self.assertEqual((status, data["error"]), (404, "no such job"))
        status, data = self.call("GET", "/batches/999")
        self.assertEqual(status, 404)

    def test_cancel_and_retry_a_whole_batch(self):
        batch = self.submit(3)
        status, data = self.call("POST", f"/batches/{batch}/cancel")
        self.assertEqual((status, data["cancelled"]), (200, 3))
        status, data = self.call("POST", f"/batches/{batch}/retry")
        self.assertEqual((status, data["retried"]), (200, 3))

    def test_workers_show_up_after_claiming(self):
        self.submit(1)
        self.call("POST", "/claims", {"worker": "box#1", "recipes": ["mp3"], "info": {"host": "box"}})
        status, data = self.call("GET", "/workers")
        self.assertEqual(status, 200)
        self.assertEqual(data["workers"][0]["id"], "box#1")
        self.assertEqual(data["workers"][0]["info"]["host"], "box")

    def test_an_unknown_route_is_404(self):
        status, data = self.call("GET", "/nonsense")
        self.assertEqual((status, data["error"]), (404, "no such route"))

    def test_bad_json_body_is_400(self):
        req = urllib.request.Request(self.base + "/batches", data=b"not json", method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            urllib.request.urlopen(req)
            self.fail("expected an HTTPError")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)


class ReaperTests(unittest.TestCase):
    def test_the_reaper_requeues_a_lease_that_expired(self):
        clock = {"t": 1000.0}
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        server = Server(os.path.join(tmp, "jobs.db"), host="127.0.0.1", port=0, token=None,
                        clock=lambda: clock["t"])
        server.start()
        self.addCleanup(server.stop)
        server.store.add_batch("mp3", [payload("a")])
        server.store.claim("gone", ["mp3"])
        clock["t"] += 120
        reaped = server.store.reap()
        self.assertEqual(reaped, 1)
        self.assertEqual(server.store.job(1)["state"], "queued")


if __name__ == "__main__":
    unittest.main()
