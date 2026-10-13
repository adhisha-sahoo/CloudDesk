import pytest

from clouddesk.infrastructure import ApiInfrastructure
from clouddesk.models import Actor, CreateRequest
from clouddesk.replay import FaultInfrastructure
from clouddesk.service import Service
from clouddesk.store import Store
from clouddesk.worker import Worker


def test_replanned_partial_resources_expire_before_another_approval(settings):
    clock = [100.0]
    store = Store(settings.data_dir / "expired-retry.db")
    service = Service(store, lambda: clock[0])
    infra = FaultInfrastructure(ApiInfrastructure(settings.aws_endpoint), "apply")
    worker = Worker(service, infra, settings)
    requester, approver = Actor("retry-owner", "requester"), Actor("reviewer", "approver")
    record, _ = service.create(
        requester, CreateRequest(slug="expired-retry", ttl_minutes=1), "expire-retry"
    )
    worker.tick()
    service.approve(approver, record["id"], store.get(record["id"])["plan_digest"])
    worker.tick()
    assert store.get(record["id"])["status"] == "FAILED"
    clock[0] = 159
    service.retry(requester, record["id"])
    worker.tick()
    assert store.get(record["id"])["status"] == "AWAITING_APPROVAL"
    clock[0] = 161
    worker.tick()
    assert store.get(record["id"])["status"] == "DESTROYED"


def test_notification_outbox_keeps_each_state_snapshot(settings):
    store = Store(settings.data_dir / "notification.db")
    service = Service(store)
    sent = []
    worker = Worker(
        service,
        ApiInfrastructure(settings.aws_endpoint),
        settings,
        notifier=lambda item: sent.append(item["status"]),
    )
    service.create(Actor("notify-owner", "requester"), CreateRequest(slug="notify-demo"), "notify")
    worker.tick()
    worker.tick()
    worker.tick()
    assert sent == ["PLANNING", "AWAITING_APPROVAL"]


def test_executor_cannot_change_with_unfinished_resources(settings):
    store = Store(settings.data_dir / "engine.db")
    store.bind_executor("api")
    Service(store).create(
        Actor("engine-owner", "requester"), CreateRequest(slug="engine-demo"), "engine"
    )
    with pytest.raises(RuntimeError, match="Clean up"):
        store.bind_executor("terraform")
    store.bind_executor("api")
