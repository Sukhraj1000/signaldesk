from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("docs_check", ROOT / "scripts" / "docs_check.py")
assert SPEC is not None
DOCS_CHECK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = DOCS_CHECK
SPEC.loader.exec_module(DOCS_CHECK)
check_docs = DOCS_CHECK.check_docs
github_anchor = DOCS_CHECK.github_anchor


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_github_anchor_matches_common_markdown_headings() -> None:
    assert github_anchor("Runtime checks") == "runtime-checks"
    assert github_anchor("Provider Mode: default/enhanced") == "provider-mode-defaultenhanced"


def test_docs_check_accepts_existing_local_file_and_heading_links(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "See [guide](docs/guide.md#runtime-checks).\n")
    write(tmp_path / "docs" / "guide.md", "# Runtime checks\n")

    assert check_docs(tmp_path) == []


def test_docs_check_reports_missing_local_file(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "See [missing](docs/missing.md).\n")

    problems = check_docs(tmp_path)

    assert len(problems) == 1
    assert problems[0].target == "docs/missing.md"
    assert problems[0].message == "target file does not exist"


def test_docs_check_reports_missing_heading_anchor(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "See [guide](docs/guide.md#missing-heading).\n")
    write(tmp_path / "docs" / "guide.md", "# Present Heading\n")

    problems = check_docs(tmp_path)

    assert len(problems) == 1
    assert problems[0].target == "docs/guide.md#missing-heading"
    assert problems[0].message == "heading anchor #missing-heading not found"


def test_docs_check_accepts_same_file_heading_anchor(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "See [jump](#runtime-checks).\n\n## Runtime checks\n")

    assert check_docs(tmp_path) == []


def test_docs_check_reports_missing_same_file_heading_anchor(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "See [jump](#missing-heading).\n\n## Present Heading\n")

    problems = check_docs(tmp_path)

    assert len(problems) == 1
    assert problems[0].target == "#missing-heading"
    assert problems[0].message == "heading anchor #missing-heading not found"


def test_docs_check_ignores_external_links(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "See [site](https://example.com/missing.md#heading).\n")

    assert check_docs(tmp_path) == []
