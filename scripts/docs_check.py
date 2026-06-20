#!/usr/bin/env python3
"""Check SignalDesk Markdown docs for broken local links."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
LOCAL_DOC_GLOBS = ("*.md", "docs/**/*.md", "packages/**/*.md")
IGNORED_SCHEMES = {"http", "https", "mailto"}


@dataclass(frozen=True)
class LinkProblem:
    path: Path
    line_number: int
    target: str
    message: str


def markdown_files(root: Path = ROOT) -> list[Path]:
    files: set[Path] = set()
    for pattern in LOCAL_DOC_GLOBS:
        files.update(root.glob(pattern))
    return sorted(path for path in files if path.is_file())


def github_anchor(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^a-z0-9 _-]", "", text)
    return re.sub(r"\s+", "-", text)


def anchors_for(path: Path) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = github_anchor(match.group(1))
        count = seen.get(base, 0)
        seen[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def split_target(raw_target: str) -> tuple[str, str]:
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc:
        return raw_target, ""
    path = unquote(parsed.path)
    fragment = unquote(parsed.fragment)
    return path, fragment


def check_file(path: Path, root: Path = ROOT) -> list[LinkProblem]:
    problems: list[LinkProblem] = []
    rel_parent = path.parent
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        for match in MARKDOWN_LINK_RE.finditer(line):
            raw_target = match.group(1).strip("<>")
            parsed = urlsplit(raw_target)
            if parsed.scheme in IGNORED_SCHEMES or raw_target.startswith("#"):
                continue

            target_path, fragment = split_target(raw_target)
            target_file = path if not target_path else (rel_parent / target_path).resolve()
            try:
                target_file.relative_to(root.resolve())
            except ValueError:
                problems.append(
                    LinkProblem(path, line_number, raw_target, "local link escapes repository root")
                )
                continue

            if not target_file.exists():
                problems.append(
                    LinkProblem(path, line_number, raw_target, "target file does not exist")
                )
                continue
            if target_file.is_dir():
                continue
            if fragment and target_file.suffix.lower() == ".md":
                anchors = anchors_for(target_file)
                if fragment not in anchors:
                    problems.append(
                        LinkProblem(
                            path,
                            line_number,
                            raw_target,
                            f"heading anchor #{fragment} not found",
                        )
                    )
    return problems


def check_docs(root: Path = ROOT) -> list[LinkProblem]:
    problems: list[LinkProblem] = []
    for path in markdown_files(root):
        problems.extend(check_file(path, root))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to check")
    args = parser.parse_args()
    root = args.root.resolve()
    problems = check_docs(root)
    if problems:
        print("FAIL: Markdown docs contain broken local links:")
        for problem in problems:
            rel = problem.path.relative_to(root)
            print(f"- {rel}:{problem.line_number}: {problem.target} ({problem.message})")
        return 1
    print(f"OK: checked {len(markdown_files(root))} Markdown files for local links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
