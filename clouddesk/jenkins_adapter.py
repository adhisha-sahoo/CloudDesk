import time
from urllib.parse import urlparse

import httpx

from .store import canonical


class JenkinsInfrastructure:
    def __init__(self, settings, client=None, timeout=300):
        self.settings = settings
        self.client = client or httpx.Client(
            base_url=settings.jenkins_url,
            auth=(settings.jenkins_user, settings.jenkins_token),
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        )
        self.timeout = timeout

    def _path(self, url: str) -> str:
        candidate, expected = urlparse(url), urlparse(self.settings.jenkins_url)
        if candidate.scheme and (candidate.scheme, candidate.netloc) != (
            expected.scheme,
            expected.netloc,
        ):
            raise RuntimeError("Jenkins returned a URL outside its configured server")
        if not candidate.path.startswith("/") or candidate.path.startswith("//") or candidate.query:
            raise RuntimeError("Jenkins returned an invalid queue or build URL")
        return candidate.path

    def run(self, action: str, request: dict) -> dict:
        payload = {
            key: request.get(key) for key in ("id", "slug", "owner", "ttl_minutes", "plan_digest")
        }
        response = self.client.post(
            f"/job/{self.settings.jenkins_job}/buildWithParameters",
            data={"ACTION": action, "REQUEST_JSON": canonical(payload)},
        )
        response.raise_for_status()
        location = response.headers.get("location")
        if not location:
            raise RuntimeError("Jenkins did not return a queue location")
        queue = self._path(location).rstrip("/")
        started = time.monotonic()
        build = None
        while time.monotonic() - started < self.timeout:
            response = self.client.get((build or queue) + "/api/json")
            response.raise_for_status()
            data = response.json()
            if not build:
                if data.get("cancelled"):
                    raise RuntimeError("Jenkins cancelled this queued job")
                if data.get("executable"):
                    build = self._path(data["executable"]["url"]).rstrip("/")
            elif not data.get("building", True):
                if data.get("result") != "SUCCESS":
                    raise RuntimeError("Jenkins infrastructure job failed")
                artifact = self.client.get(build + "/artifact/result.json")
                artifact.raise_for_status()
                return artifact.json()
            time.sleep(0.5)
        if build:
            self.client.post(build + "/stop").raise_for_status()
        else:
            self.client.post(
                "/queue/cancelItem", params={"id": queue.rsplit("/", 1)[-1]}
            ).raise_for_status()
        raise TimeoutError(
            "Jenkins timed out; cancellation was requested, verify the build before retrying"
        )

    def plan(self, request):
        return self.run("plan", request)

    def apply(self, request):
        return self.run("apply", request)

    def destroy(self, request):
        return self.run("destroy", request)
