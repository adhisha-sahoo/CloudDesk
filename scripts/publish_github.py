"""Verify and publish a new CloudDesk repository through the authenticated GitHub CLI API."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = [
    "clouddesk",
    "tests",
    "site",
    "runbooks",
    "infra",
    "jenkins",
    "scripts",
    "docs",
    ".github",
    ".gitignore",
    ".dockerignore",
    ".env.example",
    "pyproject.toml",
    "package.json",
    "README.md",
    "LICENSE",
    "Dockerfile",
    "compose.yaml",
    "Jenkinsfile",
]


def command(*arguments, capture=False, env=None):
    result = subprocess.run(  # noqa: S603 - argument arrays, trusted CLI commands
        list(arguments), cwd=ROOT, text=True, capture_output=capture, env=env, check=False
    )  # noqa: S603 - argument arrays, trusted CLI commands
    if result.returncode:
        raise RuntimeError(
            f"{arguments[0]} {arguments[1]} failed"
            + (": " + result.stderr.strip() if capture else "")
        )
    return result.stdout if capture else ""


def api(route, method="GET", body=None):
    with tempfile.TemporaryDirectory(prefix="clouddesk-gh-") as folder:
        args = ["gh", "api", route, "--method", method]
        if body is not None:
            path = Path(folder) / "body.json"
            path.write_text(json.dumps(body))
            args.extend(["--input", str(path)])
        result = command(*args, capture=True)
        return json.loads(result) if result.strip() else {}


def check_staged():
    paths = command("git", "diff", "--cached", "--name-only", capture=True).splitlines()
    secret_pattern = re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
    )
    for name in paths:
        parts = Path(name).parts
        if (
            ".env" in parts
            or ".data" in parts
            or ".venv" in parts
            or any(p.endswith(".tfstate") for p in parts)
        ):
            raise RuntimeError("An excluded private/runtime file is staged")
        content = command("git", "show", ":" + name, capture=True)
        if secret_pattern.search(content):
            raise RuntimeError("Possible credential content is staged in " + name)
    if not paths:
        raise RuntimeError("There are no new staged project files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="clouddesk")
    parser.add_argument("--visibility", choices=["public", "private"], required=True)
    parser.add_argument(
        "--expected-owner", help="Optional expected GitHub login; refuse another account"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", args.name):
        raise SystemExit("Choose a simple GitHub repository name")
    if not shutil.which("git") or not shutil.which("gh"):
        raise SystemExit(
            "Install Git and GitHub CLI, then run gh auth login. No token belongs in source."
        )
    account = api("user")
    owner = account["login"]
    if args.expected_owner and owner.lower() != args.expected_owner.lower():
        raise SystemExit("The authenticated GitHub account differs from --expected-owner")
    print("Authenticated GitHub account:", owner)
    print("Creating a new", args.visibility, "repository after local verification.")
    command(sys.executable, "scripts/check.py")
    if shutil.which("node"):
        command("node", "--test", "tests/test_demo.mjs")
    else:
        raise SystemExit("Install Node to verify the browser demo before publication")
    command(sys.executable, "scripts/build_site.py")
    if (ROOT / ".git").exists():
        remotes = command("git", "remote", capture=True).strip()
        if remotes:
            raise SystemExit(
                "This checkout already has a remote. Use your existing Git workflow; no remote was changed."
            )
        if command("git", "branch", "--show-current", capture=True).strip() != "main":
            raise SystemExit(
                "Use a checkout on main; this publisher does not change an existing branch"
            )
    else:
        command("git", "init", "-b", "main")
    command("git", "add", "--", *ALLOWLIST)
    check_staged()
    # Use the verified account's public noreply identity, not an inferred private email.
    identity = dict(os.environ)
    identity.update(
        GIT_AUTHOR_NAME=account.get("name") or owner,
        GIT_AUTHOR_EMAIL=f"{account['id']}+{owner}@users.noreply.github.com",
        GIT_COMMITTER_NAME=account.get("name") or owner,
        GIT_COMMITTER_EMAIL=f"{account['id']}+{owner}@users.noreply.github.com",
    )
    command(
        "git", "commit", "-m", "Build CloudDesk infrastructure automation platform", env=identity
    )
    # A 422/name conflict is reported; existing repositories are never overwritten.
    repository = api(
        "user/repos",
        "POST",
        {
            "name": args.name,
            "private": args.visibility == "private",
            "description": "Approval-based infrastructure automation with Slack, Python, Terraform/Jenkins, and grounded local troubleshooting",
            "auto_init": False,
        },
    )
    command("git", "remote", "add", "origin", repository["clone_url"])
    command("gh", "auth", "setup-git")
    command("git", "push", "-u", "origin", "main")
    print("Repository:", repository["html_url"])
    if args.visibility == "public":
        try:
            api(f"repos/{owner}/{args.name}/pages", "POST", {"build_type": "workflow"})
        except RuntimeError:
            print(
                "Source was pushed, but the Pages API did not succeed. Select GitHub Actions in Settings → Pages."
            )
            raise
        print("Pages enabled. Wait for successful verification and deployment in the Actions tab.")
        print(
            "Expected demo URL (not yet verified live):", f"https://{owner}.github.io/{args.name}/"
        )
    else:
        print(
            "Private source repository created. Pages was not enabled; free Pages requires a public repository."
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError) as error:
        raise SystemExit(str(error)) from error
