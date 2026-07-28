"""Cross-check the conformance engine against veraPDF.

An auditor written by the same people as the writer it audits is not
independent evidence. This project already demonstrated the failure mode: the
old auditor searched for the PDF/UA identifier under the same incorrect
namespace the pipeline wrote, so it confirmed the defect instead of catching
it, and reported full compliance on documents no conforming validator would
accept.

These tests hold the engine against veraPDF, the reference implementation. The
two do not agree rule for rule, and they are not supposed to: the Matterhorn
Protocol has 136 failure conditions and veraPDF implements the machine
determinable subset, while this engine additionally reports quality problems
that conform but obstruct a reader. The invariant that must hold is one
directional:

    If veraPDF rejects a document, this engine must not call it clean.

The reverse is allowed and is exercised explicitly, because reporting more than
the reference is the point of checks such as character map quality.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pikepdf
import pytest

from remediator.audit import audit_document
from remediator.pipeline import remediate_single_pdf
from tests import verapdf

pytestmark = [
    pytest.mark.slow,
    pytest.mark.requires_verapdf,
    pytest.mark.skipif(not verapdf.available(), reason="veraPDF CLI is not installed"),
]

#: Defects where the correspondence between the two implementations is exact.
#: Each entry is (name, mutation, veraPDF rule, this engine's condition).
Mutation = Callable[[pikepdf.Pdf], None]


def _break_pdfua_identifier(pdf: pikepdf.Pdf) -> None:
    text = pdf.Root.Metadata.read_bytes().decode("utf-8")
    text = text.replace("http://www.aiim.org/pdfua/ns/id/", "http://example.invalid/ns/id/")
    stream = pikepdf.Stream(pdf, text.encode("utf-8"))
    stream.Type = pikepdf.Name("/Metadata")
    stream.Subtype = pikepdf.Name("/XML")
    pdf.Root["/Metadata"] = stream


def _break_display_doc_title(pdf: pikepdf.Pdf) -> None:
    pdf.Root.ViewerPreferences["/DisplayDocTitle"] = False


def _break_mark_info(pdf: pikepdf.Pdf) -> None:
    del pdf.Root["/MarkInfo"]


def _break_structure_tree(pdf: pikepdf.Pdf) -> None:
    del pdf.Root["/StructTreeRoot"]


def _break_language(pdf: pikepdf.Pdf) -> None:
    del pdf.Root["/Lang"]


def _break_link_description(pdf: pikepdf.Pdf) -> None:
    for page in pdf.pages:
        for annot in page.obj.get("/Annots", []):
            if "/Contents" in annot:
                del annot["/Contents"]


CORRESPONDENCES: list[tuple[str, Mutation, str, str]] = [
    ("pdfua identifier", _break_pdfua_identifier, "5-1", "06-004"),
    ("display doc title", _break_display_doc_title, "7.1-10", "06-003"),
    ("mark info", _break_mark_info, "6.2-1", "07-001"),
    ("structure tree", _break_structure_tree, "7.1-11", "01-003"),
    # veraPDF expresses a missing default language as the natural language of
    # the page content being undeterminable, rather than as a missing catalogue
    # entry, so the corresponding rule is 7.2-34 rather than 7.2-1.
    ("document language", _break_language, "7.2-34", "11-001"),
]


@pytest.fixture
def conforming(sample_pdf: Path, tmp_path: Path) -> Path:
    """A document that both implementations agree conforms."""
    target = tmp_path / "conforming.pdf"
    remediate_single_pdf(str(sample_pdf), str(target))
    return target


class TestBaselineAgreement:
    def test_both_accept_a_conforming_document(self, conforming: Path) -> None:
        reference = verapdf.validate(conforming)
        assert reference.compliant, reference.describe()

        ours = audit_document(conforming)
        # Character map quality is deliberately stricter than the reference, so
        # it is excluded from the agreement check and covered separately below.
        blocking = [f for f in ours.errors if f.checkpoint != "10"]
        assert not blocking, [f"{f.condition}: {f.message}" for f in blocking]

    def test_both_reject_an_untagged_document(self, sample_pdf: Path) -> None:
        reference = verapdf.validate(sample_pdf)
        ours = audit_document(sample_pdf)
        assert not reference.compliant
        assert not ours.conformant


class TestDirectionalInvariant:
    """The engine must never call clean what the reference rejects."""

    @pytest.mark.parametrize(
        ("name", "mutation", "reference_rule", "condition"),
        CORRESPONDENCES,
        ids=[entry[0] for entry in CORRESPONDENCES],
    )
    def test_a_defect_is_seen_by_both_implementations(
        self,
        conforming: Path,
        tmp_path: Path,
        name: str,
        mutation: Mutation,
        reference_rule: str,
        condition: str,
    ) -> None:
        damaged = tmp_path / f"damaged_{condition}.pdf"
        with pikepdf.open(conforming) as pdf:
            mutation(pdf)
            pdf.save(damaged)

        reference = verapdf.validate(damaged)
        ours = audit_document(damaged)

        assert not reference.compliant, f"veraPDF did not notice the {name} defect"
        assert reference_rule in {f.identifier for f in reference.failures}, (
            f"expected veraPDF rule {reference_rule}; got {reference.describe()}"
        )
        assert condition in {f.condition for f in ours.errors}, (
            f"this engine did not report {condition}; reported {[f.condition for f in ours.errors]}"
        )

    def test_link_defects_are_seen_by_both(self, linked_pdf: Path, tmp_path: Path) -> None:
        good = tmp_path / "linked_good.pdf"
        remediate_single_pdf(str(linked_pdf), str(good))
        damaged = tmp_path / "linked_damaged.pdf"
        with pikepdf.open(good) as pdf:
            _break_link_description(pdf)
            pdf.save(damaged)

        reference = verapdf.validate(damaged)
        ours = audit_document(damaged)
        assert "7.18.5-2" in {f.identifier for f in reference.failures}, reference.describe()
        assert "28-011" in {f.condition for f in ours.errors}


class TestDeliberateDivergence:
    """Where the engine reports more than the reference, and why."""

    def test_character_map_quality_is_reported_although_verapdf_accepts_it(
        self, conforming: Path
    ) -> None:
        """The reference checks that a /ToUnicode map exists, not that it works.

        The bundled sample is remediated with a fallback that maps unmapped
        codes to a space. veraPDF accepts the result. Extracting the text shows
        the en dash and the increment operator have been replaced, so the
        document scores as conformant while being less readable than before it
        was processed.
        """
        reference = verapdf.validate(conforming)
        assert reference.compliant, reference.describe()

        ours = audit_document(conforming, include=["10-003"])
        assert ours.errors, (
            "the engine should report degenerate character maps that the "
            "reference validator accepts"
        )

    def test_unembedded_fonts_are_reported_by_both(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        source = make_text_pdf(pages=1)  # type: ignore[operator]
        target = tmp_path / "unembedded.pdf"
        remediate_single_pdf(str(source), str(target))

        reference = verapdf.validate(target)
        ours = audit_document(target, include=["31-001"])
        assert "7.21.4.1-1" in {f.identifier for f in reference.failures}
        assert "31-001" in {f.condition for f in ours.errors}
