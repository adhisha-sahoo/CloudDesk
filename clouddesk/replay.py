import tempfile
import time
from pathlib import Path

from .infrastructure import ApiInfrastructure
from .models import Actor, CreateRequest, DomainError
from .service import Service
from .store import Store
from .worker import Worker

SCENARIOS = {
    "duplicate": "A repeated creation request returns the same sandbox request",
    "unauthorized": "A requester cannot approve infrastructure changes",
    "failure": "A failed apply stays failed until a new plan is reviewed",
    "expiry": "Expired sandbox resources are removed by the scheduler",
    "cleanup-retry": "A transient cleanup failure is retried automatically",
}


class InjectedFailure(RuntimeError):
    pass


class FaultInfrastructure:
    def __init__(self, wrapped, fail_action=None):
        self.wrapped, self.fail_action, self.failed = wrapped, fail_action, False

    def __getattr__(self, name):
        def call(request):
            if name == self.fail_action and not self.failed:
                self.failed = True
                raise InjectedFailure("Deliberately injected local test fault")
            return getattr(self.wrapped, name)(request)

        return call


def run_scenario(name: str, settings) -> dict:
    if name not in SCENARIOS:
        raise DomainError(404, "Unknown replay scenario")
    started = time.monotonic()
    clock = [time.time()]
    requester, approver = (
        Actor("replay-requester", "requester"),
        Actor("replay-approver", "approver"),
    )
    infrastructure = FaultInfrastructure(
        ApiInfrastructure(settings.aws_endpoint),
        {"failure": "apply", "cleanup-retry": "destroy"}.get(name),
    )
    with tempfile.TemporaryDirectory(prefix="clouddesk-replay-") as folder:
        store = Store(Path(folder) / "replay.sqlite3")
        service = Service(store, lambda: clock[0])
        worker = Worker(service, infrastructure, settings)
        request, _ = service.create(
            requester, CreateRequest(slug="incident-replay", ttl_minutes=1), "replay-key"
        )
        checks = []
        try:
            worker.tick()  # plan
            if name == "duplicate":
                repeated, created = service.create(
                    requester, CreateRequest(slug="incident-replay", ttl_minutes=1), "replay-key"
                )
                checks.append(
                    {
                        "check": "same ID, no additional request",
                        "passed": not created
                        and repeated["id"] == request["id"]
                        and len(service.list(approver)) == 1,
                    }
                )
            elif name == "unauthorized":
                try:
                    service.approve(
                        requester, request["id"], store.get(request["id"])["plan_digest"]
                    )
                    denied = False
                except DomainError as error:
                    denied = error.status == 403
                checks.append(
                    {
                        "check": "unauthorized approval rejected",
                        "passed": denied
                        and store.get(request["id"])["status"] == "AWAITING_APPROVAL",
                    }
                )
            else:
                service.approve(approver, request["id"], store.get(request["id"])["plan_digest"])
                worker.tick()  # apply
                if name == "failure":
                    checks.append(
                        {
                            "check": "apply failure recorded",
                            "passed": store.get(request["id"])["status"] == "FAILED",
                        }
                    )
                    service.retry(requester, request["id"])
                    worker.tick()
                    checks.append(
                        {
                            "check": "retry requires fresh approval",
                            "passed": store.get(request["id"])["status"] == "AWAITING_APPROVAL",
                        }
                    )
                else:
                    checks.append(
                        {
                            "check": "sandbox is active",
                            "passed": store.get(request["id"])["status"] == "ACTIVE",
                        }
                    )
                    clock[0] += 61
                    worker.tick()
                    if name == "cleanup-retry":
                        checks.append(
                            {
                                "check": "cleanup failure recorded",
                                "passed": store.get(request["id"])["status"] == "CLEANUP_FAILED",
                            }
                        )
                        clock[0] += settings.cleanup_retry_seconds + 1
                        worker.tick()
                    checks.append(
                        {
                            "check": "expired resource removed",
                            "passed": store.get(request["id"])["status"] == "DESTROYED",
                        }
                    )
            checks.append({"check": "audit chain verifies", "passed": store.verify_audit()})
            events = [item["event"]["action"] for item in store.history(request["id"])]
        finally:
            # Replays have isolated records and unique resources; leave no replay infrastructure behind.
            infrastructure.wrapped.destroy(store.get(request["id"]))
    return {
        "scenario": name,
        "description": SCENARIOS[name],
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "events": events,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "environment": "local AWS emulator",
        "faults": "injected test faults" if name in {"failure", "cleanup-retry"} else "none",
    }
