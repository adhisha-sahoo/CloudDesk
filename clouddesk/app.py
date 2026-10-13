import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .assistant import Assistant
from .config import ROOT, Settings
from .infrastructure import ApiInfrastructure, endpoint_port
from .jenkins_adapter import JenkinsInfrastructure
from .models import Actor, Approval, CreateRequest, DomainError, Question
from .replay import SCENARIOS, run_scenario
from .runtime_lock import RuntimeLock
from .service import Service
from .servicenow import ServiceNow
from .slack_integration import Slack, verify_signature
from .store import Store, canonical
from .terraform_runner import TerraformInfrastructure
from .worker import Worker

bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None, infrastructure=None, clock=None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.data_dir / "clouddesk.sqlite3")
    service = Service(store, clock) if clock else Service(store)
    assistant = Assistant(settings)
    if infrastructure is None:
        if settings.executor == "terraform":
            infrastructure = TerraformInfrastructure(
                settings.aws_endpoint, settings.data_dir / "terraform", settings.terraform_bin
            )
        elif settings.executor == "jenkins":
            infrastructure = JenkinsInfrastructure(settings)
        else:
            infrastructure = ApiInfrastructure(settings.aws_endpoint)
    slack = Slack(settings, service, assistant)
    service_now = ServiceNow(settings) if settings.servicenow_url else None

    def notify(record):
        slack.notify(record)
        if service_now:
            ticket = service_now.sync(record)
            with store.transaction() as conn:
                conn.execute("UPDATE requests SET ticket_id=? WHERE id=?", (ticket, record["id"]))

    worker = Worker(service, infrastructure, settings, slack.process, notify)

    @asynccontextmanager
    async def lifespan(app):
        settings.validate_credentials()
        lock, moto = None, None
        try:
            lock = RuntimeLock(settings.data_dir / "runtime.lock")
            store.bind_executor(settings.executor)
            if settings.embedded_moto:
                from moto.server import ThreadedMotoServer

                moto = ThreadedMotoServer(
                    ip_address="127.0.0.1", port=endpoint_port(settings.aws_endpoint), verbose=False
                )
                moto.start()
            # Moto is ephemeral. Reconstruct active API-mode resources when restarting the app.
            if settings.executor == "api":
                for record in store.list():
                    if record["status"] == "ACTIVE" and record["expires_at"] > service.clock():
                        infrastructure.restore(record)
            if settings.worker_enabled:
                worker.start()
            yield
        finally:
            worker.stop()
            if moto:
                moto.stop()
            if lock:
                lock.close()

    app = FastAPI(
        title="CloudDesk",
        version="1.0.0",
        description="Approval-bound infrastructure requests in a free local AWS-compatible environment.",
        lifespan=lifespan,
    )
    app.state.service, app.state.worker, app.state.assistant = service, worker, assistant
    app.state.slack = slack
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "app"]
    )

    @app.middleware("http")
    async def headers_and_size(request, call_next):
        if request.method in {"POST", "PATCH", "PUT"}:
            try:
                length = int(request.headers.get("content-length", "-1"))
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
            if length < 0:
                return JSONResponse({"detail": "Content-Length is required"}, status_code=411)
            if length > 65536:
                return JSONResponse({"detail": "Request body is too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
            )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"detail": error.message}, status_code=error.status)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Actor:
        token = credentials.credentials if credentials else ""
        if settings.requester_token and hmac.compare_digest(token, settings.requester_token):
            return Actor("local-requester", "requester")
        if settings.approver_token and hmac.compare_digest(token, settings.approver_token):
            return Actor("local-approver", "approver")
        raise DomainError(401, "A valid CloudDesk API token is required")

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "backend": "api",
            "version": "1.0.0",
            "environment": "local AWS emulator",
        }

    @app.get("/api/me")
    def me(actor: Actor = Depends(authenticate)):
        return {"id": actor.id, "role": actor.role}

    @app.get("/api/requests")
    def list_requests(actor: Actor = Depends(authenticate)):
        return service.list(actor)

    @app.post("/api/requests")
    def create_request(
        spec: CreateRequest,
        actor: Actor = Depends(authenticate),
        idempotency_key: str = Header(default=""),
    ):
        record, created = service.create(actor, spec, idempotency_key)
        return JSONResponse(record, status_code=201 if created else 200)

    @app.get("/api/requests/{request_id}")
    def get_request(request_id: str, actor: Actor = Depends(authenticate)):
        return service.get(actor, request_id)

    @app.get("/api/requests/{request_id}/audit")
    def get_audit(request_id: str, actor: Actor = Depends(authenticate)):
        service.get(actor, request_id)
        return store.history(request_id)

    @app.post("/api/requests/{request_id}/approve")
    def approve_request(request_id: str, approval: Approval, actor: Actor = Depends(authenticate)):
        return service.approve(actor, request_id, approval.plan_digest)

    @app.post("/api/requests/{request_id}/reject")
    def reject_request(request_id: str, actor: Actor = Depends(authenticate)):
        return service.reject(actor, request_id)

    @app.post("/api/requests/{request_id}/destroy")
    def destroy_request(request_id: str, actor: Actor = Depends(authenticate)):
        return service.destroy(actor, request_id)

    @app.post("/api/requests/{request_id}/retry")
    def retry_request(request_id: str, actor: Actor = Depends(authenticate)):
        return service.retry(actor, request_id)

    @app.get("/api/metrics")
    def metrics(actor: Actor = Depends(authenticate)):
        return service.metrics(actor)

    @app.post("/api/assistant/ask")
    def ask(question: Question, actor: Actor = Depends(authenticate)):
        return assistant.ask(question.question)

    @app.get("/api/runbooks")
    def runbooks():
        return assistant.documents

    @app.get("/api/replays")
    def replays(actor: Actor = Depends(authenticate)):
        return SCENARIOS

    @app.post("/api/replays/{scenario}")
    def replay(scenario: str, actor: Actor = Depends(authenticate)):
        if actor.role != "approver":
            raise DomainError(403, "Incident replays require an approver account")
        result = run_scenario(scenario, settings)
        (settings.data_dir / "replay-last.json").write_text(json.dumps(result, indent=2))
        return result

    @app.get("/api/integrations")
    def integrations(actor: Actor = Depends(authenticate)):
        return {
            "infrastructure": settings.executor,
            "aws": "local emulator",
            "slack_configured": bool(settings.slack_bot_token and settings.slack_team_id),
            "jenkins_configured": bool(settings.jenkins_token),
            "servicenow_configured": bool(settings.servicenow_url),
            "assistant": settings.assistant_mode,
        }

    @app.post("/slack/events")
    async def slack_events(request: Request):
        body = await request.body()
        if not settings.slack_signing_secret or not verify_signature(
            settings.slack_signing_secret,
            request.headers.get("x-slack-request-timestamp"),
            request.headers.get("x-slack-signature"),
            body,
        ):
            raise DomainError(401, "Invalid Slack signature")
        form = {key: values[0] for key, values in parse_qs(body.decode()).items()}
        try:
            payload = json.loads(form["payload"]) if "payload" in form else form
            key = hashlib.sha256(
                (payload.get("trigger_id") or canonical(payload)).encode()
            ).hexdigest()
            slack.enqueue(payload, key)
        except (ValueError, KeyError, TypeError):
            raise DomainError(422, "Invalid Slack payload") from None
        return {
            "response_type": "ephemeral",
            "text": "CloudDesk received your request. Processing in the background.",
        }

    @app.post("/api/integrations/slack/socket")
    def socket_event(
        envelope: dict, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
    ):
        token = credentials.credentials if credentials else ""
        if not settings.bridge_token or not hmac.compare_digest(token, settings.bridge_token):
            raise DomainError(401, "Invalid local Slack bridge token")
        if not isinstance(envelope.get("payload"), dict) or not isinstance(
            envelope.get("envelope_id"), str
        ):
            raise DomainError(422, "Invalid Slack envelope")
        slack.enqueue(envelope["payload"], envelope["envelope_id"])
        return {"queued": True}

    app.mount("/", StaticFiles(directory=ROOT / "site", html=True), name="dashboard")
    return app


app = create_app()
