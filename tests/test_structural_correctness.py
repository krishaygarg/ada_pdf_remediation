"""Regression tests for structural defects in the produced documents.

Each test here corresponds to a specific requirement of ISO 32000-1 or
ISO 14289-1 and fails against the behaviour that preceded this change.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from remediator.pipeline import PDFUA_ID_NAMESPACE, remediate_single_pdf
from tests.pdf_factory import graphics_stack_depths, page_mcids


@pytest.fixture
def remediated(make_text_pdf: object, tmp_path: Path) -> Path:
    source = make_text_pdf(pages=3)  # type: ignore[operator]
    target = tmp_path / "remediated.pdf"
    remediate_single_pdf(str(source), str(target))
    return target


@pytest.fixture
def remediated_with_link(linked_pdf: Path, tmp_path: Path) -> Path:
    target = tmp_path / "linked_remediated.pdf"
    remediate_single_pdf(str(linked_pdf), str(target))
    return target


class TestGraphicsStackBalance:
    """A content stream must not pop a graphics state it never pushed.

    The page previously emitted one 'q' and two 'Q' operators, so the stack
    underflowed on every page of every produced document.
    """

    def test_stack_returns_to_zero_on_every_page(self, remediated: Path) -> None:
        for index, (final_depth, _) in enumerate(graphics_stack_depths(remediated)):
            assert final_depth == 0, f"page {index + 1} ends at stack depth {final_depth}"

    def test_stack_never_underflows(self, remediated: Path) -> None:
        for index, (_, minimum) in enumerate(graphics_stack_depths(remediated)):
            assert minimum >= 0, f"page {index + 1} pops an empty graphics stack"

    @pytest.mark.slow
    def test_stack_is_balanced_for_the_committed_sample(
        self, sample_pdf: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "physics.pdf"
        remediate_single_pdf(str(sample_pdf), str(target))
        assert all(depths == (0, 0) for depths in graphics_stack_depths(target))


class TestPdfUaIdentification:
    """ISO 14289-1 clause 5 fixes the identification namespace URI.

    The conventional prefix is 'pdfuaid' but the URI path segment is 'pdfua'.
    Emitting the prefix as the path produced documents that no conforming
    validator recognised as PDF/UA.
    """

    def _metadata(self, path: Path) -> str:
        with pikepdf.open(path) as pdf:
            return pdf.Root.Metadata.read_bytes().decode("utf-8")

    def test_identification_uses_the_namespace_from_the_standard(self, remediated: Path) -> None:
        assert PDFUA_ID_NAMESPACE == "http://www.aiim.org/pdfua/ns/id/"
        assert PDFUA_ID_NAMESPACE in self._metadata(remediated)

    def test_the_incorrect_namespace_is_absent(self, remediated: Path) -> None:
        assert "aiim.org/pdfuaid/ns/id/" not in self._metadata(remediated)

    def test_the_part_property_declares_part_one(self, remediated: Path) -> None:
        assert "<pdfuaid:part>1</pdfuaid:part>" in self._metadata(remediated)

    def test_metadata_is_well_formed_xml(self, remediated: Path) -> None:
        import xml.etree.ElementTree as ET

        raw = self._metadata(remediated)
        body = raw[raw.index("<x:xmpmeta") : raw.index("</x:xmpmeta>") + len("</x:xmpmeta>")]
        root = ET.fromstring(body)
        parts = root.findall(f".//{{{PDFUA_ID_NAMESPACE}}}part")
        assert [element.text for element in parts] == ["1"]

    def test_a_title_containing_markup_is_escaped(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        """An unescaped title would produce a malformed metadata packet."""
        import xml.etree.ElementTree as ET

        source = make_text_pdf(title='Tables & <Figures> in "Physics"')  # type: ignore[operator]
        target = tmp_path / "escaped.pdf"
        remediate_single_pdf(str(source), str(target))
        raw = self._metadata(target)
        body = raw[raw.index("<x:xmpmeta") : raw.index("</x:xmpmeta>") + len("</x:xmpmeta>")]
        ET.fromstring(body)


class TestStructureParentKeys:
    """Pages and annotations must not share a structure parent key.

    ISO 32000-1 14.7.4.4: a page's /StructParents indexes an array of elements
    keyed by marked-content identifier, while an annotation's /StructParent
    resolves to a single element. Assigning the page index to both made one key
    mean two incompatible things.
    """

    def test_the_document_has_a_link_to_exercise(self, remediated_with_link: Path) -> None:
        with pikepdf.open(remediated_with_link) as pdf:
            links = [
                annot
                for annot in pdf.pages[0].get("/Annots", [])
                if annot.get("/Subtype") == pikepdf.Name("/Link")
            ]
        assert len(links) == 1

    def test_annotation_key_differs_from_every_page_key(self, remediated_with_link: Path) -> None:
        with pikepdf.open(remediated_with_link) as pdf:
            page_keys = {int(page["/StructParents"]) for page in pdf.pages}
            annotation_keys = {
                int(annot["/StructParent"])
                for page in pdf.pages
                for annot in page.get("/Annots", [])
                if "/StructParent" in annot
            }
        assert annotation_keys
        assert not (page_keys & annotation_keys), (
            f"page keys {sorted(page_keys)} collide with annotation keys {sorted(annotation_keys)}"
        )

    def test_annotation_key_resolves_to_a_single_element_not_an_array(
        self, remediated_with_link: Path
    ) -> None:
        from remediator.numbertree import lookup

        with pikepdf.open(remediated_with_link) as pdf:
            tree = pdf.Root.StructTreeRoot.ParentTree
            annot = next(
                a for a in pdf.pages[0]["/Annots"] if a.get("/Subtype") == pikepdf.Name("/Link")
            )
            resolved = lookup(tree, int(annot["/StructParent"]))
            assert resolved is not None
            assert not isinstance(resolved, pikepdf.Array), (
                "an annotation key must resolve to one element, not to a page array"
            )
            assert str(resolved.get("/S")) == "/Link"

    def test_page_key_resolves_to_an_array_indexed_by_mcid(
        self, remediated_with_link: Path
    ) -> None:
        from remediator.numbertree import lookup

        mcids_per_page = page_mcids(remediated_with_link)
        with pikepdf.open(remediated_with_link) as pdf:
            tree = pdf.Root.StructTreeRoot.ParentTree
            for page, mcids in zip(pdf.pages, mcids_per_page, strict=True):
                array = lookup(tree, int(page["/StructParents"]))
                assert isinstance(array, pikepdf.Array)
                for mcid in mcids:
                    element = array[mcid]
                    assert int(element["/K"]) == mcid, (
                        f"entry at index {mcid} describes MCID {int(element['/K'])}"
                    )

    def test_the_link_element_carries_an_object_reference(self, remediated_with_link: Path) -> None:
        with pikepdf.open(remediated_with_link) as pdf:
            root = pdf.Root.StructTreeRoot.K
            link = next(kid for kid in root.K if str(kid.get("/S")) == "/Link")
            objr = link["/K"]
            assert str(objr["/Type"]) == "/OBJR"
            assert objr["/Obj"].get("/Subtype") == pikepdf.Name("/Link")

    def test_next_key_is_recorded_above_every_key_in_use(self, remediated_with_link: Path) -> None:
        with pikepdf.open(remediated_with_link) as pdf:
            next_key = int(pdf.Root.StructTreeRoot.ParentTreeNextKey)
            used = {int(page["/StructParents"]) for page in pdf.pages}
            used |= {
                int(annot["/StructParent"])
                for page in pdf.pages
                for annot in page.get("/Annots", [])
                if "/StructParent" in annot
            }
        assert next_key > max(used)

    def test_documents_without_annotations_still_build_a_valid_tree(self, remediated: Path) -> None:
        from remediator.numbertree import validate_number_tree

        with pikepdf.open(remediated) as pdf:
            keys = [int(page["/StructParents"]) for page in pdf.pages]
            validate_number_tree(pdf.Root.StructTreeRoot.ParentTree, keys)


class TestLinkDescription:
    """ISO 14289-1 7.18.5 requires a link to carry an alternate description."""

    def _link(self, path: Path, pdf: pikepdf.Pdf) -> pikepdf.Object:
        return next(
            annot
            for annot in pdf.pages[0]["/Annots"]
            if annot.get("/Subtype") == pikepdf.Name("/Link")
        )

    def test_contents_is_populated(self, remediated_with_link: Path) -> None:
        with pikepdf.open(remediated_with_link) as pdf:
            contents = str(self._link(remediated_with_link, pdf)["/Contents"])
        assert contents.strip()

    def test_the_description_names_the_destination(self, remediated_with_link: Path) -> None:
        """A generic word such as 'Hyperlink' repeats what the tag already says."""
        with pikepdf.open(remediated_with_link) as pdf:
            contents = str(self._link(remediated_with_link, pdf)["/Contents"])
        assert contents == "Link to https://example.org/"

    def test_an_existing_description_is_preserved(self, tmp_path: Path) -> None:
        """An author-supplied description must not be overwritten."""
        from tests.pdf_factory import build_pdf_with_link

        source = build_pdf_with_link(tmp_path / "described.pdf")
        with pikepdf.open(source, allow_overwriting_input=True) as pdf:
            pdf.pages[0]["/Annots"][0]["/Contents"] = pikepdf.String("Read the syllabus")
            pdf.save(source)

        target = tmp_path / "out.pdf"
        remediate_single_pdf(str(source), str(target))
        with pikepdf.open(target) as pdf:
            assert str(self._link(target, pdf)["/Contents"]) == "Read the syllabus"

    def test_an_internal_destination_is_described_without_a_uri(self, tmp_path: Path) -> None:
        from tests.pdf_factory import build_pdf_with_link

        source = build_pdf_with_link(tmp_path / "internal.pdf")
        with pikepdf.open(source, allow_overwriting_input=True) as pdf:
            annot = pdf.pages[0]["/Annots"][0]
            del annot["/A"]
            annot["/Dest"] = pikepdf.Array([pdf.pages[0].obj, pikepdf.Name("/Fit")])
            pdf.save(source)

        target = tmp_path / "out.pdf"
        remediate_single_pdf(str(source), str(target))
        with pikepdf.open(target) as pdf:
            contents = str(self._link(target, pdf)["/Contents"])
        assert contents == "Link to another location in this document"


class TestInputProtection:
    def test_writing_over_the_input_is_refused(self, make_text_pdf: object) -> None:
        """Overwriting the source would destroy the original on a partial failure."""
        source = make_text_pdf()  # type: ignore[operator]
        with pytest.raises(ValueError, match="Refusing to overwrite"):
            remediate_single_pdf(str(source), str(source))
