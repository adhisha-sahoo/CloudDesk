from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


def require_local_url(value: str, names: set[str]) -> str:
    url = urlparse(value)
    if url.scheme != "http" or url.hostname not in names or url.username or url.password:
        raise ValueError("Only explicit local HTTP endpoints are supported in this free edition")
    if url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("Endpoint must be a local server origin without a path or query")
    return value.rstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLOUDDESK_", env_file=".env", extra="ignore")
    data_dir: Path = Path(".data")
    requester_token: str = ""
    approver_token: str = ""
    bridge_token: str = ""
    embedded_moto: bool = True
    aws_endpoint: str = "http://127.0.0.1:5000"
    executor: Literal["api", "terraform", "jenkins"] = "api"
    terraform_bin: str = "terraform"
    jenkins_url: str = "http://127.0.0.1:8080"
    jenkins_user: str = "admin"
    jenkins_token: str = ""
    jenkins_job: str = "clouddesk"
    worker_enabled: bool = True
    worker_interval: float = 1.0
    cleanup_retry_seconds: float = 5.0
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_signing_secret: str = ""
    slack_team_id: str = ""
    slack_approvers: str = ""
    slack_approval_channel: str = ""
    assistant_mode: Literal["extractive", "ollama"] = "extractive"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"
    servicenow_url: str = ""
    servicenow_user: str = ""
    servicenow_password: str = ""

    @field_validator("aws_endpoint")
    @classmethod
    def local_aws(cls, value: str) -> str:
        return require_local_url(value, {"localhost", "127.0.0.1", "moto"})

    @field_validator("ollama_url")
    @classmethod
    def local_ollama(cls, value: str) -> str:
        return require_local_url(value, {"localhost", "127.0.0.1", "ollama"})

    @field_validator("jenkins_url")
    @classmethod
    def local_jenkins(cls, value: str) -> str:
        return require_local_url(value, {"localhost", "127.0.0.1", "jenkins"})

    @field_validator("jenkins_job")
    @classmethod
    def safe_job(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", value):
            raise ValueError("Use a simple Jenkins job name")
        return value

    @field_validator("servicenow_url")
    @classmethod
    def service_now_instance(cls, value: str) -> str:
        if not value:
            return value
        url = urlparse(value)
        if (
            url.scheme != "https"
            or not (url.hostname or "").endswith(".service-now.com")
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError("Provide your own HTTPS ServiceNow instance origin")
        return value.rstrip("/")

    def validate_credentials(self) -> None:
        tokens = [self.requester_token, self.approver_token, self.bridge_token]
        if any(len(token) < 24 for token in tokens) or len(set(tokens)) != 3:
            raise ValueError(
                "Run python scripts/bootstrap.py to create three distinct local tokens"
            )
        if self.executor == "jenkins" and not self.jenkins_token:
            raise ValueError("Jenkins execution needs your Jenkins API token")

    @property
    def approver_ids(self) -> set[str]:
        return {item.strip() for item in self.slack_approvers.split(",") if item.strip()}
