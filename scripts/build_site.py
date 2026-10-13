"""Prepare a static Pages artifact using only repository-owned files."""

import json
import os
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
shutil.copyfile(root / "runbooks/runbooks.json", root / "site/runbooks.json")
repository = os.environ.get("GITHUB_REPOSITORY", "")
if repository:
    import re

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SystemExit("Invalid repository identifier")
    (root / "site/config.json").write_text(
        json.dumps({"repository_url": "https://github.com/" + repository})
    )
print("Static demonstration prepared. No API credentials are included.")
