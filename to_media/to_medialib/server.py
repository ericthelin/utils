"""The job server: an HTTP JSON API in front of the queue (store.py), plus a
small status page. Workers and clients are plain HTTP clients (see client.py
and worker.py); nothing here depends on how a job is actually converted.

Every request needs `Authorization: Bearer <token>`, except the status page,
which also accepts the token as a `?token=` query parameter so it can be
opened in a browser.
"""

import html
import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .store import Store

REAP_INTERVAL = 5.0

log = logging.getLogger("to_media.server")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _job_or_404(store, job_id):
    job = store.job(job_id)
    if job is None:
        raise ApiError(404, "no such job")
    return job


def _batch_or_404(store, batch_id):
    batch = store.batch(batch_id)
    if batch is None:
        raise ApiError(404, "no such batch")
    return batch


def _int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a number")


# Routes: (method, path regex, handler(store, match, body, query) -> data)

def _route_submit(store, match, body, query):
    recipe = body.get("recipe")
    payloads = body.get("payloads")
    if not recipe or not isinstance(payloads, list) or not payloads:
        raise ApiError(400, "recipe and a non-empty list of payloads are required")
    batch = store.add_batch(recipe, payloads, label=body.get("label"),
                            priority=int(body.get("priority", 0)),
                            max_attempts=int(body.get("max_attempts", 3)))
    return {"batch": batch}


def _route_claim(store, match, body, query):
    worker = body.get("worker")
    recipes = body.get("recipes") or []
    if not worker:
        raise ApiError(400, "worker is required")
    store.touch_worker(worker, body.get("info", {}))
    jobs = store.claim(worker, recipes, limit=int(body.get("limit", 1)))
    return {"jobs": jobs}


def _route_heartbeat(store, match, body, query):
    job_id = _int(match.group("id"), "job id")
    worker = body.get("worker")
    result = store.heartbeat(job_id, worker, body.get("progress", 0))
    if result is None:
        raise ApiError(409, "this worker no longer holds that job")
    return result


def _route_complete(store, match, body, query):
    job_id = _int(match.group("id"), "job id")
    worker = body.get("worker")
    status = body.get("status")
    if status not in ("done", "skipped", "failed", "released"):
        raise ApiError(400, "status must be done, skipped, failed or released")
    if not store.complete(job_id, worker, status, body.get("detail", ""), body.get("notes", "")):
        raise ApiError(409, "this worker no longer holds that job")
    return {"ok": True}


def _route_job(store, match, body, query):
    return _job_or_404(store, _int(match.group("id"), "job id"))


def _route_jobs(store, match, body, query):
    states = query.get("state")
    batch_id = query.get("batch", [None])[0]
    return {"jobs": store.jobs(states=states, batch_id=_int(batch_id, "batch") if batch_id else None,
                               limit=_int(query.get("limit", ["50"])[0], "limit"),
                               offset=_int(query.get("offset", ["0"])[0], "offset"))}


def _route_batch(store, match, body, query):
    return _batch_or_404(store, _int(match.group("id"), "batch id"))


def _route_batches(store, match, body, query):
    return {"batches": store.batches(limit=_int(query.get("limit", ["20"])[0], "limit"))}


def _route_cancel_job(store, match, body, query):
    return {"cancelled": store.cancel(job_ids=[_int(match.group("id"), "job id")])}


def _route_cancel_batch(store, match, body, query):
    return {"cancelled": store.cancel(batch_id=_int(match.group("id"), "batch id"))}


def _route_retry_job(store, match, body, query):
    return {"retried": store.retry(job_ids=[_int(match.group("id"), "job id")])}


def _route_retry_batch(store, match, body, query):
    return {"retried": store.retry(batch_id=_int(match.group("id"), "batch id"))}


def _route_workers(store, match, body, query):
    return {"workers": store.workers()}


def _route_health(store, match, body, query):
    return {"ok": True, "version": __version__}


ROUTES = [
    ("POST", re.compile(r"^/batches$"), _route_submit),
    ("GET", re.compile(r"^/batches$"), _route_batches),
    ("GET", re.compile(r"^/batches/(?P<id>\d+)$"), _route_batch),
    ("POST", re.compile(r"^/batches/(?P<id>\d+)/cancel$"), _route_cancel_batch),
    ("POST", re.compile(r"^/batches/(?P<id>\d+)/retry$"), _route_retry_batch),
    ("POST", re.compile(r"^/claims$"), _route_claim),
    ("GET", re.compile(r"^/jobs$"), _route_jobs),
    ("GET", re.compile(r"^/jobs/(?P<id>\d+)$"), _route_job),
    ("POST", re.compile(r"^/jobs/(?P<id>\d+)/heartbeat$"), _route_heartbeat),
    ("POST", re.compile(r"^/jobs/(?P<id>\d+)/complete$"), _route_complete),
    ("POST", re.compile(r"^/jobs/(?P<id>\d+)/cancel$"), _route_cancel_job),
    ("POST", re.compile(r"^/jobs/(?P<id>\d+)/retry$"), _route_retry_job),
    ("GET", re.compile(r"^/workers$"), _route_workers),
    ("GET", re.compile(r"^/health$"), _route_health),
]


def status_page(store, version):
    batches = store.batches()
    workers = store.workers()
    rows = "".join(
        f"<tr><td>{b['id']}</td><td>{html.escape(b['recipe'])}</td>"
        f"<td>{html.escape(b['label'] or '')}</td>"
        f"<td>{b['progress'] * 100:.0f}%</td>"
        f"<td>{', '.join(f'{k}={v}' for k, v in b['counts'].items() if v)}</td>"
        f"<td>{'-' if b['eta'] is None else format(b['eta'], '.0f') + 's'}</td></tr>"
        for b in batches)
    worker_rows = "".join(
        f"<tr><td>{html.escape(w['id'])}</td><td>{w['job'] or '-'}</td>"
        f"<td>{time.time() - w['last_seen']:.0f}s ago</td></tr>"
        for w in workers)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>to_media server {html.escape(version)}</title>"
        "<meta http-equiv='refresh' content='5'>"
        "<style>body{font-family:sans-serif}table{border-collapse:collapse}"
        "td,th{border:1px solid #ccc;padding:.3em .6em;text-align:left}</style>"
        "</head><body>"
        f"<h1>to_media server {html.escape(version)}</h1>"
        "<h2>Batches</h2><table><tr><th>id</th><th>recipe</th><th>label</th>"
        f"<th>progress</th><th>counts</th><th>eta</th></tr>{rows}</table>"
        "<h2>Workers</h2><table><tr><th>id</th><th>job</th><th>last seen</th></tr>"
        f"{worker_rows}</table></body></html>"
    )


def make_handler(store, token, version=__version__):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"to_media/{version}"

        def log_message(self, fmt, *args):
            log.info("%s - %s", self.address_string(), fmt % args)

        def _authorized(self, query):
            header = self.headers.get("Authorization", "")
            given = header[7:] if header.startswith("Bearer ") else query.get("token", [None])[0]
            return token is None or given == token

        def _send_json(self, status, data):
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                raise ApiError(400, "invalid JSON body")

        def _dispatch(self, method):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if parts.path == "/status" and method == "GET":
                if not self._authorized(query):
                    self._send_json(401, {"error": "unauthorized"})
                    return
                body = status_page(store, version).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parts.path == "/health" and method == "GET":
                self._send_json(200, {"ok": True, "version": version})
                return
            if not self._authorized(query):
                self._send_json(401, {"error": "unauthorized"})
                return
            for route_method, pattern, view in ROUTES:
                match = pattern.match(parts.path)
                if match and route_method == method:
                    try:
                        body = self._body() if method == "POST" else None
                        self._send_json(200, view(store, match, body, query))
                    except ApiError as error:
                        self._send_json(error.status, {"error": error.message})
                    return
            self._send_json(404, {"error": "no such route"})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return Handler


class Server:
    """A running job server: the HTTP listener plus a background lease reaper."""

    def __init__(self, db_path, host="0.0.0.0", port=0, token=None, clock=time.time, tls_context=None):
        self.store = Store(db_path, clock=clock)
        self.httpd = ThreadingHTTPServer((host, port), make_handler(self.store, token))
        if tls_context is not None:
            self.httpd.socket = tls_context.wrap_socket(self.httpd.socket, server_side=True)
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, daemon=True)

    @property
    def port(self):
        return self.httpd.server_address[1]

    def _reap_loop(self):
        while not self._stop.wait(REAP_INTERVAL):
            try:
                reaped = self.store.reap()
                if reaped:
                    log.info("reaped %d job(s) with an expired lease", reaped)
            except Exception:
                log.exception("lease reaper failed")

    def start(self):
        self._reaper.start()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        log.info("listening on %s:%d", *self.httpd.server_address)

    def serve_forever(self):
        self._reaper.start()
        log.info("listening on %s:%d", *self.httpd.server_address)
        self.httpd.serve_forever()

    def stop(self):
        self._stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()
