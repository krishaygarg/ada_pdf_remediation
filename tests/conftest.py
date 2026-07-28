"""Shared pytest fixtures and environment guards."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from tests import pdf_factory  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_scratch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the package scratch directory into the test's temp directory.

    Without this the suite would write into the working copy's ``tmp/``, which
    makes tests order dependent and leaves debris behind after a failure.
    """
    monkeypatch.setenv("ADA_REMEDIATOR_TMP", str(tmp_path / "scratch"))


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def sample_pdf() -> Path:
    """The checked-in physics sample, skipped if it is unavailable."""
    path = REPO_ROOT / "samples" / "physics" / "physics.pdf"
    if not path.exists():  # pragma: no cover - sample is committed
        pytest.skip("samples/physics/physics.pdf is not present")
    return path


@pytest.fixture
def make_text_pdf(tmp_path: Path) -> Callable[..., Path]:
    """Return a builder for simple text-bearing PDFs."""

    counter = {"n": 0}

    def _build(**kwargs: object) -> Path:
        counter["n"] += 1
        target = tmp_path / f"text_{counter['n']}.pdf"
        return pdf_factory.build_text_pdf(target, **kwargs)  # type: ignore[arg-type]

    return _build


@pytest.fixture
def linked_pdf(tmp_path: Path) -> Path:
    """A one-page PDF containing a Link annotation."""
    return pdf_factory.build_pdf_with_link(tmp_path / "linked.pdf")


def _binary_available(name: str) -> bool:
    return shutil.which(name) is not None


requires_tesseract = pytest.mark.skipif(
    not _binary_available("tesseract"),
    reason="Tesseract binary is not installed",
)

requires_verapdf = pytest.mark.skipif(
    not _binary_available("verapdf"),
    reason="veraPDF CLI is not installed",
)
