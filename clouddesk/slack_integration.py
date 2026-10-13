import hashlib
import hmac
import json
import re
import shlex
import time

import httpx

from .models import Actor, CreateRequest, DomainError
from .store import canonical


def verify_signature(secret, timestamp, signature, body: bytes, now=None):
    now = time.time() if now is None else now
    try:
        if abs(now - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False
    expected = (
        "v0="
        + hmac.new(
            secret.encode(), b"v0:" + str(timestamp).encode() + b":" + body, hashlib.sha256
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature or "")


class Slack:
    def __init__(self, settings, service, assistant, client=None):
        self.settings, self.service, self.assistant = settings, service, assistant
        self.client = client or httpx.Client(
            base_url="https://slack.com/api", timeout=10, follow_redirects=False, trust_env=False
        )

    def actor(self, payload):
        team = payload.get("team_id") or payload.get("team", {}).get("id")
        user = payload.get("user_id") or payload.get("user", {}).get("id")
        if (
            not self.settings.slack_team_id
            or team != self.settings.slack_team_id
            or not re.fullmatch(r"[UW][A-Z0-9]+", user or "")
        ):
            raise DomainError(403, "Slack workspace or user is not allowed")
        return Actor(
            f"slack:{team}:{user}",
            "approver" if user in self.settings.approver_ids else "requester",
        )

    def enqueue(self, payload, key):
        self.actor(payload)
        with self.service.store.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO slack_inbox(key,payload_json,due_at) VALUES(?,?,?)",
                (key, canonical(payload), self.service.clock()),
            )

    def api(self, method, payload):
        if not self.settings.slack_bot_token:
            return
        response = self.client.post(
            "/" + method,
            headers={"Authorization": "Bearer " + self.settings.slack_bot_token},
            json=payload,
        )
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("Slack API rejected the message")

    def process(self, payload, key):
        actor = self.actor(payload)
        channel = payload.get("channel_id") or payload.get("channel", {}).get("id")
        user = actor.id.rsplit(":", 1)[-1]
        try:
            if payload.get("type") == "block_actions":
                action = payload["actions"][0]
                reviewed = json.loads(action["value"])
                request_id = reviewed["id"]
                record = self.service.get(actor, request_id)
                if action["action_id"] == "approve":
                    self.service.approve(actor, request_id, reviewed["digest"])
                elif action["action_id"] == "reject":
                    self.service.reject(actor, request_id)
                else:
                    raise DomainError(422, "Unknown Slack action")
                text = f"Request {request_id}: {self.service.get(actor, request_id)['status']}"
            else:
                words = shlex.split(payload.get("text", ""))
                command = words[0] if words else "help"
                if command == "create" and len(words) in {2, 3}:
                    duration = words[2].removeprefix("duration=") if len(words) == 3 else "30m"
                    match = re.fullmatch(r"([0-9]{1,3})(m|h)", duration)
                    if not match:
                        raise DomainError(422, "Use duration=30m or duration=2h")
                    ttl = int(match[1]) * (60 if match[2] == "h" else 1)
                    record, _ = self.service.create(
                        actor, CreateRequest(slug=words[1], ttl_minutes=ttl), key, channel
                    )
                    text = f"Request {record['id']} created. Its plan will be sent for review."
                elif command in {"status", "approve", "reject", "destroy", "retry"} and len(
                    words
                ) == (3 if command == "approve" else 2):
                    record = self.service.get(actor, words[1])
                    if command == "approve":
                        record = self.service.approve(actor, record["id"], words[2])
                    elif command != "status":
                        record = getattr(self.service, command)(actor, record["id"])
                    text = f"Request {record['id']}: {record['status']}\nPlan digest: {record['plan_digest']}"
                elif command == "ask" and len(words) > 1:
                    answer = self.assistant.ask(" ".join(words[1:]))
                    text = (
                        answer["answer"]
                        + "\n"
                        + "\n".join(step["text"] for step in answer["steps"])
                    )
                    text += "\n" + "\n".join(
                        f"{source['title']}: {source['url']}" for source in answer["sources"]
                    )
                else:
                    text = "Commands: create NAME duration=30m; status ID; approve ID DIGEST; reject ID; destroy ID; retry ID; ask QUESTION"
        except (DomainError, ValueError, KeyError, IndexError) as error:
            text = (
                error.message
                if isinstance(error, DomainError)
                else "Invalid command. Use /clouddesk help."
            )
        if channel:
            self.api("chat.postEphemeral", {"channel": channel, "user": user, "text": text})

    def notify(self, request):
        if not request["owner"].startswith("slack:"):
            return
        if request["channel_id"]:
            self.api(
                "chat.postEphemeral",
                {
                    "channel": request["channel_id"],
                    "user": request["owner"].rsplit(":", 1)[-1],
                    "text": f"CloudDesk {request['slug']} ({request['id']}): {request['status']}",
                },
            )
        if request["status"] == "AWAITING_APPROVAL" and self.settings.slack_approval_channel:
            plan = request["plan"]
            self.api(
                "chat.postMessage",
                {
                    "channel": self.settings.slack_approval_channel,
                    "text": f"Review CloudDesk request {request['id']}",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "plain_text",
                                "text": f"{request['slug']} • {request['ttl_minutes']} minutes\nEnvironment: local AWS emulator\nPlan: {plan['engine']}\nChanges: {json.dumps(plan['changes'])}\nDigest: {request['plan_digest']}",
                            },
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "action_id": action,
                                    "text": {"type": "plain_text", "text": action.title()},
                                    "value": canonical(
                                        {"id": request["id"], "digest": request["plan_digest"]}
                                    ),
                                }
                                for action in ("approve", "reject")
                            ],
                        },
                    ],
                },
            )
