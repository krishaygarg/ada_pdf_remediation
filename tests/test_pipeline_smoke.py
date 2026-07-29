"""End-to-end smoke coverage for the remediation pipeline.

These tests assert the properties the pipeline is supposed to guarantee today.
Structural defects are given dedicated regression tests alongside the change
that fixes them, so this module stays focused on the happy path.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from remediator.pipeline import remediate_single_pdf
from tests.pdf_factory import iter_struct_elements, page_mcids


@pytest.fixture
def remediated(make_text_pdf: object, tmp_path: Path) -> Path:
    source = make_text_pdf(pages=2)  # type: ignore[operator]
    target = tmp_path / "remediated.pdf"
    remediate_single_pdf(str(source), str(target))
    return target


class TestPipelineContract:
    def test_missing_input_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            remediate_single_pdf(str(tmp_path / "absent.pdf"), str(tmp_path / "out.pdf"))

    def test_output_is_a_readable_pdf_with_the_same_page_count(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            assert len(pdf.pages) == 2

    def test_document_language_is_declared(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            assert str(pdf.Root.Lang) == "en-US"

    def test_document_is_marked_as_tagged(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            assert bool(pdf.Root.MarkInfo.Marked) is True

    def test_viewer_is_told_to_display_the_document_title(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            assert bool(pdf.Root.ViewerPreferences.DisplayDocTitle) is True

    def test_structure_tree_and_parent_tree_exist(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            root = pdf.Root.StructTreeRoot
            assert str(root.Type) == "/StructTreeRoot"
            assert "/ParentTree" in root

    def test_every_page_declares_a_struct_parents_index(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            indices = [int(page["/StructParents"]) for page in pdf.pages]
        assert indices == sorted(set(indices)) == list(range(len(indices)))

    def test_pages_declare_structural_tab_order(self, remediated: Path) -> None:
        """PDF/UA requires tab order to follow structure, expressed as /Tabs /S."""
        with pikepdf.open(remediated) as pdf:
            assert all(str(page["/Tabs"]) == "/S" for page in pdf.pages)

    def test_text_is_wrapped_in_marked_content(self, remediated: Path) -> None:
        assert all(mcids for mcids in page_mcids(remediated))

    def test_marked_content_ids_are_unique_and_dense_per_page(self, remediated: Path) -> None:
        for mcids in page_mcids(remediated):
            assert len(mcids) == len(set(mcids)), "duplicate MCID within a page"
            assert mcids == list(range(len(mcids))), "MCIDs are not dense from zero"

    def test_structure_elements_are_produced(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            elements = list(iter_struct_elements(pdf))
        assert elements
        assert all("/S" in element for element in elements)

    def test_every_font_gains_a_tounicode_map(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            fonts = [
                obj
                for obj in pdf.objects
                if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == pikepdf.Name("/Font")
            ]
            assert fonts
            assert all("/ToUnicode" in font for font in fonts)

    def test_xmp_metadata_stream_is_written(self, remediated: Path) -> None:
        with pikepdf.open(remediated) as pdf:
            metadata = pdf.Root.Metadata.read_bytes().decode("utf-8")
        assert "pdfuaid:part" in metadata


class TestDeterminism:
    def test_two_runs_produce_the_same_structure(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        """Reruns must agree on tagging, otherwise golden comparison is useless.

        Timestamps legitimately differ between runs, so the assertion covers the
        structural output rather than the raw bytes.
        """
        source = make_text_pdf(pages=2)  # type: ignore[operator]
        first = tmp_path / "first.pdf"
        second = tmp_path / "second.pdf"
        remediate_single_pdf(str(source), str(first))
        remediate_single_pdf(str(source), str(second))
        assert page_mcids(first) == page_mcids(second)

        def tags(path: Path) -> list[str]:
            with pikepdf.open(path) as pdf:
                return [str(element.get("/S")) for element in iter_struct_elements(pdf)]

        assert tags(first) == tags(second)


@pytest.mark.slow
class TestRealDocument:
    def test_committed_sample_survives_remediation(self, sample_pdf: Path, tmp_path: Path) -> None:
        target = tmp_path / "physics.pdf"
        remediate_single_pdf(str(sample_pdf), str(target))
        with pikepdf.open(sample_pdf) as before, pikepdf.open(target) as after:
            assert len(after.pages) == len(before.pages)
        assert all(mcids for mcids in page_mcids(target))

    def test_remediation_preserves_extractable_text_volume(
        self, sample_pdf: Path, tmp_path: Path
    ) -> None:
        """Tagging must not destroy the text layer it is describing."""
        fitz = pytest.importorskip("fitz")
        target = tmp_path / "physics.pdf"
        remediate_single_pdf(str(sample_pdf), str(target))

        def visible_characters(path: Path) -> int:
            with fitz.open(path) as doc:
                return sum(len("".join(page.get_text().split())) for page in doc)

        before = visible_characters(sample_pdf)
        after = visible_characters(target)
        assert before > 0
        assert after >= before * 0.9, (
            f"remediation dropped extractable text: {before} characters before, {after} after"
        )
