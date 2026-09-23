"""Run the same project checks locally and in CI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = [
    [sys.executable, "-m", "ruff", "format", "--check", "backend", "tests", "scripts"],
    [sys.executable, "-m", "ruff", "check", "backend", "tests", "scripts"],
    [sys.executable, "-m", "mypy", "backend"],
    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
    ["npm.cmd" if sys.platform == "win32" else "npm", "run", "check", "--prefix", "frontend"],
]


def main() -> int:
    for command in COMMANDS:
        print(f"\n$ {' '.join(command)}", flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
