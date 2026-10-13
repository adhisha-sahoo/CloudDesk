import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

from clouddesk.jenkins_adapter import JenkinsInfrastructure
from clouddesk.models import Actor, CreateRequest
from clouddesk.servicenow import ServiceNow
from clouddesk.slack_integration import verify_signature


def test_slack_signature_freshness_and_body_integrity():
    secret, timestamp, body = "test-signing-secret", str(int(time.time())), b"command=%2Fclouddesk"
    signature = (
        "v0="
        + hmac.new(
            secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
        ).hexdigest()
    )
    assert verify_signature(secret, timestamp, signature, body)
    assert not verify_signature(secret, timestamp, signature, body + b"&evil=1")
    assert not verify_signature(secret, timestamp, signature, body, int(timestamp) + 301)
    assert not verify_signature(secret, "invalid", signature, body)


def test_signed_slack_request_is_queued_not_executed(api, settings):
    client, app = api
    settings.slack_team_id = "TTEST123"
    settings.slack_signing_secret = "test-signing-secret"
    body = urlencode(
        {
            "team_id": "TTEST123",
            "user_id": "UTEST123",
            "channel_id": "CTEST123",
            "trigger_id": "trigger-one",
            "text": "create slack-demo duration=15m",
        }
    ).encode()
    timestamp = str(int(time.time()))
    signature = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode(),
            b"v0:" + timestamp.encode() + b":" + body,
            hashlib.sha256,
        ).hexdigest()
    )
    headers = {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    response = client.post("/slack/events", content=body, headers=headers)
    assert response.status_code == 200
    assert app.state.service.store.list() == []  # No slow work before acknowledgement.
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    with app.state.service.store.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM slack_inbox").fetchone()[0] == 1
    app.state.worker.tick()
    assert len(app.state.service.store.list()) == 1


def test_slack_wrong_workspace_and_bridge_token_rejected(api, settings):
    client, app = api
    settings.slack_team_id = "TALLOWED"
    data = {
        "envelope_id": "env-1",
        "payload": {"team_id": "TOTHER", "user_id": "U123", "text": "help"},
    }
    assert client.post("/api/integrations/slack/socket", json=data).status_code == 401
    assert (
        client.post(
            "/api/integrations/slack/socket",
            json=data,
            headers={"Authorization": "Bearer " + settings.bridge_token},
        ).status_code
        == 403
    )
    assert client.post("/slack/events", content=b"arbitrary").status_code == 401
    assert app.state.service.store.list() == []


def test_old_slack_button_cannot_approve_a_new_plan(api, settings):
    _, app = api
    settings.slack_team_id, settings.slack_approvers = "TTEST", "UREVIEWER"
    actor = Actor("slack:TTEST:UOWNER", "requester")
    record, _ = app.state.service.create(actor, CreateRequest(slug="stale-slack"), "button")
    app.state.worker.tick()
    old_digest = "0" * 64
    payload = {
        "type": "block_actions",
        "team": {"id": "TTEST"},
        "user": {"id": "UREVIEWER"},
        "actions": [
            {
                "action_id": "approve",
                "value": json.dumps({"id": record["id"], "digest": old_digest}),
            }
        ],
    }
    app.state.slack.process(payload, "stale-click")
    assert app.state.service.store.get(record["id"])["status"] == "AWAITING_APPROVAL"


def test_jenkins_remote_api_parameters_queue_and_artifact(settings):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("buildWithParameters"):
            params = parse_qs(request.content.decode())
            assert params["ACTION"] == ["plan"]
            assert json.loads(params["REQUEST_JSON"][0])["id"] == "a" * 32
            return httpx.Response(
                201, headers={"Location": settings.jenkins_url + "/queue/item/1/"}
            )
        if request.url.path == "/queue/item/1/api/json":
            return httpx.Response(
                200, json={"executable": {"url": settings.jenkins_url + "/job/clouddesk/1/"}}
            )
        if request.url.path == "/job/clouddesk/1/api/json":
            return httpx.Response(200, json={"building": False, "result": "SUCCESS"})
        if request.url.path.endswith("artifact/result.json"):
            return httpx.Response(200, json={"digest": "b" * 64, "changes": []})
        raise AssertionError(request.url.path)

    with httpx.Client(
        base_url=settings.jenkins_url, transport=httpx.MockTransport(handler)
    ) as client:
        adapter = JenkinsInfrastructure(settings, client)
        result = adapter.plan(
            {"id": "a" * 32, "slug": "api-test", "owner": "test", "ttl_minutes": 15}
        )
    assert result["digest"] == "b" * 64
    assert "/job/clouddesk/1/artifact/result.json" in paths


def test_jenkins_rejects_external_queue_url(settings):
    with httpx.Client(
        base_url=settings.jenkins_url,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                201, headers={"Location": "https://evil.example/queue/item/1/"}
            )
        ),
    ) as client:
        with pytest.raises(RuntimeError):
            JenkinsInfrastructure(settings, client).plan(
                {"id": "a" * 32, "slug": "safe-name", "owner": "test", "ttl_minutes": 1}
            )


def test_jenkins_timeout_requests_queue_cancellation(settings):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("buildWithParameters"):
            return httpx.Response(
                201, headers={"Location": settings.jenkins_url + "/queue/item/1/"}
            )
        return httpx.Response(200, json={})

    with httpx.Client(
        base_url=settings.jenkins_url, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(TimeoutError):
            JenkinsInfrastructure(settings, client, timeout=0).plan(
                {"id": "a" * 32, "slug": "safe-name", "owner": "test", "ttl_minutes": 1}
            )
    assert "/queue/cancelItem" in calls


def test_servicenow_creates_and_then_updates_correlated_ticket(settings):
    calls, stored = [], []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            assert request.url.params["sysparm_query"] == "correlation_id=clouddesk:" + "a" * 32
            return httpx.Response(200, json={"result": stored})
        stored[:] = [{"sys_id": "b" * 32}]
        return httpx.Response(200, json={"result": stored[0]})

    with httpx.Client(
        base_url="https://devtest.service-now.com", transport=httpx.MockTransport(handler)
    ) as client:
        adapter = ServiceNow(settings, client)
        record = {
            "id": "a" * 32,
            "slug": "ticket-demo",
            "reason": "Test local ticket integration",
            "status": "ACTIVE",
        }
        assert adapter.sync(record) == "b" * 32
        assert adapter.sync({**record, "status": "DESTROYED"}) == "b" * 32
    assert calls == ["GET", "POST", "GET", "PATCH"]
