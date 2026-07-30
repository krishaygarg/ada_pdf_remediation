"""Tests for form fields, outlines, and TOC audit rules."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from remediator.audit import audit_document


class TestFormFieldsAudit:
    def test_form_fields_without_tu_and_struct_tree_fail(self, tmp_path: Path) -> None:
        from tests.pdf_factory import build_text_pdf

        path = tmp_path / "form.pdf"
        build_text_pdf(path)

        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            field = pdf.make_indirect(
                pikepdf.Dictionary(
                    FT=pikepdf.Name("/Tx"),
                    T=pikepdf.String("FirstName"),
                )
            )
            pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([field]))
            pdf.save(path)

        report = audit_document(path)
        conditions = [f.condition for f in report.findings]
        assert "27-002" in conditions  # missing /TU
        tu_finding = next(f for f in report.findings if f.condition == "27-002")
        assert "FirstName" in tu_finding.message

    def test_form_field_with_tu_passes(self, tmp_path: Path) -> None:
        from tests.pdf_factory import build_text_pdf

        path = tmp_path / "valid_form.pdf"
        build_text_pdf(path)

        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            field = pdf.make_indirect(
                pikepdf.Dictionary(
                    FT=pikepdf.Name("/Tx"),
                    T=pikepdf.String("FirstName"),
                    TU=pikepdf.String("First name input field"),
                )
            )
            pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([field]))
            pdf.save(path)

        report = audit_document(path)
        conditions = [f.condition for f in report.findings]
        assert "27-002" not in conditions


class TestTOCAndNavigationAudit:
    def test_toc_without_toci_fails(self, tmp_path: Path) -> None:
        from tests.pdf_factory import build_text_pdf

        path = tmp_path / "bad_toc.pdf"
        build_text_pdf(path)

        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            toc = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/TOC"),
                    P=pdf.Root,
                )
            )
            pdf.Root.StructTreeRoot = pikepdf.Dictionary(
                Type=pikepdf.Name("/StructTreeRoot"),
                K=pikepdf.Array([toc]),
            )
            pdf.save(path)

        report = audit_document(path)
        conditions = [f.condition for f in report.findings]
        assert "20-001" in conditions

    def test_toc_with_toci_passes(self, tmp_path: Path) -> None:
        from tests.pdf_factory import build_text_pdf

        path = tmp_path / "good_toc.pdf"
        build_text_pdf(path)

        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            toc = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/TOC"),
                    P=pdf.Root,
                )
            )
            toci = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/TOCI"),
                    P=toc,
                )
            )
            toc.K = pikepdf.Array([toci])
            pdf.Root.StructTreeRoot = pikepdf.Dictionary(
                Type=pikepdf.Name("/StructTreeRoot"),
                K=pikepdf.Array([toc]),
            )
            pdf.save(path)

        report = audit_document(path)
        conditions = [f.condition for f in report.findings]
        assert "20-001" not in conditions
