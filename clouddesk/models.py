from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class Actor:
    id: str
    role: Literal["requester", "approver"]


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{2,29}$")
    ttl_minutes: int = Field(default=30, ge=1, le=120, strict=True)
    reason: str = Field(default="Development sandbox", min_length=3, max_length=300)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1500)


class DomainError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
