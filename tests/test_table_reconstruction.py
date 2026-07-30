"""Tests for automatic table structure reconstruction and audit compliance."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from remediator.audit import audit_document
from remediator.pipeline import build_table_element


class TestTableReconstruction:
    def test_build_table_element_creates_valid_pdfua_structure(self, tmp_path: Path) -> None:
        from tests.pdf_factory import build_text_pdf

        path = tmp_path / "table_doc.pdf"
        build_text_pdf(path)

        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            page = pdf.pages[0].obj
            raw_table = [
                ["Name", "Score", "Rank"],
                ["Alice", "95", "1"],
                ["Bob", "88", "2"],
            ]

            table_elem = build_table_element(
                pdf,
                raw_table,
                parent=pdf.Root,
                page=page,
            )

            pdf.Root.StructTreeRoot = pikepdf.Dictionary(
                Type=pikepdf.Name("/StructTreeRoot"),
                K=pikepdf.Array([table_elem]),
            )
            pdf.save(path)

        # Audit the document with table structure rules
        report = audit_document(path)
        conditions = [f.condition for f in report.findings]

        # Verify no table structural errors (15-003, 15-005, 15-006)
        assert "15-003" not in conditions  # table has TH header cells
        assert "15-005" not in conditions  # TH cells declare /Scope
        assert "15-006" not in conditions  # TD/TH inside TR
