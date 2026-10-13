import httpx


class ServiceNow:
    """Optional user-configured Table API adapter. Local requests remain authoritative."""

    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(
            base_url=settings.servicenow_url,
            auth=(settings.servicenow_user, settings.servicenow_password),
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        )

    def sync(self, request: dict) -> str:
        correlation = "clouddesk:" + request["id"]
        existing = self.client.get(
            "/api/now/table/incident",
            params={
                "sysparm_query": "correlation_id=" + correlation,
                "sysparm_fields": "sys_id",
                "sysparm_limit": "1",
            },
        )
        existing.raise_for_status()
        rows = existing.json()["result"]
        body = {
            "short_description": f"CloudDesk storage sandbox: {request['slug']}",
            "description": f"Request {request['id']}; state {request['status']}; purpose: {request['reason']}",
            "correlation_id": correlation,
            "work_notes": f"CloudDesk state: {request['status']}. Environment: local AWS emulator.",
        }
        if rows:
            ticket_id = rows[0]["sys_id"]
            response = self.client.patch("/api/now/table/incident/" + ticket_id, json=body)
        else:
            response = self.client.post("/api/now/table/incident", json=body)
        response.raise_for_status()
        return response.json()["result"]["sys_id"]
