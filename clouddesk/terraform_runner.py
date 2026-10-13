import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import ROOT, require_local_url
from .infrastructure import names, preview
from .store import canonical

ALLOWED_TYPES = {
    "aws_s3_bucket",
    "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_server_side_encryption_configuration",
    "aws_iam_role",
    "aws_iam_role_policy",
}


class TerraformInfrastructure:
    def __init__(self, endpoint: str, work_root: Path, executable="terraform"):
        self.endpoint = require_local_url(endpoint, {"localhost", "127.0.0.1", "moto"})
        self.work_root = work_root
        self.executable = executable

    def directory(self, request: dict) -> Path:
        names(request)
        path = self.work_root / request["id"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run(self, path, *arguments) -> str:
        env = dict(os.environ)
        # Never inherit real AWS credentials into the emulator pipeline.
        for key in list(env):
            if key.startswith("AWS_"):
                del env[key]
        env.update(
            AWS_ACCESS_KEY_ID="testing",
            AWS_SECRET_ACCESS_KEY="testing",  # noqa: S106 - fake emulator credentials
            AWS_EC2_METADATA_DISABLED="true",
            TF_IN_AUTOMATION="1",
        )  # noqa: S106 - fake emulator credentials
        result = subprocess.run(  # noqa: S603 - fixed arguments, trusted local executable, shell disabled
            [self.executable, *arguments],
            cwd=path,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode:
            (path / "last-error.log").write_text(result.stdout + result.stderr)
            raise RuntimeError(f"Terraform {arguments[0]} failed; see the local last-error.log")
        return result.stdout

    def plan(self, request: dict) -> dict:
        path = self.directory(request)
        shutil.copy2(ROOT / "infra" / "main.tf", path / "main.tf")
        lock = ROOT / "infra" / ".terraform.lock.hcl"
        if lock.exists():
            shutil.copy2(lock, path / ".terraform.lock.hcl")
        variables = {
            "endpoint": self.endpoint,
            "request_id": request["id"],
            "slug": request["slug"],
            "owner": request["owner"],
        }
        (path / "input.auto.tfvars.json").write_text(canonical(variables))
        self.run(path, "init", "-input=false", "-no-color")
        self.run(path, "plan", "-input=false", "-no-color", "-out=approved.tfplan")
        plan = json.loads(self.run(path, "show", "-json", "approved.tfplan"))
        changes = []
        for change in plan.get("resource_changes", []):
            if change["type"] not in ALLOWED_TYPES or change.get("mode") != "managed":
                raise RuntimeError("The infrastructure plan contains an unapproved resource type")
            actions = change["change"]["actions"]
            if "delete" in actions:
                raise RuntimeError("Provisioning plans cannot delete or replace resources")
            changes.append(
                {"type": change["type"], "name": change["address"], "action": ", ".join(actions)}
            )
        digest = hashlib.sha256((path / "approved.tfplan").read_bytes()).hexdigest()
        document = {
            **preview(request),
            "engine": "Terraform saved plan",
            "changes": changes,
            "digest": digest,
        }
        (path / "review.json").write_text(canonical(document))
        return document

    def apply(self, request: dict) -> dict:
        path = self.directory(request)
        plan = path / "approved.tfplan"
        if (
            not plan.exists()
            or hashlib.sha256(plan.read_bytes()).hexdigest() != request["plan_digest"]
        ):
            raise RuntimeError("Saved Terraform plan is absent or differs from the approved digest")
        # Applying a saved plan never silently regenerates the infrastructure changes.
        try:
            self.run(path, "apply", "-input=false", "-no-color", "approved.tfplan")
        except RuntimeError:
            # A worker interrupted just after successful apply may retry. Inspect its state,
            # rather than applying a stale plan or silently approving a replacement plan.
            outputs = self.outputs(path)
            bucket, role = names(request)
            if outputs.get("bucket") != bucket or outputs.get("role") != role:
                raise
            from .infrastructure import ApiInfrastructure

            client = ApiInfrastructure(self.endpoint)
            client.verify(request)
        from .infrastructure import ApiInfrastructure

        ApiInfrastructure(self.endpoint).verify(request)
        return {
            **self.outputs(path),
            "endpoint": self.endpoint,
            "environment": "local AWS emulator",
        }

    def outputs(self, path) -> dict:
        return {
            key: value["value"]
            for key, value in json.loads(self.run(path, "output", "-json")).items()
        }

    def destroy(self, request: dict) -> dict:
        path = self.directory(request)
        if not (path / "main.tf").exists():
            return {"destroyed": True}
        self.run(path, "destroy", "-auto-approve", "-input=false", "-no-color")
        return {"destroyed": True}
