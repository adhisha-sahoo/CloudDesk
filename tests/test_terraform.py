import hashlib
import os
import shutil

import pytest

from clouddesk.infrastructure import ApiInfrastructure, names
from clouddesk.models import Actor, CreateRequest
from clouddesk.service import Service
from clouddesk.store import Store
from clouddesk.terraform_runner import TerraformInfrastructure

pytestmark = pytest.mark.terraform


@pytest.mark.skipif(
    os.getenv("RUN_TERRAFORM") != "1" or not shutil.which("terraform"),
    reason="Set RUN_TERRAFORM=1 and install Terraform to execute infrastructure tests",
)
def test_actual_saved_plan_apply_destroy(settings):
    runner = TerraformInfrastructure(settings.aws_endpoint, settings.data_dir / "terraform")
    service = Service(Store(settings.data_dir / "tf.sqlite3"))
    record, _ = service.create(
        Actor("tf-test-owner", "requester"), CreateRequest(slug="terraform-demo"), "terraform"
    )
    plan = runner.plan(record)
    assert plan["engine"] == "Terraform saved plan"
    assert len(plan["changes"]) == 5
    record["plan_digest"] = plan["digest"]
    result = runner.apply(record)
    bucket, role = names(record)
    assert result["bucket"] == bucket and result["role"] == role
    api = ApiInfrastructure(settings.aws_endpoint)
    assert api.s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"][
        "BlockPublicPolicy"
    ]
    assert (
        api.s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"][
            0
        ]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
        == "AES256"
    )
    # Interrupted worker retry sees completed state instead of applying an unreviewed replacement plan.
    assert runner.apply(record)["bucket"] == bucket
    assert runner.destroy(record)["destroyed"]
    assert runner.outputs(runner.directory(record)) == {}


def test_tampered_saved_plan_never_applies(settings):
    runner = TerraformInfrastructure(settings.aws_endpoint, settings.data_dir / "tamper")
    record = {
        "id": "f" * 32,
        "slug": "tamper-demo",
        "owner": "tf-owner",
        "ttl_minutes": 1,
        "plan_digest": hashlib.sha256(b"approved bytes").hexdigest(),
    }
    (runner.directory(record) / "approved.tfplan").write_bytes(b"different bytes")
    with pytest.raises(RuntimeError, match="differs"):
        runner.apply(record)
