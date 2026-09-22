"""A worker: claims jobs from a job server, runs them locally, reports back.

A worker needs no NFS-shared files: inputs and outputs are plain local paths
that must exist and be writable where the worker runs (shared-path mode; see
DESIGN.md for the planned transfer mode).
"""

import logging
import os
import socket
import time

from . import recipes
from .client import Conflict, Unreachable
from .jobs import Job
from .media import Cancelled
from .runner import Policy, display, run_one

log = logging.getLogger("to_media.worker")

POLL_INTERVAL = 2.0
MAX_BACKOFF = 30.0
HEARTBEAT_INTERVAL = 3.0


def _default_id(name):
    return name or f"{socket.gethostname()}#{os.getpid()}"


class HeartbeatCancelled(Cancelled):
    pass


def make_heartbeat(client, job_id, wid, interval=None):
    """A progress(fraction) callback that heartbeats to the server, at most
    once per `interval`, and raises when the server has asked to cancel."""
    state = {"last": 0.0, "fraction": 0.0}

    def progress(fraction):
        state["fraction"] = fraction
        now = time.monotonic()
        if fraction < 1.0 and now - state["last"] < (interval if interval is not None else HEARTBEAT_INTERVAL):
            return
        state["last"] = now
        try:
            result = client.heartbeat(job_id, wid, fraction)
        except (Conflict, Unreachable):
            raise HeartbeatCancelled("the server ended this job")
        if result and result.get("cancel"):
            raise HeartbeatCancelled("cancelled")

    return progress


def run_claimed(client, job_row, wid, policy):
    job = Job.from_dict(job_row["payload"]["job"])
    job_policy = Policy.from_dict({**policy.to_dict(), **job_row["payload"].get("policy", {})})
    recipe = recipes.get(job_row["recipe"])
    if recipe is None:
        client.complete(job_row["id"], wid, "failed", f"unknown recipe {job_row['recipe']}")
        return "failed"
    log.info("[%d] %s", job_row["id"], display(job))
    try:
        status, detail = run_one(recipe, job, job_policy, make_heartbeat(client, job_row["id"], wid))
    except HeartbeatCancelled as error:
        status, detail = "failed", str(error)
    try:
        client.complete(job_row["id"], wid, status, detail if status == "failed" else "", detail)
    except (Conflict, Unreachable) as error:
        log.warning("[%d] could not report %s: %s", job_row["id"], status, error)
    log.info("[%d] %s", job_row["id"], status)
    return status


def run_forever(client, wid=None, capabilities=None, slots=1, stop=None, sleep=time.sleep):
    """Claim and run jobs until `stop` (a callable returning True) says to quit."""
    wid = wid or _default_id(None)
    capabilities = list(capabilities or recipes.names())
    stop = stop or (lambda: False)
    backoff = POLL_INTERVAL
    log.info("worker %s starting, recipes: %s", wid, ", ".join(capabilities))
    while not stop():
        try:
            jobs = client.claim(wid, capabilities, limit=slots, info={"host": socket.gethostname()})
        except Unreachable as error:
            log.warning("server unreachable (%s), retrying in %.0fs", error, backoff)
            sleep(backoff)
            backoff = min(MAX_BACKOFF, backoff * 2)
            continue
        backoff = POLL_INTERVAL
        if not jobs:
            sleep(POLL_INTERVAL)
            continue
        for job_row in jobs:
            if stop():
                try:
                    client.complete(job_row["id"], wid, "released", "worker shutting down")
                except (Conflict, Unreachable):
                    pass
                continue
            run_claimed(client, job_row, wid, Policy())
