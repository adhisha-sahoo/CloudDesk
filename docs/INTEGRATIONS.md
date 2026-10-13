# Integration setup

The local API mode is complete without external accounts. Add integrations individually and keep all credentials in the ignored `.env` file.

## Docker (optional)

After `python scripts/bootstrap.py`:

```sh
docker compose up --build
```

The app is at http://127.0.0.1:8000 and the emulator is at http://127.0.0.1:5000. Both ports bind only to your own computer. Data records persist in a named Docker volume; Moto resources remain ephemeral. Restart the app after an emulator reset to reconstruct unexpired active API-mode resources.

Docker Engine is an alternative on Linux. Docker Desktop's official terms permit free personal and educational use; use an eligible installation rather than a paid organizational plan. See [Docker's licensing page](https://docs.docker.com/subscription-billing/desktop-license/).

The Docker configurations were prepared in an environment without a Docker daemon. Consult VALIDATION.md for the checks actually executed.

## Local Terraform

Before changing execution engines, clean up all nonterminal requests in your current engine. CloudDesk refuses to switch engines while those requests remain. Alternatively, use a fresh data directory under `.data/`. This prevents a Terraform cleanup from falsely reporting success for an API-created resource.

Install Terraform 1.13.5 or a later 1.x version from [HashiCorp](https://developer.hashicorp.com/terraform/install). The downloaded binary should be verified against the official checksum. Set:

```text
CLOUDDESK_EXECUTOR=terraform
CLOUDDESK_TERRAFORM_BIN=terraform
```

Restart the app. A request now creates a real saved Terraform plan before becoming eligible for approval. The apply step checks the saved file's digest, applies that file, and verifies resource controls through the AWS SDK.

Keep the emulator running between plan, approval, and apply. If Moto has been reset, an old Terraform state can reference missing resources. Replan and review; do not manually apply an unreviewed replacement plan. Request-specific state lives under `.data/terraform/`.

## Jenkins and Terraform

```sh
docker compose --profile jenkins up --build
```

1. Open http://127.0.0.1:8080 and sign in as `admin` using the generated `JENKINS_ADMIN_PASSWORD` from `.env`.
2. Open your Jenkins account settings and generate an API token. Keep it private.
3. The configured `clouddesk` pipeline job reads the included Jenkinsfile. It runs one validated operation and archives `result.json`.
4. Set `CLOUDDESK_EXECUTOR=jenkins`, `CLOUDDESK_JENKINS_USER=admin`, and your `CLOUDDESK_JENKINS_TOKEN` in `.env`.
5. Recreate the app to load its new environment: `docker compose --profile jenkins up -d --force-recreate app`.

The app calls `buildWithParameters`, follows the queue item into a specific build, reads its status, and downloads that build's result artifact. API-token authentication does not need a Jenkins CSRF crumb. On timeout it requests build/queue cancellation and records a failed operation. Verify the cancelled build before retrying after a timeout.

Saved plans and state persist in the Jenkins named volume. The Docker setup uses an admin account for a local demonstration; a team deployment should use a dedicated Jenkins identity with narrowly scoped job access.

## Slack Socket Mode (recommended)

Socket Mode avoids public tunnels and hosted endpoints.

1. In your own development workspace, create a Slack app from `jenkins/slack-manifest.yaml` using Slack's manifest setup.
2. Install it to that workspace. Copy its bot token into `CLOUDDESK_SLACK_BOT_TOKEN`.
3. Generate an app-level token with `connections:write` and put it in `CLOUDDESK_SLACK_APP_TOKEN`.
4. Set `CLOUDDESK_SLACK_TEAM_ID` to the actual workspace ID.
5. Set `CLOUDDESK_SLACK_APPROVERS` to a comma-separated list of real user IDs allowed to approve requests.
6. Optionally set `CLOUDDESK_SLACK_APPROVAL_CHANNEL` to a development channel ID and invite the bot to it.
7. Start the backend and run `python scripts/slack_socket.py` on the same computer.

```text
/clouddesk create analytics-lab duration=30m
/clouddesk status REQUEST_ID
/clouddesk approve REQUEST_ID PLAN_DIGEST
/clouddesk reject REQUEST_ID
/clouddesk destroy REQUEST_ID
/clouddesk retry REQUEST_ID
/clouddesk ask My S3 access is denied
```

The bridge immediately acknowledges incoming envelopes and forwards work to the backend's durable inbox. Provisioning does not block Slack's acknowledgement. Approval messages include the plan's digest, resource changes, and environment label. Button values contain the reviewed digest.

The bridge requires the backend on port 8000. If you change that port, update its explicit local URL. External Slack installation and messaging are not performed during automated tests.

## Slack HTTP mode (alternative)

If you already have an HTTPS reverse proxy under your control, point slash-command/interactivity URLs at `/slack/events` and configure `CLOUDDESK_SLACK_SIGNING_SECRET`. The endpoint verifies the raw-body signature and rejects timestamps outside the five-minute window. No public HTTP hosting or paid tunnel is required by the default project.

## Optional Ollama inference

Install [Ollama](https://docs.ollama.com/local) on your own computer. Download a model that fits your hardware, for example:

```sh
ollama pull qwen2.5:1.5b
```

Then set:

```text
CLOUDDESK_ASSISTANT_MODE=ollama
CLOUDDESK_OLLAMA_URL=http://127.0.0.1:11434
CLOUDDESK_OLLAMA_MODEL=qwen2.5:1.5b
```

Restart CloudDesk. No Ollama cloud account or paid model API is used. Without a downloaded/running model, the assistant returns explicitly labeled extractive fallback. The model selects diagnostic step IDs from retrieved runbooks; all displayed text remains source-backed stored content.

## Optional ServiceNow

Use this only with a developer instance you already have permission to access:

```text
CLOUDDESK_SERVICENOW_URL=https://YOUR-INSTANCE.service-now.com
CLOUDDESK_SERVICENOW_USER=YOUR-USER
CLOUDDESK_SERVICENOW_PASSWORD=YOUR-PASSWORD
```

The adapter uses the Table API's `incident` table and a request-specific `correlation_id`, looking up the existing record before creating or updating it. It records CloudDesk status in work notes. ServiceNow's native numeric incident state mapping is intentionally not assumed; organizations configure those workflows differently. The instance user needs permission to read/create/update these records.

The included local request system remains authoritative and works when this adapter is disabled. No ServiceNow subscription, trial, or billing account is required for the core project.
