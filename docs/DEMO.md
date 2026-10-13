# Three-minute portfolio demonstration

## 0:00–0:30 — Explain the problem

"Development resource requests often cross chat, ticketing, and infrastructure tools. CloudDesk connects the request, reviewed change, ownership, and cleanup in one workflow."

Identify the local emulator environment clearly. Show the public browser demo only as an interface preview.

## 0:30–1:20 — Show the real API workflow

Connect to the local backend. As requester, create `interview-demo` with a one-minute lifetime. Switch to approver, open the request, and inspect:

- the five allowlisted resource types;
- encryption, public-access blocks, and the scoped IAM policy;
- the review-plan engine and digest.

Approve the exact plan. Inspect ACTIVE output and the audit history. If using Jenkins, show the specific plan/apply builds and saved Terraform plan digest.

## 1:20–2:00 — Show the unhappy path

Run unauthorized approval and duplicate-request replays in authenticated local API mode. Show real executed checks rather than browser illustrations. Run the injected apply-failure scenario and explain why retry requires a new review.

## 2:00–2:30 — Troubleshoot with evidence

Ask "My S3 access is denied". Show cited runbook checks and the execution-mode label. Ask an unrelated question and show the abstention.

If local Ollama is configured, explain that the model selects stored diagnostic steps and has no infrastructure execution authority. Without it, describe the working extractive runbook search honestly.

## 2:30–3:00 — Close the resource lifecycle

Return to the one-minute sandbox, observe teardown, and inspect RESOURCE_DESTROYED in its audit history. Show the actual provisioning metric, CI checks, and source repository.

## Resume claims supported by the project

Use only the integrations you personally configured and exercised. A defensible project summary is:

"Built an API-first infrastructure request platform with Python/FastAPI, Slack integration, digest-bound approvals, and automated lifecycle management in a local AWS-compatible environment."

A second supported bullet is:

"Implemented digest-bound Terraform approvals, request idempotency, automatic expiry, and hash-linked audit events; verified API, browser, and Terraform lifecycle behavior through GitHub Actions."

Terraform execution is verified against Moto in CI. Add live Jenkins, Slack workspace usage, ServiceNow, and local LLM inference only after configuring and exercising those integrations yourself. Report your measured test/request counts and latency; do not turn emulator results into claims of production AWS deployment or enterprise adoption.
