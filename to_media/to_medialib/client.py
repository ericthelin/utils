"""A small HTTP client for talking to a to_media job server.

Plain http:// goes over a normal connection. https:// is pinned: the server's
certificate is self-signed (see tls.py), so there is no certificate authority
to trust it, and instead its SHA-256 fingerprint must match the one the join
string carried (see join.py). A mismatch is treated as unreachable, the same
as any other TLS failure, rather than silently accepted.
"""

import hashlib
import http.client
import json
import socket
import ssl
from urllib.parse import urlsplit


class ServerError(Exception):
    """The server rejected a request; the message is what it said."""


class Conflict(ServerError):
    """A 409: the caller no longer holds the job it tried to act on."""


class NotFound(ServerError):
    """A 404: no such job or batch."""


class Unreachable(ServerError):
    """The server could not be reached at all, or its certificate did not match."""


class FingerprintMismatch(Unreachable):
    """The server's certificate is not the one the join string named."""


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPS connection that trusts one exact certificate, by its SHA-256
    fingerprint, instead of a certificate authority."""

    def __init__(self, host, port, fingerprint, timeout):
        super().__init__(host, port, timeout=timeout)
        self.fingerprint = fingerprint

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.sock = context.wrap_socket(sock, server_hostname=self.host)
        actual = hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest()
        if actual != self.fingerprint:
            self.sock.close()
            raise FingerprintMismatch(
                f"certificate fingerprint mismatch: expected {self.fingerprint}, got {actual}")


class Client:
    def __init__(self, url, token=None, fingerprint=None, timeout=30):
        parts = urlsplit(url)
        self.scheme, self.host, self.port = parts.scheme, parts.hostname, parts.port or (
            443 if parts.scheme == "https" else 80)
        self.token = token
        self.fingerprint = fingerprint
        self.timeout = timeout

    def _connection(self):
        if self.scheme == "https":
            if not self.fingerprint:
                raise ServerError("an https:// server needs its certificate fingerprint")
            return PinnedHTTPSConnection(self.host, self.port, self.fingerprint, self.timeout)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            connection = self._connection()
            try:
                connection.request(method, path, body=data, headers=headers)
                response = connection.getresponse()
                payload = response.read()
            finally:
                connection.close()
        except FingerprintMismatch:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise Unreachable(str(error))
        if response.status >= 400:
            message = response.reason
            try:
                message = json.loads(payload)["error"]
            except (ValueError, KeyError):
                pass
            if response.status == 404:
                raise NotFound(message)
            if response.status == 409:
                raise Conflict(message)
            raise ServerError(message)
        return json.loads(payload or b"{}")

    def health(self):
        return self._call("GET", "/health")

    def submit(self, recipe, payloads, label=None, priority=0, max_attempts=None):
        body = {"recipe": recipe, "payloads": payloads, "label": label, "priority": priority}
        if max_attempts is not None:
            body["max_attempts"] = max_attempts
        return self._call("POST", "/batches", body)["batch"]

    def claim(self, worker, recipes, limit=1, info=None):
        return self._call("POST", "/claims",
                          {"worker": worker, "recipes": recipes, "limit": limit, "info": info or {}})["jobs"]

    def heartbeat(self, job_id, worker, progress):
        return self._call("POST", f"/jobs/{job_id}/heartbeat", {"worker": worker, "progress": progress})

    def complete(self, job_id, worker, status, detail="", notes=""):
        self._call("POST", f"/jobs/{job_id}/complete",
                   {"worker": worker, "status": status, "detail": detail, "notes": notes})

    def job(self, job_id):
        return self._call("GET", f"/jobs/{job_id}")

    def jobs(self, states=None, batch_id=None, limit=50, offset=0):
        query = f"?limit={limit}&offset={offset}"
        if batch_id:
            query += f"&batch={batch_id}"
        for state in states or []:
            query += f"&state={state}"
        return self._call("GET", "/jobs" + query)["jobs"]

    def batch(self, batch_id):
        return self._call("GET", f"/batches/{batch_id}")

    def batches(self, limit=20):
        return self._call("GET", f"/batches?limit={limit}")["batches"]

    def cancel(self, job_id=None, batch_id=None):
        if job_id:
            return self._call("POST", f"/jobs/{job_id}/cancel")["cancelled"]
        return self._call("POST", f"/batches/{batch_id}/cancel")["cancelled"]

    def retry(self, job_id=None, batch_id=None):
        if job_id:
            return self._call("POST", f"/jobs/{job_id}/retry")["retried"]
        return self._call("POST", f"/batches/{batch_id}/retry")["retried"]

    def workers(self):
        return self._call("GET", "/workers")["workers"]
