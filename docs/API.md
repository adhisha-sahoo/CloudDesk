# API examples

Start the backend and load your own tokens from `.env`. The examples below use environment variables containing those tokens. Do not paste actual credentials into the repository or public issue comments.

## Python example (cross-platform)

Run from the project root after installing the project:

```python
import time
import uuid
import httpx
from clouddesk.config import Settings

settings = Settings()
requester = {"Authorization": "Bearer " + settings.requester_token}
approver = {"Authorization": "Bearer " + settings.approver_token}

with httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False) as client:
    created = client.post(
        "/api/requests",
        headers={**requester, "Idempotency-Key": str(uuid.uuid4())},
        json={"slug": "api-demo", "ttl_minutes": 1, "reason": "Verify the API workflow"},
    )
    created.raise_for_status()
    request_id = created.json()["id"]
    for _ in range(30):
        response = client.get("/api/requests/" + request_id, headers=requester)
        response.raise_for_status()
        record = response.json()
        if record["status"] == "AWAITING_APPROVAL":
            break
        if record["status"] == "FAILED":
            raise RuntimeError(record["error"])
        time.sleep(1)
    else:
        raise TimeoutError("Plan was not ready within 30 seconds")
    print(record["plan"])  # Inspect these changes before approving them.
    approval = client.post(
        f"/api/requests/{request_id}/approve",
        headers=approver,
        json={"plan_digest": record["plan_digest"]},
    )
    approval.raise_for_status()
    print("Approved request:", request_id)
```

## Error contract

| Status | Meaning |
| --- | --- |
| 401 | Missing or invalid bearer token/signature |
| 403 | Actor is not permitted to approve or run replays |
| 404 | Missing request, or another requester's inaccessible request |
| 409 | Conflicting idempotency payload, stale approval, or invalid state transition |
| 411 | Modifying HTTP request lacks Content-Length |
| 413 | Body exceeds 64 KiB |
| 422 | Invalid request fields, TTL, Slack command, or idempotency key |

An SDK/provider failure is recorded as a request state with a sanitized error type. Complete Terraform command diagnostics are written to its local request-specific `last-error.log`, never embedded in the public site.

## Metrics

`GET /api/metrics` returns metrics scoped to the authenticated actor's visible requests:

- total requests and counts by state;
- number of successfully measured provisioning runs;
- p95 latency from approval to ACTIVE, calculated using the nearest-rank method;
- whole audit-chain verification result;
- explicit environment label.

No time-saving percentages or cloud cost reductions are fabricated. Browser demonstration mode deliberately shows no measured provisioning p95.
