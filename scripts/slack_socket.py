"""Optional Slack Socket Mode bridge. No public tunnel is required."""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clouddesk.config import Settings  # noqa: E402

settings = Settings()
settings.validate_credentials()
if not settings.slack_app_token or not settings.slack_bot_token or not settings.slack_team_id:
    raise SystemExit("Configure your Slack app token, bot token, and workspace ID in .env first.")
client = SocketModeClient(
    app_token=settings.slack_app_token, web_client=WebClient(token=settings.slack_bot_token)
)
pool = ThreadPoolExecutor(max_workers=3)


def forward(request):
    try:
        response = httpx.post(
            "http://127.0.0.1:8000/api/integrations/slack/socket",
            headers={"Authorization": "Bearer " + settings.bridge_token},
            json={"envelope_id": request.envelope_id, "payload": request.payload},
            timeout=10,
            trust_env=False,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        # Avoid logging tokens, complete payloads, or private message content.
        print(
            "Could not deliver a Slack interaction to the local backend; check the backend and bridge credentials."
        )


def receive(connection, request):
    if request.type not in {"slash_commands", "interactive"}:
        connection.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
        return
    connection.send_socket_mode_response(
        SocketModeResponse(
            envelope_id=request.envelope_id,
            payload={
                "text": "CloudDesk received your request. Processing in the background.",
                "response_type": "ephemeral",
            },
        )
    )
    pool.submit(forward, request)


client.socket_mode_request_listeners.append(receive)
try:
    client.connect()
    print("Slack Socket Mode bridge connected. Press Ctrl+C to stop.")
    threading.Event().wait()
except KeyboardInterrupt:
    pass
finally:
    client.close()
    pool.shutdown(wait=True)
