"""Run the project's standard verification commands from any working directory."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
commands = [
    [sys.executable, "-m", "ruff", "check", "."],
    [sys.executable, "-m", "pytest", "--cov=clouddesk", "--cov-report=term-missing"],
]
for command in commands:
    subprocess.run(command, cwd=root, check=True)  # noqa: S603 - fixed verification commands
