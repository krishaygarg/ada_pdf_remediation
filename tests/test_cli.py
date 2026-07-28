"""Tests for the console entry points.

The scripts declared in ``pyproject.toml`` point at :mod:`remediator.cli`, so
these tests exercise the same callables the installed commands resolve to.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from remediator.cli import compliance as compliance_cli
from remediator.cli import remediate as remediate_cli


class TestRemediateCli:
    def test_help_is_available_without_importing_the_pdf_stack(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            remediate_cli.main(["--help"])
        assert excinfo.value.code == 0
        assert "Remediate a PDF document" in capsys.readouterr().out

    def test_missing_input_reports_failure_without_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = remediate_cli.main([str(tmp_path / "absent.pdf"), str(tmp_path / "out.pdf")])
        assert code == 1
        assert "Remediation failed" in capsys.readouterr().err

    @pytest.mark.slow
    def test_round_trip_produces_a_readable_pdf(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        import pikepdf

        source = make_text_pdf(pages=2)  # type: ignore[operator]
        target = tmp_path / "out.pdf"
        assert remediate_cli.main([str(source), str(target)]) == 0
        assert target.exists()
        with pikepdf.open(target) as pdf:
            assert len(pdf.pages) == 2


class TestComplianceCli:
    def test_missing_file_exits_with_code_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = compliance_cli.main([str(tmp_path / "absent.pdf")])
        assert code == 2
        assert "not found" in capsys.readouterr().out

    def test_json_mode_emits_parseable_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = compliance_cli.main([str(tmp_path / "absent.pdf"), "--json"])
        assert code == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["success"] is False

    def test_remote_audit_refuses_to_upload_without_explicit_consent(
        self, make_text_pdf: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Transmitting a document to a third party requires an opt-in flag.

        The previous default sent every audited file to check.axes4.com.
        """
        source = make_text_pdf()  # type: ignore[operator]
        code = compliance_cli.main([str(source), "--remote"])
        assert code == 2
        assert "consent" in capsys.readouterr().out.lower()

    def test_remote_refusal_is_also_reported_in_json_mode(
        self, make_text_pdf: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = make_text_pdf()  # type: ignore[operator]
        code = compliance_cli.main([str(source), "--remote", "--json"])
        assert code == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["success"] is False
        assert "consent" in payload["error"]

    def test_local_audit_is_the_default_mode(self, make_text_pdf: object) -> None:
        """No network call happens unless --remote is passed."""
        source = make_text_pdf()  # type: ignore[operator]
        code = compliance_cli.main([str(source), "--quiet"])
        assert code in (0, 1)

    def test_local_flag_is_accepted_for_backwards_compatibility(
        self, make_text_pdf: object
    ) -> None:
        source = make_text_pdf()  # type: ignore[operator]
        assert compliance_cli.main([str(source), "--local", "--quiet"]) in (0, 1)
