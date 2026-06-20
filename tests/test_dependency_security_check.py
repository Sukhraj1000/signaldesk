from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dependency_security_check", ROOT / "scripts" / "dependency_security_check.py"
)
assert SPEC is not None
DEPENDENCY_SECURITY_CHECK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = DEPENDENCY_SECURITY_CHECK
SPEC.loader.exec_module(DEPENDENCY_SECURITY_CHECK)
check_requirements = DEPENDENCY_SECURITY_CHECK.check_requirements


def write_pyproject(tmp_path: Path, dependencies: str) -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "example"',
                'version = "0.0.0"',
                dependencies,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return pyproject


def test_dependency_security_check_accepts_lower_bounded_dependencies(tmp_path: Path) -> None:
    pyproject = write_pyproject(
        tmp_path,
        "\n".join(
            [
                'dependencies = ["typer>=0.12.0"]',
                "[project.optional-dependencies]",
                'dev = ["pytest>=8.2.0"]',
            ]
        ),
    )

    assert check_requirements(pyproject) == []


def test_dependency_security_check_requires_lower_bounds(tmp_path: Path) -> None:
    pyproject = write_pyproject(tmp_path, 'dependencies = ["typer"]')

    issues = check_requirements(pyproject)

    assert len(issues) == 1
    assert issues[0].message == "dependency must declare a lower bound such as >= or ~="


def test_dependency_security_check_rejects_direct_references(tmp_path: Path) -> None:
    pyproject = write_pyproject(
        tmp_path,
        'dependencies = ["example @ https://example.invalid/example-1.0.0.tar.gz"]',
    )

    issues = check_requirements(pyproject)

    assert any("direct URL/path dependencies" in issue.message for issue in issues)


def test_dependency_security_check_redacts_direct_reference_credentials(tmp_path: Path) -> None:
    pyproject = write_pyproject(
        tmp_path,
        'dependencies = ["example @ https://user:secret@example.invalid/pkg.whl?token=secret"]',
    )

    issues = check_requirements(pyproject)

    formatted = "\n".join(issue.format() for issue in issues)
    assert "user:secret" not in formatted
    assert "token=secret" not in formatted
    assert "https://example.invalid/pkg.whl?<redacted>" in formatted


def test_dependency_security_check_does_not_accept_marker_as_lower_bound(tmp_path: Path) -> None:
    pyproject = write_pyproject(
        tmp_path,
        'dependencies = ["typer; python_version >= \'3.12\'"]',
    )

    issues = check_requirements(pyproject)

    assert any("lower bound" in issue.message for issue in issues)


def test_dependency_security_check_rejects_wildcard_exact_pins(tmp_path: Path) -> None:
    pyproject = write_pyproject(tmp_path, 'dependencies = ["requests==2.*,>=2.0"]')

    issues = check_requirements(pyproject)

    assert any(issue.message == "wildcard or empty exact pins are not allowed" for issue in issues)


def test_dependency_security_check_rejects_denied_package_names(tmp_path: Path) -> None:
    pyproject = write_pyproject(tmp_path, 'dependencies = ["pycrypto>=2.6"]')

    issues = check_requirements(pyproject)

    assert any(issue.message == "package name is on the denied list" for issue in issues)
