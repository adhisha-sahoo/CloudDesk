import hashlib
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import require_local_url
from .store import canonical

TEMPLATE_VERSION = "storage-sandbox-v1"
ACCOUNT = "123456789012"


def names(request: dict) -> tuple[str, str]:
    import re

    if not re.fullmatch(r"[0-9a-f]{32}", request["id"]):
        raise ValueError("Invalid request identifier")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,29}", request["slug"]):
        raise ValueError("Invalid sandbox name")
    return f"cd-{request['slug']}-{request['id'][:12]}", f"cd-{request['id']}"


def role_policy(bucket: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": f"arn:aws:s3:::{bucket}"},
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": f"arn:aws:s3:::{bucket}/*",
            },
        ],
    }


def preview(request: dict) -> dict:
    bucket, role = names(request)
    document = {
        "template": TEMPLATE_VERSION,
        "request_id": request["id"],
        "owner": request["owner"],
        "bucket": bucket,
        "role": role,
        "ttl_minutes": request["ttl_minutes"],
        "controls": ["AES256 encryption", "all public access blocked", "bucket-scoped IAM policy"],
        "changes": [
            {"type": "aws_s3_bucket", "name": bucket, "action": "create or reconcile"},
            {"type": "aws_s3_bucket_public_access_block", "name": bucket, "action": "configure"},
            {
                "type": "aws_s3_bucket_server_side_encryption_configuration",
                "name": bucket,
                "action": "configure",
            },
            {"type": "aws_iam_role", "name": role, "action": "create or reconcile"},
            {"type": "aws_iam_role_policy", "name": role, "action": "configure"},
        ],
        "policy": role_policy(bucket),
        "environment": "local AWS emulator",
        "engine": "AWS SDK API preview",
    }
    return {**document, "digest": hashlib.sha256(canonical(document).encode()).hexdigest()}


class ApiInfrastructure:
    def __init__(self, endpoint: str):
        self.endpoint = require_local_url(endpoint, {"localhost", "127.0.0.1", "moto"})
        session = boto3.Session(
            aws_access_key_id="testing",
            aws_secret_access_key="testing",  # noqa: S106 - fixed fake emulator credentials
            region_name="us-east-1",
        )
        config = Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 2},
            s3={"addressing_style": "path"},
        )
        self.s3 = session.client("s3", endpoint_url=self.endpoint, config=config)
        self.iam = session.client("iam", endpoint_url=self.endpoint, config=config)

    def plan(self, request: dict) -> dict:
        return preview(request)

    def _owned_bucket(self, request: dict, bucket: str) -> bool:
        try:
            self.s3.head_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"404", "NoSuchBucket", "NotFound"}:
                return False
            raise
        try:
            tags = self.s3.get_bucket_tagging(Bucket=bucket)["TagSet"]
        except ClientError as error:
            raise RuntimeError(
                "Existing bucket has no verifiable CloudDesk ownership tag"
            ) from error
        if not any(t["Key"] == "CloudDeskRequest" and t["Value"] == request["id"] for t in tags):
            raise RuntimeError("Refusing to modify a resource owned by another request")
        return True

    def apply(self, request: dict) -> dict:
        expected = preview(request)["digest"]
        if request["plan_digest"] != expected:
            raise RuntimeError("Approved plan does not match the current resource template")
        bucket, role = names(request)
        tags = [
            {"Key": "CloudDeskRequest", "Value": request["id"]},
            {"Key": "Owner", "Value": request["owner"]},
        ]
        if not self._owned_bucket(request, bucket):
            self.s3.create_bucket(Bucket=bucket)
            self.s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": tags})
        self.s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        self.s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )
        trust = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        try:
            self.iam.create_role(
                RoleName=role, AssumeRolePolicyDocument=canonical(trust), Tags=tags
            )
        except self.iam.exceptions.EntityAlreadyExistsException:
            existing = self.iam.get_role(RoleName=role)["Role"].get("Tags", [])
            if not any(
                t["Key"] == "CloudDeskRequest" and t["Value"] == request["id"] for t in existing
            ):
                raise RuntimeError("Existing IAM role belongs to another request") from None
        self.iam.put_role_policy(
            RoleName=role,
            PolicyName="sandbox-access",
            PolicyDocument=canonical(role_policy(bucket)),
        )
        self.verify(request)
        return {
            "bucket": bucket,
            "role": role,
            "endpoint": self.endpoint,
            "environment": "local AWS emulator",
        }

    def verify(self, request: dict):
        bucket, role = names(request)
        if not self._owned_bucket(request, bucket):
            raise RuntimeError("The approved bucket is absent")
        controls = self.s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        if not all(
            controls.get(key) is True
            for key in (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
        ):
            raise RuntimeError("Public-access protection is incomplete")
        rules = self.s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"][
            "Rules"
        ]
        if not any(
            rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") == "AES256"
            for rule in rules
        ):
            raise RuntimeError("Expected bucket encryption is absent")
        role_data = self.iam.get_role(RoleName=role)["Role"]
        if not any(
            tag["Key"] == "CloudDeskRequest" and tag["Value"] == request["id"]
            for tag in role_data.get("Tags", [])
        ):
            raise RuntimeError("IAM role ownership is not verified")
        policy = self.iam.get_role_policy(RoleName=role, PolicyName="sandbox-access")[
            "PolicyDocument"
        ]
        if canonical(policy) != canonical(role_policy(bucket)):
            raise RuntimeError("Scoped IAM policy differs from the approved template")

    def destroy(self, request: dict) -> dict:
        bucket, role = names(request)
        if self._owned_bucket(request, bucket):
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    result = self.s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
                    if result.get("Errors"):
                        raise RuntimeError("Some sandbox objects could not be removed")
            self.s3.delete_bucket(Bucket=bucket)
        try:
            existing = self.iam.get_role(RoleName=role)["Role"].get("Tags", [])
            if not any(
                t["Key"] == "CloudDeskRequest" and t["Value"] == request["id"] for t in existing
            ):
                raise RuntimeError("Refusing to remove an IAM role without matching ownership")
            try:
                self.iam.delete_role_policy(RoleName=role, PolicyName="sandbox-access")
            except self.iam.exceptions.NoSuchEntityException:
                pass  # A partial apply may have created the role but not its policy.
            self.iam.delete_role(RoleName=role)
        except self.iam.exceptions.NoSuchEntityException:
            pass
        return {"destroyed": True, "bucket": bucket, "role": role}

    def restore(self, request: dict):
        # Moto is ephemeral. Recreate active API-mode resources after a local restart.
        return self.apply(request)


def endpoint_port(endpoint: str) -> int:
    return urlparse(endpoint).port or 5000
