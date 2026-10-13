import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from botocore.exceptions import ClientError

from clouddesk.infrastructure import ApiInfrastructure, names
from clouddesk.models import Actor, CreateRequest, DomainError
from clouddesk.replay import SCENARIOS, run_scenario
from clouddesk.service import Service
from clouddesk.store import Store
from clouddesk.worker import Worker


def create(api, headers, key="test-key"):
    client, app = api
    response = client.post(
        "/api/requests",
        json={"slug": "test-sandbox", "ttl_minutes": 1, "reason": "Integration test"},
        headers={**headers["requester"], "Idempotency-Key": key},
    )
    assert response.status_code == 201
    app.state.worker.tick()
    return client.get("/api/requests/" + response.json()["id"], headers=headers["requester"]).json()


def test_api_requires_auth(api):
    client, _ = api
    assert client.get("/api/requests").status_code == 401
    assert client.get("/api/health").json()["environment"] == "local AWS emulator"


def test_full_lifecycle_and_security_configuration(api, headers, settings):
    client, app = api
    record = create(api, headers)
    assert record["status"] == "AWAITING_APPROVAL"
    assert (
        client.post(
            f"/api/requests/{record['id']}/approve",
            json={"plan_digest": record["plan_digest"]},
            headers=headers["requester"],
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/requests/{record['id']}/approve",
            json={"plan_digest": "0" * 64},
            headers=headers["approver"],
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/requests/{record['id']}/approve",
            json={"plan_digest": record["plan_digest"]},
            headers=headers["approver"],
        ).status_code
        == 200
    )
    app.state.worker.tick()
    active = client.get(f"/api/requests/{record['id']}", headers=headers["requester"]).json()
    assert active["status"] == "ACTIVE"
    infra = ApiInfrastructure(settings.aws_endpoint)
    bucket, role = names(active)
    assert all(
        infra.s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"].values()
    )
    assert (
        infra.s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"][
            0
        ]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
        == "AES256"
    )
    policy = infra.iam.get_role_policy(RoleName=role, PolicyName="sandbox-access")["PolicyDocument"]
    assert policy["Statement"][1]["Resource"] == f"arn:aws:s3:::{bucket}/*"
    infra.s3.put_object(Bucket=bucket, Key="test-object.txt", Body=b"owned test content")
    assert (
        client.post(
            f"/api/requests/{record['id']}/destroy", json={}, headers=headers["requester"]
        ).status_code
        == 200
    )
    app.state.worker.tick()
    assert app.state.service.store.get(record["id"])["status"] == "DESTROYED"
    with pytest.raises(ClientError):
        infra.s3.head_bucket(Bucket=bucket)
    with pytest.raises(infra.iam.exceptions.NoSuchEntityException):
        infra.iam.get_role(RoleName=role)
    metrics = client.get("/api/metrics", headers=headers["approver"]).json()
    assert metrics["measured_provisions"] == 1
    assert metrics["p95_provision_seconds"] >= 0
    assert metrics["audit_chain_valid"]


def test_duplicate_and_conflicting_keys(api, headers):
    client, _ = api
    body = {"slug": "same-request", "ttl_minutes": 15}
    auth = {**headers["requester"], "Idempotency-Key": "same"}
    first = client.post("/api/requests", json=body, headers=auth)
    repeat = client.post("/api/requests", json=body, headers=auth)
    assert first.status_code == 201 and repeat.status_code == 200
    assert first.json()["id"] == repeat.json()["id"]
    assert (
        client.post("/api/requests", json={**body, "ttl_minutes": 30}, headers=auth).status_code
        == 409
    )


def test_concurrent_duplicate_requests(settings):
    service = Service(Store(settings.data_dir / "parallel.db"))
    actor = Actor("parallel-user", "requester")
    spec = CreateRequest(slug="parallel-demo")
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(lambda _: service.create(actor, spec, "same-concurrent-key"), range(20))
        )
    assert len({record["id"] for record, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    with service.store.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


@pytest.mark.parametrize(
    "body",
    [
        {"slug": "../escape"},
        {"slug": "UPPERCASE"},
        {"slug": "aa"},
        {"slug": "valid-name", "ttl_minutes": 121},
        {"slug": "valid-name", "ttl_minutes": 0},
        {"slug": "valid-name", "ttl_minutes": "30"},
        {"slug": "valid-name", "role": "approver"},
    ],
)
def test_reject_invalid_specs(api, headers, body):
    client, _ = api
    assert (
        client.post(
            "/api/requests",
            json=body,
            headers={**headers["requester"], "Idempotency-Key": "validation"},
        ).status_code
        == 422
    )


def test_missing_key_and_large_payload(api, headers):
    client, _ = api
    assert (
        client.post(
            "/api/requests", json={"slug": "missing-key"}, headers=headers["requester"]
        ).status_code
        == 422
    )
    assert (
        client.post("/api/requests", content=b"x" * 65537, headers=headers["requester"]).status_code
        == 413
    )


def test_visibility_enforced_at_service(settings):
    service = Service(Store(settings.data_dir / "visibility.db"))
    record, _ = service.create(
        Actor("alice", "requester"), CreateRequest(slug="alice-demo"), "owner-key"
    )
    bob = Actor("bob", "requester")
    assert service.list(bob) == []
    with pytest.raises(DomainError) as error:
        service.get(bob, record["id"])
    assert error.value.status == 404


def test_rejection_is_terminal(api, headers):
    client, app = api
    record = create(api, headers)
    assert (
        client.post(
            f"/api/requests/{record['id']}/reject", json={}, headers=headers["approver"]
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/requests/{record['id']}/approve",
            json={"plan_digest": record["plan_digest"]},
            headers=headers["approver"],
        ).status_code
        == 409
    )
    assert app.state.service.store.get(record["id"])["status"] == "REJECTED"


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_replay_executes_against_local_aws(settings, scenario):
    result = run_scenario(scenario, settings)
    assert result["passed"]
    assert result["duration_ms"] is not None


def test_audit_detects_modification(api, headers):
    _, app = api
    create(api, headers)
    store = app.state.service.store
    assert store.verify_audit()
    with store.transaction() as conn:
        conn.execute("UPDATE audit SET event_json=? WHERE seq=1", (json.dumps({"tampered": True}),))
    assert not store.verify_audit()


def test_interrupted_job_recovered_without_duplicate_resource(settings):
    store = Store(settings.data_dir / "restart.db")
    service = Service(store)
    infra = ApiInfrastructure(settings.aws_endpoint)
    worker = Worker(service, infra, settings)
    record, _ = service.create(
        Actor("restart-owner", "requester"), CreateRequest(slug="restart-demo"), "restart"
    )
    worker.tick()
    service.approve(
        Actor("reviewer", "approver"), record["id"], store.get(record["id"])["plan_digest"]
    )
    job = store.claim("jobs", service.clock())
    infra.apply(store.get(record["id"]))  # Simulate a crash just after provider success.
    store.recover_jobs()
    worker.tick()
    active = store.get(record["id"])
    assert active["status"] == "ACTIVE"
    bucket, _ = names(active)
    assert sum(item["Name"] == bucket for item in infra.s3.list_buckets()["Buckets"]) == 1
    infra.destroy(active)
    assert job["action"] == "apply"


def test_partial_iam_apply_can_be_cleaned(settings):
    infra = ApiInfrastructure(settings.aws_endpoint)
    service = Service(Store(settings.data_dir / "partial.db"))
    record, _ = service.create(
        Actor("partial-owner", "requester"), CreateRequest(slug="partial-demo"), "partial"
    )
    _, role = names(record)
    infra.iam.create_role(
        RoleName=role,
        AssumeRolePolicyDocument='{"Version":"2012-10-17","Statement":[]}',
        Tags=[{"Key": "CloudDeskRequest", "Value": record["id"]}],
    )
    infra.destroy(record)
    with pytest.raises(infra.iam.exceptions.NoSuchEntityException):
        infra.iam.get_role(RoleName=role)


def test_does_not_destroy_unowned_bucket(settings):
    infra = ApiInfrastructure(settings.aws_endpoint)
    service = Service(Store(settings.data_dir / "ownership.db"))
    record, _ = service.create(
        Actor("owner", "requester"), CreateRequest(slug="ownership-demo"), "ownership"
    )
    bucket, _ = names(record)
    infra.s3.create_bucket(Bucket=bucket)
    infra.s3.put_bucket_tagging(
        Bucket=bucket,
        Tagging={"TagSet": [{"Key": "CloudDeskRequest", "Value": "some-other-request"}]},
    )
    with pytest.raises(RuntimeError):
        infra.destroy(record)
    infra.s3.head_bucket(Bucket=bucket)
    infra.s3.delete_bucket(Bucket=bucket)
