import logging
import threading

from .store import canonical

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, service, infrastructure, settings, slack_handler=None, notifier=None):
        self.service = service
        self.store = service.store
        self.infrastructure = infrastructure
        self.settings = settings
        self.slack_handler = slack_handler
        self.notifier = notifier
        self.stop_event = threading.Event()
        self.thread = None

    def tick(self) -> bool:
        self.service.schedule_expired()
        job = self.store.claim("jobs", self.service.clock())
        if job:
            self.execute(job)
            return True
        if self.slack_handler:
            item = self.store.claim("slack_inbox", self.service.clock())
            if item:
                self.handle_message(item)
                return True
        item = self.store.claim("outbox", self.service.clock())
        if item:
            self.handle_notification(item)
            return True
        return False

    def execute(self, job):
        request = self.store.get(job["request_id"])
        action = job["action"]
        now = self.service.clock()
        if action == "apply" and request["expires_at"] is not None and request["expires_at"] <= now:
            action = "destroy"
            with self.store.transaction() as conn:
                conn.execute("UPDATE jobs SET action='destroy' WHERE id=?", (job["id"],))
                self.store.audit(conn, request["id"], "scheduler", "TTL_EXPIRED_BEFORE_RETRY", now)
        with self.store.transaction() as conn:
            state = {"plan": "PLANNING", "apply": "PROVISIONING", "destroy": "DESTROYING"}[action]
            # Start the TTL before applying so failed, partially-created resources also expire.
            expires = request["expires_at"]
            if action == "apply" and expires is None:
                expires = now + request["ttl_minutes"] * 60
            conn.execute(
                "UPDATE requests SET status=?,updated_at=?,expires_at=? WHERE id=?",
                (state, now, expires, request["id"]),
            )
            self.store.audit(conn, request["id"], "worker", f"{action.upper()}_STARTED", now)
        request = self.store.get(request["id"])
        try:
            result = getattr(self.infrastructure, action)(request)
            if not isinstance(result, dict):
                raise ValueError("Provider returned an invalid result")
            if action == "plan":
                import re

                if not re.fullmatch(r"[0-9a-f]{64}", result.get("digest", "")) or not isinstance(
                    result.get("changes"), list
                ):
                    raise ValueError("Provider returned an invalid review plan")
        except Exception as error:
            # Do not put provider exception strings into the public UI: they can include credentials.
            error_name = type(error).__name__
            log.warning("%s job %s failed (%s)", action, job["id"], error_name)
            now = self.service.clock()
            retry_cleanup = action == "destroy" and job["attempts"] < 5
            state = "CLEANUP_FAILED" if action == "destroy" else "FAILED"
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE requests SET status=?,error=?,updated_at=? WHERE id=?",
                    (
                        state,
                        f"{action} failed ({error_name}); inspect local worker/provider logs",
                        now,
                        request["id"],
                    ),
                )
                conn.execute(
                    "UPDATE jobs SET state=?,due_at=?,error=? WHERE id=?",
                    (
                        "PENDING" if retry_cleanup else "FAILED",
                        now + self.settings.cleanup_retry_seconds * job["attempts"],
                        error_name,
                        job["id"],
                    ),
                )
                self.store.audit(
                    conn,
                    request["id"],
                    "worker",
                    f"{action.upper()}_FAILED",
                    now,
                    {"error_type": error_name, "retry_scheduled": retry_cleanup},
                )
                self.store.notify(conn, request["id"], now)
            return
        now = self.service.clock()
        with self.store.transaction() as conn:
            if action == "plan":
                conn.execute(
                    "UPDATE requests SET status='AWAITING_APPROVAL',plan_json=?,plan_digest=?,error=NULL,updated_at=? WHERE id=?",
                    (canonical(result), result["digest"], now, request["id"]),
                )
                event = "PLAN_READY"
            elif action == "apply":
                conn.execute(
                    "UPDATE requests SET status='ACTIVE',resource_json=?,error=NULL,updated_at=? WHERE id=?",
                    (canonical(result), now, request["id"]),
                )
                event = "RESOURCE_ACTIVE"
            else:
                conn.execute(
                    "UPDATE requests SET status='DESTROYED',error=NULL,updated_at=? WHERE id=?",
                    (now, request["id"]),
                )
                event = "RESOURCE_DESTROYED"
            conn.execute("UPDATE jobs SET state='SUCCESS',error=NULL WHERE id=?", (job["id"],))
            self.store.audit(conn, request["id"], "worker", event, now)
            self.store.notify(conn, request["id"], now)

    def handle_message(self, item):
        import json

        try:
            self.slack_handler(json.loads(item["payload_json"]), item["key"])
            state, error = "SUCCESS", None
        except Exception as exc:
            state = "PENDING" if item["attempts"] < 3 else "FAILED"
            error = type(exc).__name__
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE slack_inbox SET state=?,due_at=?,error=? WHERE key=?",
                (state, self.service.clock() + 5 * item["attempts"], error, item["key"]),
            )

    def handle_notification(self, item):
        try:
            if self.notifier:
                import json

                snapshot = (
                    json.loads(item["payload_json"])
                    if item.get("payload_json")
                    else self.store.get(item["request_id"])
                )
                self.notifier(snapshot)
            state, error = "SUCCESS", None
        except Exception as exc:
            state = "PENDING" if item["attempts"] < 5 else "FAILED"
            error = type(exc).__name__
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE outbox SET state=?,due_at=?,error=? WHERE id=?",
                (state, self.service.clock() + 5 * item["attempts"], error, item["id"]),
            )

    def start(self):
        self.store.recover_jobs()
        self.thread = threading.Thread(target=self.run, name="clouddesk-worker", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                worked = self.tick()
            except Exception:
                log.exception("Worker cycle failed")
                worked = False
            if not worked:
                self.stop_event.wait(self.settings.worker_interval)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()  # Keep the runtime lock until its bounded provider operation finishes.
