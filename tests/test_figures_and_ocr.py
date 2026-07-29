"""Tests for figure detection, alternate text providers and the OCR layer."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pikepdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from remediator.alttext import (
    OTHER_MARKER,
    TARGET_MARKER,
    AltTextProvider,
    AltTextResult,
    FigureContext,
    NeedsReviewProvider,
    PageSpan,
    available_providers,
    get_provider,
    register_provider,
)
from remediator.figures import (
    DetectedFigure,
    build_figure_element,
    build_page_spans,
    describe_figures,
    detect_image_figures,
    detect_vector_figures,
)
from remediator.geometry.boxes import Box, cluster_boxes, significant_regions
from remediator.ocr_engine import OcrLine, OcrWord, group_words, horizontal_scale
from remediator.pipeline import remediate_single_pdf
from remediator.utils import merge_bboxes
from tests.pdf_factory import build_image_only_pdf


class TestBox:
    def test_geometry_accessors(self) -> None:
        box = Box(10, 20, 40, 60)
        assert box.width == 30
        assert box.height == 40
        assert box.area == 1200

    def test_union_covers_both(self) -> None:
        assert Box(0, 0, 10, 10).union(Box(5, 5, 20, 20)) == Box(0, 0, 20, 20)

    def test_containment(self) -> None:
        assert Box(0, 0, 100, 100).contains(Box(10, 10, 20, 20))
        assert not Box(10, 10, 20, 20).contains(Box(0, 0, 100, 100))

    def test_intersection_respects_padding(self) -> None:
        assert not Box(0, 0, 10, 10).intersects(Box(15, 0, 25, 10))
        assert Box(0, 0, 10, 10).intersects(Box(15, 0, 25, 10), padding=6)


class TestClustering:
    def test_empty_input(self) -> None:
        assert cluster_boxes([]) == []

    def test_a_single_box_is_returned_unchanged(self) -> None:
        assert cluster_boxes([Box(1, 2, 3, 4)]) == [Box(1, 2, 3, 4)]

    def test_touching_boxes_merge(self) -> None:
        assert cluster_boxes([Box(0, 0, 10, 10), Box(5, 5, 20, 20)]) == [Box(0, 0, 20, 20)]

    def test_distant_boxes_stay_apart(self) -> None:
        result = cluster_boxes([Box(0, 0, 10, 10), Box(500, 500, 510, 510)])
        assert len(result) == 2

    def test_grouping_is_transitive(self) -> None:
        chain = [Box(0, 0, 10, 10), Box(9, 0, 19, 10), Box(18, 0, 28, 10)]
        assert cluster_boxes(chain) == [Box(0, 0, 28, 10)]

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=-300, max_value=300),
                st.integers(min_value=-300, max_value=300),
                st.integers(min_value=0, max_value=80),
                st.integers(min_value=0, max_value=80),
            ),
            min_size=0,
            max_size=40,
        )
    )
    @settings(max_examples=120, deadline=None)
    def test_the_sweep_line_agrees_with_the_pairwise_implementation(
        self, raw: list[tuple[int, int, int, int]]
    ) -> None:
        """The faster grouping must produce exactly the same regions.

        The pairwise version in remediator.utils is the reference. This is the
        property that lets the O(n log n) version replace it without changing
        any output.
        """
        boxes = [[x, y, x + w, y + h] for x, y, w, h in raw]
        reference = sorted(tuple(box) for box in merge_bboxes(boxes))
        produced = sorted(tuple(box) for box in cluster_boxes([Box(*b) for b in boxes]))
        assert produced == reference

    def test_grouping_many_boxes_stays_fast(self) -> None:
        """A page of detailed vector artwork must not take quadratic time.

        Rectangles are spaced well beyond the padding so none of them merge,
        which is the case that forces the pairwise implementation to perform
        every one of its comparisons.
        """
        import time

        boxes = [Box(index * 10.0, 0.0, index * 10.0 + 1.0, 1.0) for index in range(4000)]
        started = time.perf_counter()
        result = cluster_boxes(boxes)
        elapsed = time.perf_counter() - started
        assert len(result) == 4000, "well separated rectangles must not be grouped"
        assert elapsed < 5.0, f"grouping 4000 disjoint rectangles took {elapsed:.2f}s"


class TestSignificantRegions:
    def test_tiny_regions_are_discarded(self) -> None:
        """A rule or an underline is not a figure."""
        regions = significant_regions([Box(10, 10, 200, 11)], page_width=612, page_height=792)
        assert regions == []

    def test_full_page_regions_are_discarded(self) -> None:
        """A page border is not a figure either, and tagging it hides the page."""
        regions = significant_regions([Box(0, 0, 612, 792)], page_width=612, page_height=792)
        assert regions == []

    def test_a_plausible_chart_is_kept(self) -> None:
        regions = significant_regions([Box(100, 100, 400, 400)], page_width=612, page_height=792)
        assert len(regions) == 1

    def test_regions_come_back_in_reading_order(self) -> None:
        regions = significant_regions(
            [Box(300, 400, 500, 600), Box(100, 100, 300, 300)],
            page_width=612,
            page_height=792,
        )
        assert [region.top for region in regions] == sorted(region.top for region in regions)


class TestFigureDetection:
    def test_small_images_are_not_figures(self) -> None:
        placements = [("/Im1", Box(0, 0, 4, 4))]
        assert detect_image_figures(placements, page_width=612, page_height=792) == []

    def test_a_substantial_image_is_a_figure(self) -> None:
        placements = [("/Im1", Box(100, 100, 400, 400))]
        figures = detect_image_figures(placements, page_width=612, page_height=792)
        assert len(figures) == 1
        assert figures[0].kind == "image"
        assert figures[0].xobject_name == "/Im1"

    def test_vector_regions_under_an_image_are_not_reported_twice(self) -> None:
        image = Box(50, 50, 500, 500)
        figures = detect_vector_figures(
            [Box(100, 100, 300, 300)],
            page_width=612,
            page_height=792,
            exclude=[image],
        )
        assert figures == []

    def test_the_bounding_box_is_nested_in_a_layout_attribute(self) -> None:
        """ISO 32000-1 14.8.5.4.3 puts /BBox inside /A with owner /Layout.

        Placing it directly on the structure element is a common mistake and
        leaves it where no consumer looks.
        """
        pdf = pikepdf.new()
        parent = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name("/StructElem")))
        page = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name("/Page")))
        element = build_figure_element(
            pdf,
            DetectedFigure(bbox=Box(10, 20, 30, 40), kind="image"),
            parent=parent,
            page=page,
            mcid=0,
            alt_text="A bar chart of quarterly revenue",
        )
        attributes = element["/A"]
        assert str(attributes["/O"]) == "/Layout"
        assert [float(v) for v in attributes["/BBox"]] == [10.0, 20.0, 30.0, 40.0]
        assert "/BBox" not in element
        assert str(element["/Alt"]) == "A bar chart of quarterly revenue"

    def test_no_alt_entry_is_written_when_there_is_no_description(self) -> None:
        """An absent /Alt is reported by the audit. An empty one is not."""
        pdf = pikepdf.new()
        element = build_figure_element(
            pdf,
            DetectedFigure(bbox=Box(0, 0, 10, 10), kind="image"),
            parent=pdf.make_indirect(pikepdf.Dictionary()),
            page=pdf.make_indirect(pikepdf.Dictionary()),
            mcid=0,
            alt_text=None,
        )
        assert "/Alt" not in element


class TestAltTextProviders:
    def test_the_default_provider_declines_rather_than_inventing(self) -> None:
        result = NeedsReviewProvider().describe(
            FigureContext(page_index=0, bbox=(0, 0, 100, 100), page_width=612, page_height=792)
        )
        assert result.text is None
        assert result.needs_human_review
        assert not result.usable

    def test_the_decline_records_where_the_figure_is(self) -> None:
        result = NeedsReviewProvider().describe(
            FigureContext(
                page_index=2, bbox=(10, 20, 210, 120), page_width=612, page_height=792, kind="image"
            )
        )
        assert "page 3" in result.notes
        assert "200 by 100" in result.notes

    def test_an_existing_caption_is_reused(self) -> None:
        """A caption is the author's own description, so promoting it reports
        what the document says rather than guessing."""
        result = NeedsReviewProvider().describe(
            FigureContext(
                page_index=0,
                bbox=(0, 0, 100, 100),
                page_width=612,
                page_height=792,
                nearby_text="Some body text\nFigure 2. Projectile trajectory for three angles\nMore text",
            )
        )
        assert result.text == "Figure 2. Projectile trajectory for three angles"
        assert result.needs_human_review, "a caption names a figure; it may not describe it"

    def test_a_bare_caption_label_is_not_treated_as_a_description(self) -> None:
        result = NeedsReviewProvider().describe(
            FigureContext(
                page_index=0,
                bbox=(0, 0, 100, 100),
                page_width=612,
                page_height=792,
                nearby_text="Figure 3.",
            )
        )
        assert result.text is None

    def test_the_default_provider_is_the_reviewing_one(self) -> None:
        assert get_provider().name == "needs-review"

    def test_a_provider_can_be_registered_and_selected(self) -> None:
        class Stub:
            name = "test-stub"

            def describe(self, figure: FigureContext) -> AltTextResult:
                return AltTextResult(text="a stub description", confidence=1.0, provider=self.name)

        register_provider(Stub(), replace=True)
        assert "test-stub" in available_providers()
        assert (
            get_provider("test-stub")
            .describe(FigureContext(page_index=0, bbox=(0, 0, 1, 1), page_width=1, page_height=1))
            .text
            == "a stub description"
        )

    def test_an_unknown_provider_name_is_refused_with_the_known_ones(self) -> None:
        with pytest.raises(LookupError, match="needs-review"):
            get_provider("no-such-provider")


def _figure(top: float, *, kind: str = "image") -> DetectedFigure:
    return DetectedFigure(bbox=Box(x0=100, top=top, x1=300, bottom=top + 80), kind=kind)


class TestPageSpans:
    """Two figures on a page share almost all of their nearby text, so nearby
    text alone cannot say which caption belongs to which."""

    def test_text_and_figures_interleave_by_vertical_position(self) -> None:
        spans = build_page_spans(
            [("Intro paragraph", 10.0), ("Figure 1. A trajectory", 100.0), ("Closing", 300.0)],
            [_figure(50.0)],
        )
        assert [(s.text, s.figure_index) for s in spans] == [
            ("Intro paragraph", None),
            ("", 0),
            ("Figure 1. A trajectory\nClosing", None),
        ]

    def test_consecutive_lines_merge_into_one_span(self) -> None:
        """A provider should see paragraphs, not one span per line."""
        spans = build_page_spans([("one", 1.0), ("two", 2.0), ("three", 3.0)], [])
        assert len(spans) == 1
        assert spans[0].text == "one\ntwo\nthree"

    def test_a_caption_below_its_image_sorts_after_the_figure(self) -> None:
        """The case that matters, and it needs no tie break: a caption sits
        below its image, so its top is the larger number."""
        spans = build_page_spans([("Figure 1. Caption", 140.0)], [_figure(50.0)])
        assert spans[0].is_figure
        assert spans[1].text == "Figure 1. Caption"

    def test_a_line_level_with_the_top_edge_reads_as_introducing_the_figure(self) -> None:
        spans = build_page_spans([("Results", 50.0)], [_figure(50.0)])
        assert spans[0].text == "Results"
        assert spans[1].is_figure

    def test_each_figure_marks_itself_and_distinguishes_the_others(self) -> None:
        figures = [_figure(50.0), _figure(400.0)]
        described = describe_figures(
            figures,
            page_index=0,
            page_width=612,
            page_height=792,
            text_lines=[
                ("Figure 1. The first one", 140.0),
                ("Figure 2. The second one", 490.0),
            ],
            provider=_Capturing(),
        )
        assert len(described) == 2

        first, second = _Capturing.seen[-2], _Capturing.seen[-1]
        assert first.figure_index == 0
        assert second.figure_index == 1

        # The marker moves; the page content does not.
        assert first.marked_page_text().index(TARGET_MARKER) < first.marked_page_text().index(
            OTHER_MARKER
        )
        assert second.marked_page_text().index(OTHER_MARKER) < second.marked_page_text().index(
            TARGET_MARKER
        )
        assert "Figure 1." in first.marked_page_text()
        assert "Figure 2." in first.marked_page_text()

    def test_siblings_exclude_the_figure_itself(self) -> None:
        figures = [_figure(50.0), _figure(400.0), _figure(600.0)]
        describe_figures(
            figures,
            page_index=0,
            page_width=612,
            page_height=792,
            text_lines=[("x", 1.0)],
            provider=_Capturing(),
        )
        for position, context in enumerate(_Capturing.seen[-3:]):
            assert len(context.sibling_bboxes) == 2
            assert context.bbox not in context.sibling_bboxes
            assert not context.is_only_figure_on_page
            assert context.figure_index == position

    def test_a_lone_figure_reports_itself_as_the_only_one(self) -> None:
        describe_figures(
            [_figure(50.0)],
            page_index=0,
            page_width=612,
            page_height=792,
            text_lines=[("x", 1.0)],
            provider=_Capturing(),
        )
        assert _Capturing.seen[-1].is_only_figure_on_page

    def test_a_caller_describing_one_figure_still_learns_of_the_others(self) -> None:
        """The pipeline tags figures as it walks the stream, one at a time. Its
        sibling context has to come from the page rather than from the call."""
        on_page = [_figure(50.0), _figure(400.0)]
        describe_figures(
            [on_page[1]],
            page_index=0,
            page_width=612,
            page_height=792,
            text_lines=[("x", 1.0)],
            page_figures=on_page,
            provider=_Capturing(),
        )
        context = _Capturing.seen[-1]
        assert context.figure_index == 1
        assert context.sibling_bboxes == ((100.0, 50.0, 300.0, 130.0),)

    def test_without_positions_the_marked_text_is_empty_rather_than_misleading(self) -> None:
        """An empty string means "no page context", which a provider must not
        confuse with an empty page."""
        describe_figures(
            [_figure(50.0)],
            page_index=0,
            page_width=612,
            page_height=792,
            page_text="some text with no positions",
            provider=_Capturing(),
        )
        context = _Capturing.seen[-1]
        assert context.page_spans == ()
        assert context.marked_page_text() == ""
        assert context.page_text == ""
        assert context.nearby_text == "some text with no positions"

    def test_page_text_omits_the_figure_markers(self) -> None:
        context = FigureContext(
            page_index=0,
            bbox=(0, 0, 1, 1),
            page_width=1,
            page_height=1,
            figure_index=0,
            page_spans=(PageSpan(text="above"), PageSpan(figure_index=0), PageSpan(text="below")),
        )
        assert context.page_text == "above\nbelow"
        assert context.marked_page_text() == f"above\n{TARGET_MARKER}\nbelow"

    def test_an_unplaceable_figure_marks_nothing_rather_than_the_wrong_thing(self) -> None:
        """The bug this guards against: an unmatched figure reporting index 0
        claims to be the first figure on the page, so it received a different
        figure's caption and described it confidently."""
        describe_figures(
            [_figure(50.0)],
            page_index=0,
            page_width=612,
            page_height=792,
            text_lines=[("Figure 1. Something else", 900.0)],
            page_figures=[_figure(5000.0)],  # nothing overlapping the subject
            provider=_Capturing(),
        )
        context = _Capturing.seen[-1]
        assert context.figure_index is None
        assert not context.has_page_context
        assert context.marked_page_text() == ""

    def test_a_region_is_matched_despite_rounding_between_detectors(self) -> None:
        """The two sources of a figure's geometry come through different
        libraries and disagree in the last decimal place."""
        subject = DetectedFigure(bbox=Box(x0=100.0, top=50.0, x1=300.0, bottom=130.0), kind="image")
        rounded = DetectedFigure(
            bbox=Box(x0=100.002, top=49.998, x1=299.997, bottom=130.004), kind="image"
        )
        describe_figures(
            [subject],
            page_index=0,
            page_width=612,
            page_height=792,
            text_lines=[("x", 1.0)],
            page_figures=[_figure(400.0), rounded],
            provider=_Capturing(),
        )
        assert _Capturing.seen[-1].figure_index == 1


class TestPageContextThroughThePipeline:
    """The unit tests above can pass while the pipeline feeds the interface
    inconsistent coordinates, which is exactly what happened: both figures on a
    page reported themselves as figure zero and received identical context."""

    @staticmethod
    def _two_figure_document(directory: Path) -> Path:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        for name, colour in (("a.png", (200, 40, 40)), ("b.png", (40, 80, 200))):
            Image.new("RGB", (240, 160), colour).save(directory / name)

        source = directory / "two_figures.pdf"
        page = canvas.Canvas(str(source), pagesize=letter)
        page.setFont("Helvetica", 11)
        page.drawString(72, 730, "Introduction to projectile motion")
        page.drawImage(str(directory / "a.png"), 72, 560, width=240, height=150)
        page.drawString(72, 545, "Figure 1. Trajectory for three launch angles")
        page.drawImage(str(directory / "b.png"), 72, 300, width=240, height=150)
        page.drawString(72, 285, "Figure 2. Terminal velocity against mass")
        page.showPage()
        page.save()
        return source

    @pytest.mark.slow
    def test_each_figure_on_a_page_receives_its_own_caption(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from remediator import pipeline
        from remediator.progress import NullReporter

        source = self._two_figure_document(tmp_path)
        seen: list[FigureContext] = []

        class Spy:
            name = "spy"

            def describe(self, figure: FigureContext) -> AltTextResult:
                seen.append(figure)
                return AltTextResult(text=None)

        monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: Spy())
        pipeline.remediate_single_pdf(
            str(source), str(tmp_path / "out.pdf"), progress=NullReporter()
        )

        assert len(seen) == 2, "both images should have been offered for description"
        assert [context.figure_index for context in seen] == [0, 1], (
            "each figure must locate itself, not default to the first"
        )
        assert all(context.has_page_context for context in seen)

        first, second = (context.marked_page_text() for context in seen)
        assert first != second, "identical context defeats the purpose of tracking position"
        # The marker sits immediately before the caption that belongs to it.
        assert TARGET_MARKER + "\nFigure 1." in first
        assert TARGET_MARKER + "\nFigure 2." in second
        assert OTHER_MARKER + "\nFigure 2." in first
        assert OTHER_MARKER + "\nFigure 1." in second


class TestReadingSpaceConversion:
    """The content stream measures up from the bottom of the page; pdfplumber
    measures down from the top. Mixing them silently breaks figure placement."""

    def test_a_box_is_flipped_about_the_page_height(self) -> None:
        from remediator.pipeline import _to_reading_space

        # An image drawn at y=560 with height 150 on a 792pt page.
        converted = _to_reading_space(Box(x0=72, top=560, x1=312, bottom=710), 792.0)
        assert converted == Box(x0=72, top=82.0, x1=312, bottom=232.0)

    def test_conversion_is_its_own_inverse(self) -> None:
        from remediator.pipeline import _to_reading_space

        original = Box(x0=10, top=100, x1=200, bottom=300)
        assert _to_reading_space(_to_reading_space(original, 792.0), 792.0) == original

    def test_conversion_preserves_height_and_horizontal_extent(self) -> None:
        from remediator.pipeline import _to_reading_space

        original = Box(x0=10, top=100, x1=200, bottom=300)
        converted = _to_reading_space(original, 792.0)
        assert converted.height == original.height
        assert (converted.x0, converted.x1) == (original.x0, original.x1)


class _Capturing:
    """Records the contexts it is handed, so the wiring can be asserted on."""

    name = "capturing"
    seen: ClassVar[list[FigureContext]] = []

    def describe(self, figure: FigureContext) -> AltTextResult:
        _Capturing.seen.append(figure)
        return AltTextResult(text=None)

    def test_a_provider_without_a_name_is_refused(self) -> None:
        class Nameless:
            name = ""

            def describe(self, figure: FigureContext) -> AltTextResult:  # pragma: no cover
                return AltTextResult(text=None)

        with pytest.raises(ValueError, match="non-empty name"):
            register_provider(Nameless())

    def test_the_default_provider_satisfies_the_protocol(self) -> None:
        assert isinstance(NeedsReviewProvider(), AltTextProvider)

    def test_describe_figures_reports_which_need_review(self) -> None:
        described = describe_figures(
            [DetectedFigure(bbox=Box(0, 0, 100, 100), kind="image")],
            page_index=0,
            page_width=612,
            page_height=792,
        )
        assert len(described) == 1
        _figure, text, needs_review = described[0]
        assert text is None
        assert needs_review


class TestOcrGrouping:
    def _data(self, rows: list[tuple[int, int, int, str]]) -> dict:
        """Build a Tesseract-shaped result from (block, paragraph, line, text)."""
        keys = [
            "block_num",
            "par_num",
            "line_num",
            "text",
            "conf",
            "left",
            "top",
            "width",
            "height",
        ]
        data: dict[str, list] = {key: [] for key in keys}
        for index, (block, paragraph, line, text) in enumerate(rows):
            data["block_num"].append(block)
            data["par_num"].append(paragraph)
            data["line_num"].append(line)
            data["text"].append(text)
            data["conf"].append(96)
            data["left"].append(index * 50)
            data["top"].append(line * 20)
            data["width"].append(40)
            data["height"].append(12)
        return data

    def test_words_are_grouped_into_paragraphs_not_left_separate(self) -> None:
        """One structure element per word made a screen reader announce every
        word as its own paragraph."""
        data = self._data(
            [
                (1, 1, 1, "The"),
                (1, 1, 1, "quick"),
                (1, 1, 2, "brown"),
                (1, 2, 1, "Second"),
                (2, 1, 1, "Another"),
            ]
        )
        paragraphs = group_words(data)
        assert len(paragraphs) == 3
        assert paragraphs[0].text == "The quick brown"
        assert len(paragraphs[0].lines) == 2

    def test_low_confidence_words_are_dropped(self) -> None:
        data = self._data([(1, 1, 1, "good"), (1, 1, 1, "noise")])
        data["conf"][1] = 5
        assert group_words(data)[0].text == "good"

    def test_blank_entries_are_ignored(self) -> None:
        data = self._data([(1, 1, 1, "word"), (1, 1, 1, "   ")])
        assert group_words(data)[0].text == "word"

    def test_empty_input_yields_no_paragraphs(self) -> None:
        assert group_words({"text": []}) == []

    def test_document_order_is_preserved(self) -> None:
        data = self._data([(2, 1, 1, "second"), (1, 1, 1, "first")])
        assert [p.text for p in group_words(data)] == ["second", "first"]

    def test_line_extent_spans_its_words(self) -> None:
        line = OcrLine(
            words=[
                OcrWord("a", left=10, top=5, width=20, height=12, confidence=90),
                OcrWord("b", left=40, top=5, width=20, height=12, confidence=90),
            ]
        )
        assert line.left == 10
        assert line.right == 60
        assert line.height == 12


class TestHorizontalScale:
    def test_a_wider_target_stretches_the_run(self) -> None:
        """The invisible layer must line up with the image beneath it."""
        assert horizontal_scale("hello", font_size=10, target_width=50) > 100

    def test_a_narrower_target_compresses_the_run(self) -> None:
        assert horizontal_scale("hello", font_size=10, target_width=10) < 100

    @pytest.mark.parametrize(
        ("text", "size", "width"), [("", 10, 50), ("x", 0, 50), ("x", 10, 0), ("x", 10, -5)]
    )
    def test_degenerate_input_leaves_the_scale_alone(
        self, text: str, size: float, width: float
    ) -> None:
        assert horizontal_scale(text, size, width) == 100.0

    def test_the_scale_is_clamped(self) -> None:
        """One mis-recognised box must not stretch a run across the page."""
        assert horizontal_scale("x", font_size=1, target_width=100_000) <= 400.0
        assert horizontal_scale("x" * 500, font_size=100, target_width=1) >= 10.0


class TestPipelineFigureIntegration:
    @pytest.fixture
    def image_pdf(self, tmp_path: Path) -> Path:
        return build_image_only_pdf(tmp_path / "image.pdf")

    def test_an_image_becomes_a_figure_element(self, image_pdf: Path, tmp_path: Path) -> None:
        """Previously every image was wrapped as an artifact, so no /Figure
        element was ever produced despite the documented behaviour."""
        target = tmp_path / "out.pdf"
        remediate_single_pdf(str(image_pdf), str(target))
        with pikepdf.open(target) as pdf:
            tags = [str(kid.get("/S")) for kid in pdf.Root.StructTreeRoot.K.K]
        assert "/Figure" in tags

    def test_the_figure_declares_its_bounding_box(self, image_pdf: Path, tmp_path: Path) -> None:
        target = tmp_path / "out.pdf"
        remediate_single_pdf(str(image_pdf), str(target))
        with pikepdf.open(target) as pdf:
            figure = next(
                kid for kid in pdf.Root.StructTreeRoot.K.K if str(kid.get("/S")) == "/Figure"
            )
            attributes = figure["/A"]
        assert str(attributes["/O"]) == "/Layout"
        assert len(attributes["/BBox"]) == 4

    def test_the_artifact_policy_keeps_undescribed_images_out_of_the_tree(
        self, image_pdf: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "artifact.pdf"
        remediate_single_pdf(str(image_pdf), str(target), undescribed_images="artifact")
        with pikepdf.open(target) as pdf:
            tags = [str(kid.get("/S")) for kid in pdf.Root.StructTreeRoot.K.K]
        assert "/Figure" not in tags

    def test_the_two_policies_reach_opposite_conformance_verdicts(
        self, image_pdf: Path, tmp_path: Path
    ) -> None:
        """The tradeoff is real and is the reason the choice is exposed.

        Tagging the figure surfaces work that a person has to do. Marking it
        decorative conforms while removing the image from the reading order.
        """
        from remediator.audit import audit_document

        tagged = tmp_path / "tagged.pdf"
        hidden = tmp_path / "hidden.pdf"
        remediate_single_pdf(str(image_pdf), str(tagged), undescribed_images="figure")
        remediate_single_pdf(str(image_pdf), str(hidden), undescribed_images="artifact")

        tagged_report = audit_document(tagged)
        hidden_report = audit_document(hidden)
        assert "13-004" in {f.condition for f in tagged_report.errors}
        assert hidden_report.conformant

    def test_an_invalid_policy_is_refused(self, image_pdf: Path, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="figure' or 'artifact"):
            remediate_single_pdf(str(image_pdf), str(tmp_path / "x.pdf"), undescribed_images="skip")

    @pytest.mark.slow
    def test_a_text_document_gains_no_spurious_figures(
        self, sample_pdf: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "physics.pdf"
        remediate_single_pdf(str(sample_pdf), str(target))
        with pikepdf.open(target) as pdf:
            tags = [str(kid.get("/S")) for kid in pdf.Root.StructTreeRoot.K.K]
        assert "/Figure" not in tags
