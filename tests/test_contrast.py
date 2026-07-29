"""Tests for the contrast engine.

The colour metrics are checked against published reference values rather than
against this implementation's own output, because a self-consistent but wrong
contrast calculation would silently mis-grade every document.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remediator.contrast import (
    Rgb,
    Verdict,
    analyse_document,
    apca_contrast,
    clear_analysis_cache,
    contrast_ratio,
    delta_e,
    estimate_background,
    relative_luminance,
    summarise,
)
from remediator.contrast.analysis import (
    _estimate_background_vectorised,
    _srgb_array_to_lab,
)
from remediator.contrast.color import apca_screen_luminance, to_lab

BLACK = Rgb(0.0, 0.0, 0.0)
WHITE = Rgb(1.0, 1.0, 1.0)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_analysis_cache()


class TestWcagLuminance:
    def test_the_endpoints_are_exact(self) -> None:
        assert relative_luminance(WHITE) == pytest.approx(1.0)
        assert relative_luminance(BLACK) == pytest.approx(0.0)

    def test_black_on_white_is_the_maximum_ratio(self) -> None:
        assert contrast_ratio(BLACK, WHITE) == pytest.approx(21.0, abs=1e-9)

    @pytest.mark.parametrize(
        ("hex_value", "expected"),
        [
            (0x767676, 4.54),  # the classic AA boundary grey
            (0x949494, 3.03),
            (0x595959, 7.00),
            (0x000000, 21.00),
        ],
    )
    def test_published_values_against_white(self, hex_value: int, expected: float) -> None:
        """Figures taken from the WebAIM contrast checker."""
        assert contrast_ratio(Rgb.from_int(hex_value), WHITE) == pytest.approx(expected, abs=0.01)

    def test_the_ratio_is_symmetric(self) -> None:
        """A property APCA deliberately does not share."""
        a, b = Rgb.from_int(0x1A2B3C), Rgb.from_int(0xEEDDCC)
        assert contrast_ratio(a, b) == pytest.approx(contrast_ratio(b, a))

    def test_identical_colours_give_the_minimum_ratio(self) -> None:
        assert contrast_ratio(WHITE, WHITE) == pytest.approx(1.0)

    @given(
        st.integers(min_value=0, max_value=0xFFFFFF), st.integers(min_value=0, max_value=0xFFFFFF)
    )
    @settings(max_examples=200, deadline=None)
    def test_the_ratio_always_lies_in_range(self, first: int, second: int) -> None:
        ratio = contrast_ratio(Rgb.from_int(first), Rgb.from_int(second))
        assert 1.0 <= ratio <= 21.0 + 1e-9


class TestApca:
    @pytest.mark.parametrize(
        ("text", "background", "expected"),
        [
            (0x000000, 0xFFFFFF, 106.04),
            (0xFFFFFF, 0x000000, -107.88),
            (0x888888, 0xFFFFFF, 63.06),
            (0xFFFFFF, 0x888888, -68.54),
        ],
    )
    def test_published_reference_pairs(self, text: int, background: int, expected: float) -> None:
        """Values published with the APCA W3 0.1.9 reference implementation."""
        produced = apca_contrast(Rgb.from_int(text), Rgb.from_int(background))
        assert produced == pytest.approx(expected, abs=0.01)

    def test_polarity_is_signed(self) -> None:
        assert apca_contrast(BLACK, WHITE) > 0, "dark on light is positive"
        assert apca_contrast(WHITE, BLACK) < 0, "light on dark is negative"

    def test_the_metric_is_asymmetric(self) -> None:
        """The reason for reporting APCA alongside the WCAG 2 ratio.

        The same luminance separation reads differently depending on polarity,
        which a symmetric ratio cannot express.
        """
        forward = abs(apca_contrast(BLACK, WHITE))
        reverse = abs(apca_contrast(WHITE, BLACK))
        assert forward != pytest.approx(reverse)
        assert abs(forward - reverse) > 1.0

    def test_identical_colours_give_zero(self) -> None:
        assert apca_contrast(WHITE, WHITE) == 0.0
        assert apca_contrast(BLACK, BLACK) == 0.0

    def test_near_identical_colours_are_clipped_to_zero(self) -> None:
        """Below the low clip the result is noise, not contrast."""
        assert apca_contrast(Rgb.from_int(0xFEFEFE), WHITE) == 0.0

    def test_the_transfer_curve_is_not_the_wcag_one(self) -> None:
        """APCA uses a simple power curve; substituting WCAG's shifts everything."""
        grey = Rgb.from_int(0x808080)
        assert apca_screen_luminance(grey) != pytest.approx(relative_luminance(grey))

    @given(
        st.integers(min_value=0, max_value=0xFFFFFF), st.integers(min_value=0, max_value=0xFFFFFF)
    )
    @settings(max_examples=200, deadline=None)
    def test_the_result_stays_within_the_documented_span(self, text: int, background: int) -> None:
        value = apca_contrast(Rgb.from_int(text), Rgb.from_int(background))
        assert -110.0 <= value <= 110.0


class TestColourSpaces:
    def test_lab_endpoints(self) -> None:
        lightness, a, b = to_lab(WHITE)
        assert lightness == pytest.approx(100.0, abs=0.01)
        assert a == pytest.approx(0.0, abs=0.01)
        assert b == pytest.approx(0.0, abs=0.01)
        assert to_lab(BLACK)[0] == pytest.approx(0.0, abs=0.01)

    def test_delta_e_is_zero_for_identical_colours(self) -> None:
        assert delta_e(WHITE, WHITE) == pytest.approx(0.0)

    def test_delta_e_grows_with_separation(self) -> None:
        near = delta_e(Rgb.from_int(0x808080), Rgb.from_int(0x858585))
        far = delta_e(BLACK, WHITE)
        assert near < far

    def test_hex_round_trip(self) -> None:
        assert Rgb.from_int(0x1A2B3C).to_hex() == "#1A2B3C"

    @given(st.integers(min_value=0, max_value=0xFFFFFF))
    def test_packed_integers_decode_to_their_bytes(self, packed: int) -> None:
        colour = Rgb.from_int(packed)
        assert colour.to_bytes() == ((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)


class TestVectorisedPathMatchesScalar:
    """The fast path must agree with the readable reference implementation.

    Converting pixels one at a time made the analysis take twenty seconds for
    five pages. The vectorised version replaced it, so the two are held
    together here rather than left to drift.
    """

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=255),
                st.integers(min_value=0, max_value=255),
                st.integers(min_value=0, max_value=255),
            ),
            min_size=1,
            max_size=40,
        )
    )
    @settings(max_examples=60, deadline=None)
    def test_lab_conversion_agrees(self, pixels: list[tuple[int, int, int]]) -> None:
        import numpy as np

        produced = _srgb_array_to_lab(np.array(pixels, dtype=np.uint8))
        for row, pixel in zip(produced, pixels, strict=True):
            expected = to_lab(Rgb.from_bytes(*pixel))
            for got, want in zip(row, expected, strict=True):
                assert got == pytest.approx(want, abs=1e-9)

    def test_background_estimation_agrees(self) -> None:
        import numpy as np

        pixels = [(255, 255, 255)] * 60 + [(0, 0, 0)] * 20
        scalar, scalar_note = estimate_background(pixels, BLACK)
        vector, vector_note = _estimate_background_vectorised(
            np.array(pixels, dtype=np.uint8), np.array(to_lab(BLACK))
        )
        assert scalar_note == vector_note
        assert scalar is not None
        assert vector == scalar.to_bytes()


class TestBackgroundEstimation:
    def test_the_dominant_far_colour_is_chosen(self) -> None:
        pixels = [(255, 255, 255)] * 80 + [(0, 0, 0)] * 20
        background, note = estimate_background(pixels, BLACK)
        assert note == ""
        assert background is not None
        assert background.to_hex() == "#FFFFFF"

    def test_a_uniform_region_reports_invisible_text(self) -> None:
        """Text drawn in the colour of its own background is present but unreadable."""
        background, note = estimate_background([(255, 255, 255)] * 100, WHITE)
        assert background is None
        assert note == "the region is a single colour"

    def test_too_few_pixels_is_reported_rather_than_guessed(self) -> None:
        background, note = estimate_background([(255, 255, 255)] * 3, BLACK)
        assert background is None
        assert "too few pixels" in note

    def test_a_dark_panel_behind_light_text_is_found(self) -> None:
        pixels = [(25, 25, 30)] * 70 + [(255, 255, 255)] * 30
        background, _note = estimate_background(pixels, WHITE)
        assert background is not None
        assert background.to_bytes() == (25, 25, 30)


class TestLargeTextThresholds:
    def _run(self, size: float, bold: bool = False):
        from remediator.contrast.analysis import TextRun

        return TextRun(
            page_index=0,
            text="x",
            bbox=(0, 0, 10, 10),
            color=BLACK,
            size=size,
            bold=bold,
            font="Test",
        )

    @pytest.mark.parametrize(
        ("size", "bold", "large"),
        [
            (12, False, False),
            (17.9, False, False),
            (18, False, True),
            (13, True, False),
            (14, True, True),
        ],
    )
    def test_wcag_large_text_definition(self, size: float, bold: bool, large: bool) -> None:
        """WCAG 2.1: 18 point, or 14 point when bold."""
        assert self._run(size, bold).is_large is large


@pytest.mark.slow
class TestOnRealDocuments:
    @pytest.fixture(scope="module")
    def graded_pdf(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        """A page carrying text at known contrast ratios."""
        reportlab = pytest.importorskip("reportlab")
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        _ = reportlab
        target = tmp_path_factory.mktemp("contrast") / "graded.pdf"
        pdf = canvas.Canvas(str(target), pagesize=letter)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.rect(0, 0, 612, 792, fill=1, stroke=0)

        cases = [
            ("Black on white", (0, 0, 0), 12),
            ("Grey 767676 at the AA boundary", (0x76 / 255,) * 3, 12),
            ("Grey 949494 below AA at body size", (0x94 / 255,) * 3, 12),
            ("Grey 949494 at twenty point", (0x94 / 255,) * 3, 20),
            ("Very light CCCCCC", (0xCC / 255,) * 3, 12),
        ]
        y = 700
        for text, colour, size in cases:
            pdf.setFillColorRGB(*colour)
            pdf.setFont("Helvetica", size)
            pdf.drawString(60, y, text)
            y -= 48

        pdf.setFillColorRGB(0.1, 0.1, 0.12)
        pdf.rect(50, y - 30, 500, 60, fill=1, stroke=0)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setFont("Helvetica", 12)
        pdf.drawString(60, y - 5, "White text on a dark panel")
        pdf.showPage()
        pdf.save()
        return target

    def _find(self, findings, fragment: str):
        return next(f for f in findings if fragment in f.run.text)

    def test_measured_ratios_match_the_intended_values(self, graded_pdf: Path) -> None:
        findings = analyse_document(graded_pdf)
        assert self._find(findings, "Black on white").ratio == pytest.approx(21.0, abs=0.05)
        assert self._find(findings, "767676").ratio == pytest.approx(4.54, abs=0.05)
        assert self._find(findings, "below AA").ratio == pytest.approx(3.03, abs=0.05)

    def test_the_large_text_threshold_changes_the_verdict(self, graded_pdf: Path) -> None:
        """Identical colour, different size, opposite outcome."""
        findings = analyse_document(graded_pdf)
        small = self._find(findings, "below AA at body size")
        large = self._find(findings, "at twenty point")
        assert small.ratio == pytest.approx(large.ratio, abs=0.05)
        assert small.verdict is Verdict.FAIL_AA
        assert large.verdict is Verdict.PASS_AA

    def test_a_dark_panel_is_detected_as_the_background(self, graded_pdf: Path) -> None:
        """The background is whatever was painted, not the page colour."""
        finding = self._find(analyse_document(graded_pdf), "dark panel")
        assert finding.background is not None
        red, green, blue = finding.background.to_bytes()
        assert max(red, green, blue) < 60, (
            f"expected a dark ground, got {finding.background.to_hex()}"
        )
        assert finding.apca is not None and finding.apca < 0, "reverse polarity"

    def test_failures_are_identified(self, graded_pdf: Path) -> None:
        counts = summarise(analyse_document(graded_pdf))
        assert counts["fail-aa"] == 2
        assert counts["invisible"] == 0

    def test_repeated_analysis_is_served_from_cache(self, graded_pdf: Path) -> None:
        import time

        clear_analysis_cache()
        started = time.perf_counter()
        analyse_document(graded_pdf)
        first = time.perf_counter() - started

        started = time.perf_counter()
        analyse_document(graded_pdf)
        second = time.perf_counter() - started
        assert second < first / 2, "the three contrast rules must share one analysis"


@pytest.mark.slow
class TestAuditIntegration:
    def test_contrast_rules_are_absent_from_a_default_audit(self, sample_pdf: Path) -> None:
        """Rendering every page is far more costly than the rest of the audit."""
        from remediator.audit import audit_document

        report = audit_document(sample_pdf)
        assert not [f for f in report.findings if f.checkpoint == "04"]

    def test_contrast_rules_run_when_requested(self, sample_pdf: Path) -> None:
        from remediator.audit import audit_document

        report = audit_document(sample_pdf, include=["04"])
        assert report.rules_run == 3
        assert not report.rules_errored

    def test_low_contrast_text_is_reported_as_a_finding(self, tmp_path: Path) -> None:
        from remediator.audit import audit_document

        pytest.importorskip("reportlab")
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        target = tmp_path / "faint.pdf"
        pdf = canvas.Canvas(str(target), pagesize=letter)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.rect(0, 0, 612, 792, fill=1, stroke=0)
        pdf.setFillColorRGB(0.85, 0.85, 0.85)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(72, 700, "This sentence is far too faint to read comfortably.")
        pdf.showPage()
        pdf.save()

        report = audit_document(target, include=["04"])
        assert "04-001" in {f.condition for f in report.errors}
        finding = next(f for f in report.errors if f.condition == "04-001")
        assert finding.context["ratio"] < 4.5
        assert finding.location.page == 0

    def test_invisible_text_is_reported_separately(self, tmp_path: Path) -> None:
        """White on white is a different problem from merely faint text."""
        from remediator.audit import audit_document

        pytest.importorskip("reportlab")
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        target = tmp_path / "hidden.pdf"
        pdf = canvas.Canvas(str(target), pagesize=letter)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.rect(0, 0, 612, 792, fill=1, stroke=0)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(72, 700, "This text is the same colour as the page.")
        pdf.showPage()
        pdf.save()

        report = audit_document(target, include=["04"])
        assert "04-002" in {f.condition for f in report.errors}


def test_the_module_docstring_claim_holds() -> None:
    """The engine reports on a checkpoint the protocol calls human-judged."""
    from remediator.audit import Determination, rule_catalogue

    contrast_rules = [m for m in rule_catalogue() if m.checkpoint == "04"]
    assert contrast_rules
    assert all(m.determination is Determination.HUMAN for m in contrast_rules)
    assert {m.condition for m in contrast_rules} == {"04-001", "04-002", "04-003"}
