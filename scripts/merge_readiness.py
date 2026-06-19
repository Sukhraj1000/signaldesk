#!/usr/bin/env python3
"""Generate a lightweight merge-readiness report for SignalDesk PRs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RISKY_PREFIXES = (
    ".github/",
    ".devcontainer/",
    "docker-compose.yml",
    "Dockerfile",
    "pyproject.toml",
    "tox.ini",
    "scripts/",
)
RISKY_KEYWORDS = ("auth", "secret", "token", "credential", "password", "env", "deploy", "release")


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check)


def lines(command: list[str]) -> list[str]:
    output = run(command).stdout.strip()
    return [line for line in output.splitlines() if line]


def base_ref() -> str:
    for candidate in ("origin/main", "main"):
        result = run(["git", "rev-parse", "--verify", candidate], check=False)
        if result.returncode == 0:
            return candidate
    return "HEAD"


def main() -> int:
    branch = run(["git", "branch", "--show-current"]).stdout.strip()
    base = base_ref()
    status = lines(["git", "status", "--short"])
    changed = [] if base == "HEAD" else lines(["git", "diff", "--name-only", f"{base}...HEAD"])
    unstaged = lines(["git", "diff", "--name-only"])
    staged = lines(["git", "diff", "--cached", "--name-only"])
    untracked = [line[3:] for line in status if line.startswith("?? ")]

    risky = sorted(
        path
        for path in set(changed + unstaged + staged + untracked)
        if path.startswith(RISKY_PREFIXES)
        or any(keyword in path.lower() for keyword in RISKY_KEYWORDS)
    )

    print("# Merge Readiness Report")
    print()
    print(f"Branch: {branch or '(detached)'}")
    print(f"Base ref: {base}")
    print(f"Changed files against main: {len(changed)}")
    print(f"Working tree status entries: {len(status)}")
    print()
    print("## Changed files")
    if changed:
        for path in changed:
            print(f"- {path}")
    else:
        print("- None against main")
    print()
    print("## Working tree")
    if status:
        for entry in status:
            print(f"- {entry}")
    else:
        print("- Clean")
    print()
    print("## Risk flags")
    if branch == "main":
        print("- BLOCKER: branch is main")
    if untracked:
        print("- REVIEW: untracked files are present")
    if risky:
        for path in risky:
            print(f"- REVIEW: risky path touched: {path}")
    if not risky and branch != "main" and not untracked:
        print("- No automatic risk flags detected")
    print()
    print("## Required before approval")
    print("- `make check` passes locally or in CI")
    print("- PR CI is green")
    print("- human approval is recorded")
    print("- any REVIEW/BLOCKER item above is resolved or explicitly accepted")

    return 1 if branch == "main" else 0


if __name__ == "__main__":
    sys.exit(main())
