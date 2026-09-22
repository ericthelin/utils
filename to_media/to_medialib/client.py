"""A small HTTP client for talking to a to_media job server."""

import json
import urllib.error
import urllib.request


class ServerError(Exception):
    """The server rejected a request; the message is what it said."""


class Conflict(ServerError):
    """A 409: the caller no longer holds the job it tried to act on."""


class NotFound(ServerError):
    """A 404: no such job or batch."""


class Unreachable(ServerError):
    """The server could not be reached at all."""


class Client:
    def __init__(self, url, token=None, timeout=30):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            message = error.reason
            try:
                message = json.loads(error.read())["error"]
            except (ValueError, KeyError):
                pass
            if error.code == 404:
                raise NotFound(message)
            if error.code == 409:
                raise Conflict(message)
            raise ServerError(message)
        except urllib.error.URLError as error:
            raise Unreachable(str(error.reason))

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
