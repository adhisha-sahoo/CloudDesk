import hashlib
import time
import uuid

from .models import Actor, CreateRequest, DomainError
from .store import Store, canonical


class Service:
    def __init__(self, store: Store, clock=time.time):
        self.store = store
        self.clock = clock

    def create(
        self, actor: Actor, spec: CreateRequest, key: str, channel_id=None
    ) -> tuple[dict, bool]:
        if not key or len(key) > 128 or any(ord(c) < 32 for c in key):
            raise DomainError(422, "Provide a printable Idempotency-Key of 1-128 characters")
        now = self.clock()
        fingerprint = hashlib.sha256(canonical(spec.model_dump()).encode()).hexdigest()
        with self.store.transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM idempotency WHERE actor=? AND key=?", (actor.id, key)
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise DomainError(409, "This idempotency key belongs to a different request")
                row = conn.execute(
                    "SELECT * FROM requests WHERE id=?", (existing["request_id"],)
                ).fetchone()
                return self.store.request(row), False
            request_id = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO requests(id,owner,slug,ttl_minutes,reason,status,created_at,updated_at,channel_id)
                VALUES(?,?,?,?,?,'PLANNING',?,?,?)""",
                (
                    request_id,
                    actor.id,
                    spec.slug,
                    spec.ttl_minutes,
                    spec.reason,
                    now,
                    now,
                    channel_id,
                ),
            )
            conn.execute(
                "INSERT INTO idempotency VALUES(?,?,?,?)", (actor.id, key, fingerprint, request_id)
            )
            self.store.enqueue(conn, request_id, "plan", now)
            self.store.audit(conn, request_id, actor.id, "REQUEST_CREATED", now, spec.model_dump())
            self.store.notify(conn, request_id, now)
        return self.store.get(request_id), True

    def get(self, actor: Actor, request_id: str) -> dict:
        request = self.store.get(request_id)
        if not request or (actor.role != "approver" and request["owner"] != actor.id):
            raise DomainError(404, "Request not found")
        return request

    def list(self, actor: Actor) -> list[dict]:
        return self.store.list(None if actor.role == "approver" else actor.id)

    def approve(self, actor: Actor, request_id: str, digest: str) -> dict:
        self.get(actor, request_id)
        if actor.role != "approver":
            raise DomainError(403, "An approver account is required")
        now = self.clock()
        with self.store.transaction() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row["status"] != "AWAITING_APPROVAL":
                raise DomainError(409, "Only a planned request can be approved")
            if row["expires_at"] is not None and row["expires_at"] <= now:
                raise DomainError(409, "Expired requests must be cleaned up")
            if digest != row["plan_digest"]:
                raise DomainError(409, "Plan changed; review the current plan before approval")
            conn.execute(
                "UPDATE requests SET status='QUEUED',updated_at=?,error=NULL WHERE id=?",
                (now, request_id),
            )
            self.store.enqueue(conn, request_id, "apply", now)
            self.store.audit(conn, request_id, actor.id, "PLAN_APPROVED", now, {"digest": digest})
            self.store.notify(conn, request_id, now)
        return self.store.get(request_id)

    def reject(self, actor: Actor, request_id: str) -> dict:
        self.get(actor, request_id)
        if actor.role != "approver":
            raise DomainError(403, "An approver account is required")
        now = self.clock()
        with self.store.transaction() as conn:
            row = conn.execute("SELECT status FROM requests WHERE id=?", (request_id,)).fetchone()
            if row["status"] != "AWAITING_APPROVAL":
                raise DomainError(409, "Only a planned request can be rejected")
            conn.execute(
                "UPDATE requests SET status='REJECTED',updated_at=? WHERE id=?", (now, request_id)
            )
            self.store.audit(conn, request_id, actor.id, "REQUEST_REJECTED", now)
            self.store.notify(conn, request_id, now)
        return self.store.get(request_id)

    def destroy(self, actor: Actor, request_id: str) -> dict:
        self.get(actor, request_id)
        now = self.clock()
        with self.store.transaction() as conn:
            row = conn.execute("SELECT status FROM requests WHERE id=?", (request_id,)).fetchone()
            if row["status"] in {"DESTROY_QUEUED", "DESTROYING", "DESTROYED"}:
                return self.store.request(
                    conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
                )
            if row["status"] not in {"ACTIVE", "FAILED", "CLEANUP_FAILED"}:
                raise DomainError(409, "Request is not ready for cleanup")
            inflight = conn.execute(
                "SELECT id FROM jobs WHERE request_id=? AND state IN ('PENDING','RUNNING')",
                (request_id,),
            ).fetchone()
            if not inflight:
                self.store.enqueue(conn, request_id, "destroy", now)
            conn.execute(
                "UPDATE requests SET status='DESTROY_QUEUED',updated_at=? WHERE id=?",
                (now, request_id),
            )
            self.store.audit(conn, request_id, actor.id, "CLEANUP_REQUESTED", now)
        return self.store.get(request_id)

    def retry(self, actor: Actor, request_id: str) -> dict:
        self.get(actor, request_id)
        now = self.clock()
        with self.store.transaction() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row["status"] != "FAILED":
                raise DomainError(409, "Only a failed request can be replanned")
            if row["expires_at"] is not None and row["expires_at"] <= now:
                raise DomainError(409, "Expired requests must be cleaned up")
            # A retry always produces a new plan and requires a new explicit approval.
            conn.execute(
                "UPDATE requests SET status='PLANNING',error=NULL,updated_at=? WHERE id=?",
                (now, request_id),
            )
            self.store.enqueue(conn, request_id, "plan", now)
            self.store.audit(conn, request_id, actor.id, "REPLAN_REQUESTED", now)
        return self.store.get(request_id)

    def schedule_expired(self) -> int:
        now = self.clock()
        count = 0
        with self.store.transaction() as conn:
            rows = conn.execute(
                """SELECT id FROM requests WHERE status IN ('ACTIVE','FAILED','AWAITING_APPROVAL')
                AND expires_at IS NOT NULL AND expires_at<=?""",
                (now,),
            ).fetchall()
            for row in rows:
                inflight = conn.execute(
                    "SELECT id FROM jobs WHERE request_id=? AND state IN ('PENDING','RUNNING')",
                    (row["id"],),
                ).fetchone()
                if not inflight:
                    self.store.enqueue(conn, row["id"], "destroy", now)
                    conn.execute(
                        "UPDATE requests SET status='DESTROY_QUEUED',updated_at=? WHERE id=?",
                        (now, row["id"]),
                    )
                    self.store.audit(conn, row["id"], "scheduler", "TTL_EXPIRED", now)
                    count += 1
        return count

    def metrics(self, actor: Actor) -> dict:
        rows = self.list(actor)
        states = {}
        durations = []
        with self.store.transaction() as conn:
            for row in rows:
                states[row["status"]] = states.get(row["status"], 0) + 1
                events = [
                    __import__("json").loads(item[0])
                    for item in conn.execute(
                        "SELECT event_json FROM audit WHERE request_id=?", (row["id"],)
                    )
                ]
                starts = [e["time"] for e in events if e["action"] == "PLAN_APPROVED"]
                ends = [e["time"] for e in events if e["action"] == "RESOURCE_ACTIVE"]
                if starts and ends:
                    durations.append(max(0, ends[-1] - max(s for s in starts if s <= ends[-1])))
        durations.sort()
        import math

        p95 = durations[max(0, math.ceil(len(durations) * 0.95) - 1)] if durations else None
        return {
            "total": len(rows),
            "states": states,
            "measured_provisions": len(durations),
            "p95_provision_seconds": round(p95, 3) if p95 is not None else None,
            "audit_chain_valid": self.store.verify_audit(),
            "environment": "local AWS emulator",
        }
