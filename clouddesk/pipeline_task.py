"""Jenkins invokes this module with environment parameters, never shell-expanded input."""

import json
import os
from pathlib import Path

from .config import require_local_url
from .models import CreateRequest
from .terraform_runner import TerraformInfrastructure


def main():
    action = os.environ["ACTION"]
    if action not in {"plan", "apply", "destroy"}:
        raise ValueError("Unsupported infrastructure action")
    request = json.loads(os.environ["REQUEST_JSON"])
    CreateRequest(slug=request["slug"], ttl_minutes=request["ttl_minutes"])
    endpoint = require_local_url(
        os.getenv("CLOUDDESK_AWS_ENDPOINT", "http://moto:5000"), {"localhost", "127.0.0.1", "moto"}
    )
    runner = TerraformInfrastructure(
        endpoint, Path(os.getenv("CLOUDDESK_TF_ROOT", "/var/jenkins_home/clouddesk-state"))
    )
    result = getattr(runner, action)(request)
    Path("result.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main()
