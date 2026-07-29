"""Tests that the distribution is installable and its console scripts resolve.

The console scripts previously pointed at top-level modules that were excluded
from the wheel, so ``pip install .`` produced commands that raised
``ModuleNotFoundError`` on launch. Only an installed-artifact test catches that
class of defect; running from a source checkout hides it because the repository
root happens to be on ``sys.path``.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

try:  # standard from 3.11, backported by tomli for 3.10
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def manifest() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class TestManifest:
    def test_declared_entry_points_are_importable(self, manifest: dict) -> None:
        from importlib import import_module

        scripts = manifest["project"]["scripts"]
        assert scripts, "no console scripts declared"
        for target in scripts.values():
            module_name, _, attribute = target.partition(":")
            module = import_module(module_name)
            assert callable(getattr(module, attribute))

    def test_entry_points_live_inside_the_installed_package(self, manifest: dict) -> None:
        """Every script target must sit under a package the wheel actually ships."""
        included = manifest["tool"]["setuptools"]["packages"]["find"]["include"]
        prefixes = tuple(entry.rstrip("*") for entry in included)
        for target in manifest["project"]["scripts"].values():
            module_name = target.split(":", 1)[0]
            assert module_name.startswith(prefixes), (
                f"console script {target!r} points at {module_name!r}, which is not "
                f"covered by the packaged modules {included}"
            )

    def test_metadata_is_populated(self, manifest: dict) -> None:
        project = manifest["project"]
        assert project["description"].strip()
        assert project["keywords"]
        assert project["classifiers"]
        assert project["urls"]["Repository"]

    def test_requires_python_matches_the_lowest_tested_classifier(self, manifest: dict) -> None:
        project = manifest["project"]
        versions = sorted(
            line.rsplit(" :: ", 1)[-1]
            for line in project["classifiers"]
            if line.startswith("Programming Language :: Python :: 3.")
        )
        assert project["requires-python"] == f">={versions[0]}"


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a wheel once and hand its path to the packaging tests."""
    pytest.importorskip("build", reason="the 'build' package is required to test packaging")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.mark.slow
class TestBuiltWheel:
    def test_wheel_contains_the_cli_package(self, wheel: Path) -> None:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
        assert "remediator/cli/__init__.py" in names
        assert "remediator/cli/remediate.py" in names
        assert "remediator/cli/compliance.py" in names

    def test_wheel_declares_both_console_scripts(self, wheel: Path) -> None:
        with zipfile.ZipFile(wheel) as archive:
            entry_points = next(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith(".dist-info/entry_points.txt")
            )
        assert "remediate-pdf" in entry_points
        assert "check-compliance" in entry_points
