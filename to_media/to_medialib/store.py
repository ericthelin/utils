"""The job queue: batches of jobs in SQLite, with leases so that a job whose
worker disappears goes back to the queue.

Jobs move queued -> running -> done | skipped | failed | cancelled. A worker
holds a running job on a lease that it renews with heartbeats; when the lease
lapses the job is requeued (or failed once it has used all its attempts).
"""

import json
import sqlite3
import threading
import time

TERMINAL = ("done", "skipped", "failed", "cancelled")
STATES = ("queued", "running") + TERMINAL
LEASE_SECONDS = 60
MAX_ATTEMPTS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    recipe TEXT NOT NULL,
    label TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    recipe TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    worker TEXT,
    lease_expires REAL,
    progress REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    detail TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS jobs_claim ON jobs(state, priority, id);
CREATE INDEX IF NOT EXISTS jobs_batch ON jobs(batch_id, state);
CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    info TEXT NOT NULL,
    last_seen REAL NOT NULL
);
"""


def row_dict(row):
    if row is None:
        return None
    data = dict(row)
    if "payload" in data:
        data["payload"] = json.loads(data["payload"])
    return data


class Store:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def transaction(self):
        return _Transaction(self)

    # submitting -----------------------------------------------------------

    def add_batch(self, recipe, payloads, label=None, priority=0, max_attempts=MAX_ATTEMPTS):
        """Queue a batch of jobs; each payload is plain data (job and policy)."""
        now = self.clock()
        with self.transaction() as db:
            batch = db.execute("INSERT INTO batches(created, recipe, label) VALUES (?,?,?)",
                               (now, recipe, label)).lastrowid
            db.executemany(
                "INSERT INTO jobs(batch_id, recipe, payload, priority, max_attempts, created) VALUES (?,?,?,?,?,?)",
                [(batch, recipe, json.dumps(p, sort_keys=True), priority, max_attempts, now) for p in payloads])
        return batch

    # working ---------------------------------------------------------------

    def claim(self, worker, recipes, lease=LEASE_SECONDS, limit=1):
        """Give the worker up to `limit` queued jobs it can run, on a lease."""
        now = self.clock()
        marks = ",".join("?" * len(recipes))
        if not recipes:
            return []
        with self.transaction() as db:
            rows = db.execute(
                f"SELECT id FROM jobs WHERE state='queued' AND recipe IN ({marks}) "
                "ORDER BY priority DESC, id LIMIT ?", (*recipes, limit)).fetchall()
            ids = [r["id"] for r in rows]
            for job_id in ids:
                db.execute("UPDATE jobs SET state='running', worker=?, lease_expires=?, attempts=attempts+1, "
                           "progress=0, started=COALESCE(started, ?), cancel_requested=0 WHERE id=?",
                           (worker, now + lease, now, job_id))
        return [self.job(job_id) for job_id in ids]

    def heartbeat(self, job_id, worker, progress, lease=LEASE_SECONDS):
        """Renew a lease and record progress. None when the worker no longer holds the job."""
        with self.transaction() as db:
            row = db.execute("SELECT cancel_requested FROM jobs WHERE id=? AND worker=? AND state='running'",
                             (job_id, worker)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET lease_expires=?, progress=? WHERE id=?",
                       (self.clock() + lease, max(0.0, min(1.0, float(progress))), job_id))
            return {"cancel": bool(row["cancel_requested"])}

    def complete(self, job_id, worker, status, detail="", notes=""):
        """Record how a job ended. False when the worker no longer holds the job."""
        now = self.clock()
        with self.transaction() as db:
            row = db.execute("SELECT attempts, max_attempts, cancel_requested FROM jobs "
                             "WHERE id=? AND worker=? AND state='running'", (job_id, worker)).fetchone()
            if row is None:
                return False
            if status == "released":
                db.execute("UPDATE jobs SET state='queued', worker=NULL, lease_expires=NULL, "
                           "attempts=MAX(attempts-1, 0), progress=0 WHERE id=?", (job_id,))
            elif status == "failed" and row["cancel_requested"]:
                db.execute("UPDATE jobs SET state='cancelled', finished=?, detail=?, worker=NULL, lease_expires=NULL "
                           "WHERE id=?", (now, "cancelled", job_id))
            elif status == "failed" and row["attempts"] < row["max_attempts"]:
                db.execute("UPDATE jobs SET state='queued', worker=NULL, lease_expires=NULL, progress=0, detail=? "
                           "WHERE id=?", (f"attempt {row['attempts']} failed: {detail}", job_id))
            else:
                progress = 1.0 if status in ("done", "skipped") else None
                db.execute("UPDATE jobs SET state=?, finished=?, detail=?, notes=?, worker=NULL, "
                           "lease_expires=NULL, progress=COALESCE(?, progress) WHERE id=?",
                           (status, now, detail, notes, progress, job_id))
        return True

    def reap(self):
        """Requeue (or fail) running jobs whose lease has lapsed. Returns how many."""
        now = self.clock()
        with self.transaction() as db:
            rows = db.execute("SELECT id, attempts, max_attempts FROM jobs "
                              "WHERE state='running' AND lease_expires < ?", (now,)).fetchall()
            for row in rows:
                if row["attempts"] >= row["max_attempts"]:
                    db.execute("UPDATE jobs SET state='failed', finished=?, worker=NULL, lease_expires=NULL, "
                               "detail=? WHERE id=?", (now, "the worker stopped responding too many times", row["id"]))
                else:
                    db.execute("UPDATE jobs SET state='queued', worker=NULL, lease_expires=NULL, progress=0, "
                               "detail=? WHERE id=?", ("the worker stopped responding", row["id"]))
        return len(rows)

    # managing ---------------------------------------------------------------

    def cancel(self, job_ids=None, batch_id=None):
        """Cancel queued jobs at once and ask running ones to stop. Returns how many were affected."""
        where, args = self._scope(job_ids, batch_id)
        now = self.clock()
        with self.transaction() as db:
            queued = db.execute(f"UPDATE jobs SET state='cancelled', finished=?, detail='cancelled' "
                                f"WHERE state='queued' AND {where}", (now, *args)).rowcount
            running = db.execute(f"UPDATE jobs SET cancel_requested=1 WHERE state='running' AND {where}",
                                 args).rowcount
        return queued + running

    def retry(self, job_ids=None, batch_id=None):
        """Queue failed and cancelled jobs again. Returns how many."""
        where, args = self._scope(job_ids, batch_id)
        with self.transaction() as db:
            return db.execute(
                "UPDATE jobs SET state='queued', attempts=0, progress=0, detail=NULL, finished=NULL, "
                f"worker=NULL, cancel_requested=0 WHERE state IN ('failed','cancelled') AND {where}",
                args).rowcount

    @staticmethod
    def _scope(job_ids, batch_id):
        if job_ids:
            return f"id IN ({','.join('?' * len(job_ids))})", tuple(job_ids)
        if batch_id:
            return "batch_id=?", (batch_id,)
        return "1=1", ()

    # asking ---------------------------------------------------------------

    def job(self, job_id):
        with self.lock:
            return row_dict(self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def jobs(self, states=None, batch_id=None, limit=50, offset=0):
        clauses, args = [], []
        if states:
            clauses.append(f"state IN ({','.join('?' * len(states))})")
            args += list(states)
        if batch_id:
            clauses.append("batch_id=?")
            args.append(batch_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.lock:
            rows = self.db.execute(f"SELECT * FROM jobs {where} ORDER BY id LIMIT ? OFFSET ?",
                                   (*args, limit, offset)).fetchall()
        return [row_dict(r) for r in rows]

    def counts(self, batch_id=None):
        where, args = ("WHERE batch_id=?", (batch_id,)) if batch_id else ("", ())
        with self.lock:
            rows = self.db.execute(f"SELECT state, COUNT(*) AS n FROM jobs {where} GROUP BY state", args).fetchall()
        counts = {state: 0 for state in STATES}
        counts.update({r["state"]: r["n"] for r in rows})
        return counts

    def batch(self, batch_id):
        """Summary of one batch: counts, overall progress and an estimate of the time left."""
        with self.lock:
            row = self.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if row is None:
                return None
            running = self.db.execute("SELECT COALESCE(SUM(progress), 0) AS p FROM jobs "
                                      "WHERE batch_id=? AND state='running'", (batch_id,)).fetchone()["p"]
            first = self.db.execute("SELECT MIN(started) AS s FROM jobs WHERE batch_id=?", (batch_id,)).fetchone()["s"]
        counts = self.counts(batch_id)
        total = sum(counts.values())
        finished = sum(counts[s] for s in TERMINAL)
        units = finished + running
        progress = units / total if total else 1.0
        now = self.clock()
        elapsed = (now - first) if first else 0.0
        eta = elapsed * (1 - progress) / progress if first and progress >= 0.02 and finished < total else None
        return {"id": batch_id, "recipe": row["recipe"], "label": row["label"], "created": row["created"],
                "counts": counts, "total": total, "progress": progress, "elapsed": elapsed, "eta": eta,
                "complete": finished == total}

    def batches(self, limit=20):
        with self.lock:
            ids = [r["id"] for r in self.db.execute("SELECT id FROM batches ORDER BY id DESC LIMIT ?", (limit,))]
        return [self.batch(i) for i in ids]

    # workers ---------------------------------------------------------------

    def touch_worker(self, worker, info):
        with self.transaction() as db:
            db.execute("INSERT INTO workers(id, info, last_seen) VALUES (?,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET info=excluded.info, last_seen=excluded.last_seen",
                       (worker, json.dumps(info, sort_keys=True), self.clock()))

    def workers(self, within=300):
        cutoff = self.clock() - within
        with self.lock:
            rows = self.db.execute("SELECT * FROM workers WHERE last_seen >= ? ORDER BY id", (cutoff,)).fetchall()
            busy = {r["worker"]: r["id"] for r in self.db.execute(
                "SELECT worker, id FROM jobs WHERE state='running'")}
        return [{"id": r["id"], "info": json.loads(r["info"]), "last_seen": r["last_seen"],
                 "job": busy.get(r["id"])} for r in rows]


class _Transaction:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        self.store.lock.acquire()
        self.store.db.execute("BEGIN IMMEDIATE")
        return self.store.db

    def __exit__(self, kind, error, traceback):
        try:
            self.store.db.execute("ROLLBACK" if kind else "COMMIT")
        finally:
            self.store.lock.release()
        return False
