#!/usr/bin/env python3
"""Tests for TLS: certificate generation, fingerprint pinning end to end."""

import os
import shutil
import sys
import tempfile
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib import tls  # noqa: E402
from to_medialib.client import Client, FingerprintMismatch, Unreachable  # noqa: E402
from to_medialib.server import Server  # noqa: E402


def has_openssl():
    return shutil.which("openssl") is not None


@unittest.skipUnless(has_openssl(), "openssl not installed")
class CertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cert = os.path.join(self.tmp, "server.crt")
        self.key = os.path.join(self.tmp, "server.key")

    def test_a_certificate_and_key_are_created(self):
        tls.ensure_cert(self.cert, self.key)
        self.assertTrue(os.path.exists(self.cert))
        self.assertTrue(os.path.exists(self.key))

    def test_the_key_is_private(self):
        tls.ensure_cert(self.cert, self.key)
        self.assertEqual(os.stat(self.key).st_mode & 0o777, 0o600)

    def test_an_existing_certificate_is_kept(self):
        first = tls.ensure_cert(self.cert, self.key)
        with open(self.key) as handle:
            key_text = handle.read()
        second = tls.ensure_cert(self.cert, self.key)
        with open(self.key) as handle:
            self.assertEqual(handle.read(), key_text)
        self.assertEqual(first, second)

    def test_the_fingerprint_is_a_sha256_hex_digest(self):
        fingerprint = tls.ensure_cert(self.cert, self.key)
        self.assertEqual(len(fingerprint), 64)
        int(fingerprint, 16)  # does not raise

    def test_a_server_context_can_be_built_from_the_cert(self):
        tls.ensure_cert(self.cert, self.key)
        context = tls.server_context(self.cert, self.key)
        self.assertIsNotNone(context)


@unittest.skipUnless(has_openssl(), "openssl not installed")
class PinningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cert, key = os.path.join(self.tmp, "server.crt"), os.path.join(self.tmp, "server.key")
        self.fingerprint = tls.ensure_cert(cert, key)
        context = tls.server_context(cert, key)
        self.server = Server(os.path.join(self.tmp, "jobs.db"), host="127.0.0.1", port=0,
                             token="tok", tls_context=context)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = f"https://127.0.0.1:{self.server.port}"

    def test_a_client_with_the_right_fingerprint_connects(self):
        client = Client(self.url, token="tok", fingerprint=self.fingerprint)
        self.assertEqual(client.health()["ok"], True)

    def test_a_client_with_the_wrong_fingerprint_is_refused(self):
        client = Client(self.url, token="tok", fingerprint="0" * 64)
        with self.assertRaises(FingerprintMismatch):
            client.health()

    def test_an_https_client_needs_a_fingerprint_at_all(self):
        from to_medialib.client import ServerError
        client = Client(self.url, token="tok")
        with self.assertRaises(ServerError):
            client.health()

    def test_plain_http_cannot_reach_a_tls_only_server(self):
        client = Client(f"http://127.0.0.1:{self.server.port}", token="tok")
        with self.assertRaises(Unreachable):
            client.health()


if __name__ == "__main__":
    unittest.main()
