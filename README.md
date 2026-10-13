# CloudDesk

[Open the live demo](https://adhisha-sahoo.github.io/AIproject/#overview) · [CI verification](https://github.com/adhisha-sahoo/AIproject/actions/workflows/ci.yml)

**Approval-based infrastructure automation, grounded troubleshooting, and an incident replay lab.**

CloudDesk turns a development sandbox request into a reviewed plan, an approved infrastructure change, and a scheduled teardown. It includes a FastAPI backend, a responsive dashboard, Slack integration, a Jenkins/Terraform executor, and a local-model troubleshooting option.

The default backend uses **real AWS SDK HTTP calls against the free Moto emulator**. It does not provision live AWS resources. The GitHub Pages site is an explicitly labeled browser demonstration; the working backend runs locally.

## Start the working backend

Requires Python 3.11 or newer. Python 3.12 is the tested version.

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on macOS/Linux, or `.venv\Scripts\Activate.ps1` in Windows PowerShell. Alternatively, invoke the virtual environment's Python executable directly.

```sh
python -m pip install -e .
python scripts/bootstrap.py
python -m uvicorn clouddesk.app:app --host 127.0.0.1 --port 8000
```

1. Open **http://127.0.0.1:8000**.
2. Click the connection settings icon and enter the requester and approver tokens from your local `.env`.
3. Switch to the requester role and create a sandbox.
4. Switch to the approver role, review its plan, and approve that exact plan.
5. Inspect the active resource output, audit history, and measured provisioning latency.
6. Use a one-minute lifetime to watch the backend automatically clean up its resources.

Moto starts with the application. No cloud credentials, payment card, Docker, or model download is required for this mode. Use a single application worker; CloudDesk enforces a data-directory lock to prevent competing schedulers.

## What is implemented

| Capability | Implementation |
| --- | --- |
| Self-service API | Validated request creation, scoped visibility, explicit request states |
| Duplicate protection | Transactional, actor-scoped idempotency keys; conflicting payloads return 409 |
| Approval | Separate requester/approver credentials, bound to a SHA-256 plan digest |
| Infrastructure | Private S3 sandbox, encryption configuration, and bucket-scoped IAM role policy |
| Execution engines | Direct boto3 API calls, local Terraform, or Jenkins Remote Access API |
| Resource verification | Ownership tags, encryption, public-access blocks, and IAM policy checked after apply |
| Expiry and recovery | Durable jobs, expiry scheduling, interrupted-job recovery, bounded cleanup retries |
| Audit | SHA-256 hash-linked event history with verification |
| Troubleshooting | Local runbook retrieval; optional Ollama selection of existing diagnostic step IDs |
| Incident lab | Isolated duplicate, unauthorized approval, failed apply, expiry, and cleanup-retry scenarios |
| Slack | Socket Mode bridge, slash commands, digest-bound approval buttons, signature-checked HTTP mode |
| Service management | Working local request/ticket API; optional ServiceNow Table API adapter |
| Portfolio deployment | Static browser demo and GitHub Actions verification/Pages workflows |

## API-first workflow

Interactive API documentation is available at **http://127.0.0.1:8000/docs**. Authorize using one of your generated local tokens. `POST /api/requests` requires an `Idempotency-Key` header.

```text
POST /api/requests
GET  /api/requests/{id}
POST /api/requests/{id}/approve   {"plan_digest": "reviewed digest"}
POST /api/requests/{id}/reject
POST /api/requests/{id}/retry
POST /api/requests/{id}/destroy
GET  /api/requests/{id}/audit
GET  /api/metrics
POST /api/assistant/ask
POST /api/replays/{scenario}
```

See [API examples](docs/API.md) for executable requests.

## Run verification

```sh
python -m pip install -e '.[dev]'
python scripts/check.py
node --test tests/test_demo.mjs
```

Node is needed only for the browser-model checks, not to run the application. On a normal local machine with Terraform installed, also run:

```sh
# macOS/Linux
RUN_TERRAFORM=1 python -m pytest tests/test_terraform.py -v
# PowerShell
$env:RUN_TERRAFORM="1"
python -m pytest tests/test_terraform.py -v
```

The Terraform integration test creates, verifies, and destroys resources against an isolated local Moto server. It does not use AWS.

To repeat the authenticated Chromium check:

```sh
python -m pip install playwright==1.56.0
python -m playwright install chromium
# macOS/Linux; use $env:RUN_BROWSER="1" in PowerShell
RUN_BROWSER=1 python -m pytest tests/test_browser.py -v
```

## Integrations and deployment

- [Local Docker, Jenkins, Terraform, Slack, and Ollama setup](docs/INTEGRATIONS.md)
- [Publish the repository and free GitHub Pages demo](docs/DEPLOYMENT.md)
- [Architecture, assumptions, and limits](docs/ARCHITECTURE.md)
- [Validation evidence and remaining external checks](docs/VALIDATION.md)
- [A three-minute interview demonstration](docs/DEMO.md)

## Honest project boundaries

Moto simulates AWS behavior and is not evidence of real AWS IAM enforcement. Its resource state is ephemeral. API mode reconstructs unexpired active resources when the application starts; Terraform/Jenkins mode requires a fresh reviewed plan after the emulator is reset. Keep the application running for scheduled cleanup; it handles expired requests when restarted.

The assistant always displays its execution mode. Browser search and extractive fallback are not presented as LLM inference. Optional Ollama inference selects existing runbook step IDs, so all displayed diagnostic text and sources come from the repository's runbooks.

External Slack, Jenkins, Ollama, and ServiceNow connections require your own setup. No external account or live integration is silently assumed.

## Primary documentation used

- [Moto server mode](https://docs.getmoto.org/en/latest/docs/server_mode.html)
- [AWS S3 public-access protection](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [Terraform saved plans](https://developer.hashicorp.com/terraform/cli/commands/plan)
- [Jenkins Remote Access API](https://www.jenkins.io/doc/book/using/remote-access-api/)
- [Slack Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [ServiceNow Table API](https://www.servicenow.com/docs/r/zurich/api-reference/rest-apis/c_TableAPI.html)
- [GitHub Pages hosting](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

Licensed under MIT. Third-party dependencies retain their own licenses.
