"""Tests for workspace configuration and its absence of import side effects."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from remediator import config


class TestImportPurity:
    """Importing the package must not touch the filesystem or the environment."""

    def test_importing_the_package_creates_no_directory(self, tmp_path: Path) -> None:
        scratch = tmp_path / "should-not-exist"
        env = {**os.environ, "ADA_REMEDIATOR_TMP": str(scratch)}
        subprocess.run(
            [sys.executable, "-c", "import remediator, remediator.config"],
            check=True,
            env=env,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
        )
        assert not scratch.exists(), "importing the package created its scratch directory"

    def test_importing_the_package_does_not_mutate_tmpdir(self, tmp_path: Path) -> None:
        env = {**os.environ, "ADA_REMEDIATOR_TMP": str(tmp_path / "scratch"), "TMPDIR": "/sentinel"}
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, remediator.config; print(os.environ.get('TMPDIR'))",
            ],
            check=True,
            env=env,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "/sentinel"

    def test_version_is_importable_without_the_pdf_stack(self) -> None:
        """``__version__`` must not drag in pikepdf; health checks depend on it."""
        script = "\n".join(
            [
                "import sys, remediator",
                "print(remediator.__version__)",
                "print('pikepdf' in sys.modules)",
            ]
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
        )
        version, pikepdf_loaded = result.stdout.split()
        assert version
        assert pikepdf_loaded == "False"


class TestScratchDirectory:
    def test_get_tmp_dir_does_not_create_the_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "lazy"
        os.environ["ADA_REMEDIATOR_TMP"] = str(target)
        assert config.get_tmp_dir() == target
        assert not target.exists()

    def test_ensure_tmp_dir_creates_the_directory_and_is_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "eager"
        os.environ["ADA_REMEDIATOR_TMP"] = str(target)
        assert config.ensure_tmp_dir() == target
        assert target.is_dir()
        assert config.ensure_tmp_dir() == target

    def test_environment_variable_overrides_the_default(self, tmp_path: Path) -> None:
        override = tmp_path / "elsewhere"
        os.environ["ADA_REMEDIATOR_TMP"] = str(override)
        assert config.get_tmp_dir() == override


class TestConfigureWorkspaceTmp:
    def test_environment_is_redirected_inside_the_context(self, tmp_path: Path) -> None:
        target = tmp_path / "redirect"
        os.environ["ADA_REMEDIATOR_TMP"] = str(target)
        with config.configure_workspace_tmp() as path:
            assert path == target
            assert os.environ["TMPDIR"] == str(target)
            assert tempfile.tempdir == str(target)

    def test_previous_environment_is_restored_on_exit(self, tmp_path: Path) -> None:
        os.environ["ADA_REMEDIATOR_TMP"] = str(tmp_path / "restore")
        os.environ["TMPDIR"] = "/original"
        before = tempfile.tempdir
        with config.configure_workspace_tmp():
            pass
        assert os.environ["TMPDIR"] == "/original"
        assert tempfile.tempdir == before

    def test_environment_is_restored_even_when_the_body_raises(self, tmp_path: Path) -> None:
        os.environ["ADA_REMEDIATOR_TMP"] = str(tmp_path / "boom")
        os.environ["TMPDIR"] = "/original"

        def explode() -> None:
            with config.configure_workspace_tmp():
                raise RuntimeError("deliberate")

        with pytest.raises(RuntimeError, match="deliberate"):
            explode()
        assert os.environ["TMPDIR"] == "/original"

    def test_absent_variables_are_removed_again_rather_than_left_behind(
        self, tmp_path: Path
    ) -> None:
        os.environ["ADA_REMEDIATOR_TMP"] = str(tmp_path / "clean")
        os.environ.pop("TEMP", None)
        with config.configure_workspace_tmp():
            assert "TEMP" in os.environ
        assert "TEMP" not in os.environ
