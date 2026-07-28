"""End-to-end conformance checks against the reference validator.

These are the tests that make a compliance claim credible: the assertion comes
from veraPDF, an independent implementation, rather than from this project's
own auditor.

They skip when veraPDF is absent. CI installs it, so the gate is enforced there
even when a contributor runs without a Java runtime locally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remediator.pipeline import remediate_single_pdf
from tests import verapdf

pytestmark = [
    pytest.mark.slow,
    pytest.mark.requires_verapdf,
    pytest.mark.skipif(not verapdf.available(), reason="veraPDF CLI is not installed"),
]


def _remediate(source: Path, tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    remediate_single_pdf(str(source), str(target))
    return target


class TestPdfUaConformance:
    def test_the_committed_sample_conforms(self, sample_pdf: Path, tmp_path: Path) -> None:
        result = verapdf.validate(_remediate(sample_pdf, tmp_path, "physics.pdf"))
        assert result.compliant, result.describe()

    def test_a_generated_multi_page_document_conforms(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        source = make_text_pdf(pages=4)  # type: ignore[operator]
        result = verapdf.validate(_remediate(source, tmp_path, "generated.pdf"))
        # The generated fixture uses a standard font that is not embedded, which
        # the pipeline cannot supply. That single rule is expected; anything
        # else is a regression.
        remaining = [f for f in result.failures if f.identifier != "7.21.4.1-1"]
        assert not remaining, result.describe()

    def test_the_untouched_source_does_not_conform(self, sample_pdf: Path) -> None:
        """Guards against the suite passing because validation silently no-ops."""
        result = verapdf.validate(sample_pdf)
        assert not result.compliant

    def test_link_annotations_do_not_introduce_failures(
        self, linked_pdf: Path, tmp_path: Path
    ) -> None:
        result = verapdf.validate(_remediate(linked_pdf, tmp_path, "linked_out.pdf"))
        annotation_rules = {"7.18.1-2", "7.18.5-2", "7.18.5-1"}
        offending = [f for f in result.failures if f.identifier in annotation_rules]
        assert not offending, result.describe()


class TestKnownLimitations:
    """Documents gaps honestly rather than leaving them as silent surprises."""

    def test_unembedded_fonts_are_reported_by_the_validator(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        """The pipeline cannot embed a font program it was never given.

        ISO 14289-1 7.21.4.1 requires every rendered font to be embedded. When
        a source document references a standard font without embedding it, the
        output inherits that failure. Recording the behaviour here keeps it from
        being mistaken for a regression later.
        """
        source = make_text_pdf(pages=1)  # type: ignore[operator]
        result = verapdf.validate(_remediate(source, tmp_path, "unembedded.pdf"))
        assert any(f.identifier == "7.21.4.1-1" for f in result.failures), result.describe()
