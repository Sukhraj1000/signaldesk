#!/usr/bin/env python3
"""Deterministic dependency hygiene checks for SignalDesk.

This check is intentionally lightweight and offline. It is not a replacement for a
live vulnerability database audit; it prevents dependency patterns that are risky
for this small package today without requiring secrets, network access, or paid
services in CI.
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
LOWER_BOUND_RE = re.compile(r"(?:>=|~=)\s*[^,\s]+")
WILDCARD_OR_EMPTY_EXACT_PIN_RE = re.compile(r"==\s*(?:$|[,;]|[^,;]*\*)")

# Known dependency names that should not enter this project without an explicit
# security review. Keep this list conservative to avoid false positives.
DENIED_PACKAGE_NAMES = {
    "crypto",  # abandoned/ambiguous legacy package; prefer maintained libraries.
    "pycrypto",  # unmaintained crypto package with known security history.
    "sklearn",  # deprecated shim; use scikit-learn if ever needed.
}


@dataclass(frozen=True)
class DependencyIssue:
    section: str
    requirement: str
    message: str

    def format(self) -> str:
        return f"{self.section}: {_redact_requirement(self.requirement)!r}: {self.message}"


def _redact_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return "<direct-reference>"
    host = parsed.hostname or parsed.netloc.rsplit("@", maxsplit=1)[-1]
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    query = "<redacted>" if parsed.query else ""
    return urlunsplit((parsed.scheme, host, parsed.path, query, ""))


def _redact_requirement(requirement: str) -> str:
    normalized = requirement.strip()
    if " @ " in normalized:
        name, reference = normalized.split(" @ ", maxsplit=1)
        return f"{name} @ {_redact_url(reference)}"
    if normalized.startswith(("http://", "https://", "file:")):
        return _redact_url(normalized)
    return normalized


def _dependency_sections(pyproject: Path) -> dict[str, list[str]]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    sections: dict[str, list[str]] = {
        "project.dependencies": list(project.get("dependencies", [])),
    }
    optional = project.get("optional-dependencies", {})
    for extra_name, requirements in sorted(optional.items()):
        sections[f"project.optional-dependencies.{extra_name}"] = list(requirements)
    return sections


def _package_name(requirement: str) -> str:
    match = NAME_RE.match(requirement)
    return match.group(1).replace("_", "-").lower() if match else ""


def check_requirements(pyproject: Path = PYPROJECT) -> list[DependencyIssue]:
    issues: list[DependencyIssue] = []
    for section, requirements in _dependency_sections(pyproject).items():
        for requirement in requirements:
            normalized = requirement.strip()
            specifier_part = normalized.split(";", maxsplit=1)[0]
            package_name = _package_name(normalized)
            if not package_name:
                issues.append(DependencyIssue(section, requirement, "could not parse package name"))
                continue
            if package_name in DENIED_PACKAGE_NAMES:
                issues.append(
                    DependencyIssue(section, requirement, "package name is on the denied list")
                )
            if " @ " in normalized or normalized.startswith(("http://", "https://", "file:")):
                issues.append(
                    DependencyIssue(
                        section,
                        requirement,
                        "direct URL/path dependencies are not allowed in CI-scanned dependencies",
                    )
                )
            if WILDCARD_OR_EMPTY_EXACT_PIN_RE.search(specifier_part):
                issues.append(
                    DependencyIssue(
                        section,
                        requirement,
                        "wildcard or empty exact pins are not allowed",
                    )
                )
            if not LOWER_BOUND_RE.search(specifier_part):
                issues.append(
                    DependencyIssue(
                        section,
                        requirement,
                        "dependency must declare a lower bound such as >= or ~=",
                    )
                )
    return issues


def main() -> int:
    issues = check_requirements()
    if issues:
        print("Dependency/security check failed:")
        for issue in issues:
            print(f"- {issue.format()}")
        return 1
    print("Dependency/security check passed: declared dependencies are bounded and offline-safe.")
    print("Note: run a live vulnerability audit separately when the dependency surface grows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
