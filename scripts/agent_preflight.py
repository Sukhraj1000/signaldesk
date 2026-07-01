#!/usr/bin/env python3
"""Local preflight for AI-assisted SignalDesk development."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_BRANCH_PREFIXES = ("feature/", "fix/", "bug/", "chore/", "docs/", "review/")
SECRET_NAME_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|ACCESS_KEY)", re.IGNORECASE
)
SECRET_VALUE_RE = re.compile(
    r"(ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{22,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{30,}|"
    r"sk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)

SENSITIVE_DOTENV_SAMPLE_SUFFIXES = (".example", ".sample", ".template")
SENSITIVE_AUTH_FILE_NAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "pip.conf",
}

SENSITIVE_KEY_FILE_NAMES = {
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
SENSITIVE_KEY_FILE_SUFFIXES = (".pem", ".p12", ".pfx")


def run(args: list[str]) -> str:
    completed = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def warn(message: str) -> None:
    print(f"WARN: {message}")


def ok(message: str) -> None:
    print(f"OK: {message}")


def check_repo() -> None:
    top = run(["git", "rev-parse", "--show-toplevel"])
    if Path(top).resolve() != ROOT:
        fail(f"expected repo root {ROOT}, got {top}")
    ok(f"repo root {ROOT}")

    origin = run(["git", "remote", "get-url", "origin"])
    normalized = (
        origin.removesuffix(".git")
        .replace("git@github.com:", "https://github.com/")
        .replace("ssh://git@github.com/", "https://github.com/")
    )
    if normalized != "https://github.com/Sukhraj1000/signaldesk":
        fail(f"origin remote mismatch: {origin}")
    ok("remote points to Sukhraj1000/signaldesk")


def check_branch() -> None:
    branch = run(["git", "branch", "--show-current"])
    if branch == "main":
        fail("refusing AI-assisted development directly on main; create a task branch")
    if not branch.startswith(ALLOWED_BRANCH_PREFIXES):
        warn(
            "branch should normally start with one of "
            + ", ".join(ALLOWED_BRANCH_PREFIXES)
            + f"; current branch is {branch!r}"
        )
    else:
        ok(f"branch name {branch}")


def check_env() -> None:
    suspicious = sorted(name for name in os.environ if SECRET_NAME_RE.search(name))
    if suspicious:
        names = ", ".join(suspicious[:20])
        warn(
            "secret-like environment variables are present; "
            f"do not pass them to untrusted agents: {names}"
        )
    else:
        ok("no secret-like environment variable names detected")


def is_sensitive_secret_path(rel: str) -> bool:
    """Return true when a repo path looks like a credential file.

    This intentionally checks filenames in addition to value patterns because ignored
    or newly added dotenv/key files can leak before a scanner sees a known token
    shape. Template files such as .env.example remain allowed.
    """

    name = Path(rel).name.lower()
    if name == ".env":
        return True
    if name == ".envrc":
        return True
    if name in SENSITIVE_AUTH_FILE_NAMES:
        return True
    if name.startswith(".env.") and not name.endswith(SENSITIVE_DOTENV_SAMPLE_SUFFIXES):
        return True
    if name.endswith(".env"):
        return True
    if name in SENSITIVE_KEY_FILE_NAMES:
        return True
    return name.endswith(SENSITIVE_KEY_FILE_SUFFIXES)


def check_sensitive_secret_filenames() -> None:
    files = run(["git", "ls-files", "--cached", "--others", "--exclude-standard"]).splitlines()
    offenders = sorted(rel for rel in files if is_sensitive_secret_path(rel))
    if offenders:
        fail("secret-looking filenames found in git-visible files: " + ", ".join(offenders))
    ok("no secret-looking filenames found in git-visible files")


def check_tracked_secret_patterns() -> None:
    files = run(["git", "ls-files", "--cached", "--others", "--exclude-standard"]).splitlines()
    offenders: list[str] = []
    for rel in files:
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if SECRET_VALUE_RE.search(text):
            offenders.append(rel)
    if offenders:
        fail("secret-looking values found in tracked files: " + ", ".join(offenders))
    ok("no obvious secret values found in tracked text files")


def main() -> None:
    check_repo()
    check_branch()
    check_env()
    check_sensitive_secret_filenames()
    check_tracked_secret_patterns()
    print("Preflight complete.")


if __name__ == "__main__":
    main()
