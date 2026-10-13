from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, slug TEXT NOT NULL,
 ttl_minutes INTEGER NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL,
 plan_json TEXT, plan_digest TEXT, resource_json TEXT, error TEXT,
 channel_id TEXT, ticket_id TEXT
);
CREATE TABLE IF NOT EXISTS idempotency (
 actor TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 request_id TEXT NOT NULL REFERENCES requests(id), PRIMARY KEY(actor, key)
);
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL REFERENCES requests(id),
 action TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
 due_at REAL NOT NULL, error TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_inflight_job ON jobs(request_id)
 WHERE state IN ('PENDING', 'RUNNING');
CREATE TABLE IF NOT EXISTS audit (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
 event_json TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slack_inbox (
 key TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
 due_at REAL NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
 due_at REAL NOT NULL, error TEXT, payload_json TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.transaction() as conn:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(outbox)")}
            if "payload_json" not in columns:
                conn.execute("ALTER TABLE outbox ADD COLUMN payload_json TEXT")

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def request(row) -> dict:
        data = dict(row)
        for key in ("plan", "resource"):
            data[key] = json.loads(data.pop(f"{key}_json") or "null")
        return data

    @staticmethod
    def audit(conn, request_id: str, actor: str, action: str, now: float, detail=None):
        previous = conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = previous[0] if previous else "0" * 64
        event = canonical(
            {
                "request_id": request_id,
                "actor": actor,
                "action": action,
                "time": now,
                "detail": detail,
            }
        )
        digest = hashlib.sha256((prev + event).encode()).hexdigest()
        conn.execute(
            "INSERT INTO audit(request_id,event_json,previous_hash,hash) VALUES(?,?,?,?)",
            (request_id, event, prev, digest),
        )

    @staticmethod
    def enqueue(conn, request_id: str, action: str, now: float):
        conn.execute(
            "INSERT INTO jobs(request_id,action,due_at) VALUES(?,?,?)", (request_id, action, now)
        )

    @staticmethod
    def notify(conn, request_id: str, now: float):
        row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        conn.execute(
            "INSERT INTO outbox(request_id,due_at,payload_json) VALUES(?,?,?)",
            (request_id, now, canonical(Store.request(row))),
        )

    def get(self, request_id: str) -> dict | None:
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            return self.request(row) if row else None

    def list(self, owner: str | None = None) -> list[dict]:
        with self.transaction() as conn:
            if owner:
                rows = conn.execute(
                    "SELECT * FROM requests WHERE owner=? ORDER BY created_at DESC LIMIT 200",
                    (owner,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM requests ORDER BY created_at DESC LIMIT 200"
                ).fetchall()
            return [self.request(row) for row in rows]

    def history(self, request_id: str) -> list[dict]:
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM audit WHERE request_id=? ORDER BY seq", (request_id,)
            )
            return [{**dict(row), "event": json.loads(row["event_json"])} for row in rows]

    def verify_audit(self) -> bool:
        previous = "0" * 64
        with self.transaction() as conn:
            for row in conn.execute("SELECT * FROM audit ORDER BY seq"):
                digest = hashlib.sha256((previous + row["event_json"]).encode()).hexdigest()
                if row["previous_hash"] != previous or row["hash"] != digest:
                    return False
                previous = row["hash"]
        return True

    def recover_jobs(self):
        # One application process owns the worker; interrupted idempotent jobs are resumed.
        with self.transaction() as conn:
            conn.execute("UPDATE jobs SET state='PENDING' WHERE state='RUNNING'")
            conn.execute("UPDATE outbox SET state='PENDING' WHERE state='RUNNING'")
            conn.execute("UPDATE slack_inbox SET state='PENDING' WHERE state='RUNNING'")

    def bind_executor(self, executor: str):
        with self.transaction() as conn:
            old = conn.execute("SELECT value FROM metadata WHERE key='executor'").fetchone()
            if old and old[0] != executor:
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM requests WHERE status NOT IN ('DESTROYED','REJECTED')"
                ).fetchone()[0]
                if remaining:
                    raise RuntimeError(
                        "Clean up nonterminal requests before changing executors, or use a fresh data directory"
                    )
            conn.execute(
                "INSERT INTO metadata(key,value) VALUES('executor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (executor,),
            )

    def claim(self, table: str, now: float):
        if table not in {"jobs", "outbox", "slack_inbox"}:
            raise ValueError("Unknown queue")
        key = "key" if table == "slack_inbox" else "id"
        with self.transaction() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE state='PENDING' AND due_at<=? ORDER BY due_at,{key} LIMIT 1",  # noqa: S608 - fixed queue allowlist above
                (now,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                f"UPDATE {table} SET state='RUNNING',attempts=attempts+1 WHERE {key}=?",  # noqa: S608 - fixed queue allowlist above
                (row[key],),  # noqa: S608 - fixed queue allowlist above
            )
            return {**dict(row), "attempts": row["attempts"] + 1}
