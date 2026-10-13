"""Create local credentials without replacing an existing configuration."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    print(".env already exists; no configuration was overwritten.")
else:
    content = (root / ".env.example").read_text()
    values = {
        key: secrets.token_urlsafe(32)
        for key in [
            "CLOUDDESK_REQUESTER_TOKEN",
            "CLOUDDESK_APPROVER_TOKEN",
            "CLOUDDESK_BRIDGE_TOKEN",
            "JENKINS_ADMIN_PASSWORD",
        ]
    }
    for key, value in values.items():
        content = content.replace(key + "=\n", key + "=" + value + "\n")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
    print("Created .env with separate requester, approver, and bridge credentials.")
    print(
        "Read your API tokens from .env and enter them in the local dashboard. Never commit .env."
    )
