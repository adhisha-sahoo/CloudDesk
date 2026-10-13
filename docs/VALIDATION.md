# Validation evidence

Verified in the build workspace on 13 October 2026, using Python 3.12 and Chromium 141.

## Passed checks

- **51 Python tests passed** with `RUN_BROWSER=1 python -m pytest --cov=clouddesk --cov-report=term-missing -q`.
- **2 JavaScript behavior tests passed** with `node --test tests/test_demo.mjs`.
- **87% Python statement coverage** in that run. Coverage is evidence of exercised code, not a guarantee of correctness.
- Ruff lint and formatting checks passed.
- Both JavaScript modules passed `node --check`.
- Terraform configuration passed `terraform fmt -check`.
- Editable package installation succeeded.
- Desktop and mobile dashboard views were visually inspected. A form-pattern compatibility problem and a CSP-blocked inline style were corrected.
- Authenticated Chromium verification completed requester creation, plan review, approver authorization, actual emulator provisioning, resource cleanup, an executed expiry replay, and a cited runbook response. Its final browser test reported no console/page errors and no horizontal overflow at 390px width.

The Python suite exercises:

- a complete S3/IAM sandbox lifecycle against Moto HTTP APIs;
- encryption, public-access blocks, policy scope, object removal, and owned-resource deletion;
- 20 concurrent repeated requests producing one request and one job;
- conflicting payloads, invalid inputs, missing authentication, role denial, and requester visibility;
- stale digests, stale Slack approval buttons, Slack signatures, timestamps, workspace checks, and inbox deduplication;
- failed apply, fresh-review retry, expiry, cleanup retry, interrupted-job recovery, and partial IAM cleanup;
- expiry during re-review and protection against changing executors with unfinished requests;
- state-specific notification snapshots and audit-chain modification detection;
- grounded runbook retrieval, abstention, Ollama API/output contracts, and invalid/unavailable-model fallback;
- Jenkins API queue/build/artifact contracts, foreign URL refusal, and timeout cancellation;
- ServiceNow correlation lookup, creation, and update contracts.

## Not executed live here

| Check | Status and reason |
| --- | --- |
| Native Terraform plan/apply/destroy | One test skipped in the final suite. A direct attempt found the workspace disallows the Unix-domain socket required by the AWS Terraform provider: `socket: operation not permitted`. The project includes a standard Linux GitHub Actions job to run this test. |
| Docker Compose/Jenkins container boot | No Docker daemon was available. The files and API contracts were prepared, but a running Jenkins server/pipeline was not verified here. |
| Real Slack workspace installation and messaging | No Slack app credentials or workspace identifiers were supplied. HTTP/signature/command behavior was tested without sending real messages. |
| Local Ollama model inference | No model runtime/download was supplied. HTTP request and model-selection/fallback contracts were tested with deterministic responses. |
| Live ServiceNow instance | No developer instance or credentials were supplied. Its Table API adapter was contract-tested. |
| GitHub repository and Pages publication | GitHub installation was confirmed, but the running session did not expose callable GitHub account/publishing tools. No repository creation or successful deployment is claimed. An authenticated API/CLI publisher and Pages workflows are included. |

The dependency stack emitted one upstream TestClient deprecation warning about httpx compatibility; it did not cause test failures.

Run the supplied CI workflows and the integration setup guide before adding claims about live Jenkins, Terraform, Slack, or model inference to a resume. The free local API implementation and public browser demonstration are intentionally distinguished from those external integrations.
