import importlib.util
import os
import subprocess
import sys
import time

import httpx
import pytest

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER") != "1" or importlib.util.find_spec("playwright") is None,
        reason="Set RUN_BROWSER=1 and install Playwright/Chromium for browser verification",
    ),
]


def test_authenticated_dashboard_and_mobile_layout(settings, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    from clouddesk.config import ROOT
    from tests.conftest import unused_port

    port = unused_port()
    env = dict(
        os.environ,
        CLOUDDESK_DATA_DIR=str(tmp_path / "browser-app"),
        CLOUDDESK_EMBEDDED_MOTO="false",
        CLOUDDESK_AWS_ENDPOINT=settings.aws_endpoint,
        CLOUDDESK_REQUESTER_TOKEN=settings.requester_token,
        CLOUDDESK_APPROVER_TOKEN=settings.approver_token,
        CLOUDDESK_BRIDGE_TOKEN=settings.bridge_token,
        CLOUDDESK_WORKER_ENABLED="true",
        CLOUDDESK_EXECUTOR="api",
        CLOUDDESK_ASSISTANT_MODE="extractive",
        CLOUDDESK_SLACK_BOT_TOKEN="",
        CLOUDDESK_SERVICENOW_URL="",
    )
    with (tmp_path / "browser-server.log").open("w") as log:
        server = subprocess.Popen(  # noqa: S603 - fixed local QA command, shell disabled
            [
                sys.executable,
                "-m",
                "uvicorn",
                "clouddesk.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )  # noqa: S603 - fixed local QA server command
        try:
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(trust_env=False) as client:
                for _ in range(100):
                    try:
                        if client.get(base + "/api/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Browser QA server did not start")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                page.goto(base, wait_until="networkidle")
                page.locator("#connection-button").click()
                page.locator("input[name=requester]").fill(settings.requester_token)
                page.locator("input[name=approver]").fill(settings.approver_token)
                page.get_by_role("button", name="Connect →", exact=True).click()
                expect(page.locator("#connection-label")).to_contain_text("Local API connected")
                page.locator("#role-button").click()
                expect(page.locator("#role-button")).to_have_text("Role: requester")
                page.locator("button.new-request").click()
                page.locator("input[name=slug]").fill("browser-live-test")
                page.locator("select[name=ttl]").select_option("1")
                page.locator("textarea[name=reason]").fill("Authenticated browser verification")
                page.get_by_role("button", name="Create request →", exact=True).click()
                expect(page.locator("#request-dialog")).not_to_be_visible()
                page.locator("#role-button").click()
                expect(page.locator("#role-button")).to_have_text("Role: approver")
                page.get_by_role("button", name="browser-live-test", exact=False).wait_for(
                    state="visible"
                )
                page.get_by_role("button", name="browser-live-test", exact=False).click()
                page.get_by_role("button", name="Approve this plan →", exact=True).wait_for(
                    state="visible", timeout=15000
                )
                page.get_by_role("button", name="Approve this plan →", exact=True).click()
                expect(page.locator("#detail-content .status")).to_have_text(
                    "Active", timeout=15000
                )
                page.get_by_role("button", name="Clean up sandbox", exact=True).click()
                expect(page.locator("#detail-content .status")).to_have_text(
                    "Destroyed", timeout=15000
                )
                page.locator("#detail-dialog button.close-dialog").click()
                page.get_by_role("button", name="Incident lab", exact=False).first.click()
                page.locator("[data-replay=expiry]").click()
                expect(page.locator("#replay-expiry")).to_contain_text(
                    "All checks passed", timeout=15000
                )
                page.get_by_role("button", name="Runbook assistant", exact=False).first.click()
                page.locator("#question").fill("My S3 access is denied")
                page.get_by_role("button", name="Find relevant checks →").click()
                expect(page.locator("#answer-area li")).to_have_count(3, timeout=15000)
                page.set_viewport_size({"width": 390, "height": 844})
                assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert (
                    page.locator(".runbook-item").first.evaluate(
                        "element => getComputedStyle(element).display"
                    )
                    == "block"
                )
                assert not errors
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)
