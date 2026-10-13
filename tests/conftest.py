import socket

import pytest
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer

from clouddesk.app import create_app
from clouddesk.config import Settings
from clouddesk.infrastructure import ApiInfrastructure


@pytest.fixture(scope="session")
def moto_endpoint():
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    _, port = server.get_host_and_port()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def settings(tmp_path, moto_endpoint):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedded_moto=False,
        worker_enabled=False,
        aws_endpoint=moto_endpoint,
        requester_token="requester-test-credential-123456789",
        approver_token="approver-test-credential-123456789",
        bridge_token="bridge-test-credential-123456789",
        cleanup_retry_seconds=0.1,
    )


@pytest.fixture
def api(settings):
    app = create_app(settings, ApiInfrastructure(settings.aws_endpoint))
    with TestClient(app) as client:
        yield client, app


@pytest.fixture
def headers(settings):
    return {
        "requester": {"Authorization": "Bearer " + settings.requester_token},
        "approver": {"Authorization": "Bearer " + settings.approver_token},
    }


def unused_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]
