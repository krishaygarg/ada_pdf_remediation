"""Tests for the reading order harness.

The harness is scaffolding for the research in
``docs/planning/layout_reading_order_proposal.md``. These tests cover the
scaffolding: the registry, the dataset format, the validation that stops a
strategy corrupting a page, and the reporting.

They deliberately do not test any ordering algorithm, because none is
implemented here. Several assert the opposite: that the harness reports
honestly while the research functions are still stubs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from remediator.roeval import (
    BenchmarkPage,
    DatasetError,
    PageElement,
    ReadingOrderStrategy,
    available,
    get,
    load_dataset,
    register,
    run_benchmark,
    run_strategy,
    to_json,
    to_markdown,
    validate_ordering,
)
from remediator.roeval.runner import metrics_are_implemented
from remediator.roeval.strategy import as_strategy

DATASET = Path(__file__).resolve().parent.parent / "datasets" / "example.jsonl"


def element(identifier: int, x0: float = 0.0, top: float = 0.0) -> PageElement:
    return PageElement(
        id=identifier, type="P", bbox=(x0, top, x0 + 100, top + 20), text=f"e{identifier}"
    )


@pytest.fixture
def pages() -> list[BenchmarkPage]:
    return load_dataset(DATASET)


class TestRegistry:
    def test_the_baseline_is_registered(self) -> None:
        """Without a baseline in the table there is nothing to beat, and a
        small gain over nothing looks impressive."""
        assert "stream-order" in available()

    def test_the_research_strategies_are_registered(self) -> None:
        assert {"xy-cut", "llm-perplexity", "vlm-align"} <= set(available())

    def test_every_strategy_describes_itself(self) -> None:
        for name, strategy in available().items():
            assert strategy.description.strip(), f"{name} has no description"

    def test_strategies_satisfy_the_protocol(self) -> None:
        for strategy in available().values():
            assert isinstance(strategy, ReadingOrderStrategy)

    def test_an_unknown_name_lists_what_is_available(self) -> None:
        with pytest.raises(LookupError, match="stream-order"):
            get("no-such-strategy")

    def test_a_strategy_without_a_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="non-empty name"):
            register(as_strategy("", "nameless", lambda elements, image=None: list(elements)))

    def test_a_duplicate_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="already registered"):
            register(as_strategy("stream-order", "clash", lambda e, i=None: list(e)))

    def test_a_strategy_can_be_registered_and_selected(self) -> None:
        register(
            as_strategy(
                "test-reverse",
                "Reverses the elements, for testing only.",
                lambda elements, image=None: list(reversed(elements)),
            ),
            replace=True,
        )
        produced = get("test-reverse").sort([element(0), element(1)])
        assert [item.id for item in produced] == [1, 0]


class TestBaseline:
    def test_the_baseline_preserves_the_stream_order(self) -> None:
        elements = [element(index) for index in range(5)]
        produced = get("stream-order").sort(elements)
        assert [item.id for item in produced] == [0, 1, 2, 3, 4]


class TestValidation:
    def test_a_faithful_reordering_is_accepted(self) -> None:
        elements = [element(0), element(1), element(2)]
        validate_ordering(elements, list(reversed(elements)))

    def test_dropping_an_element_is_refused(self) -> None:
        """A strategy that loses content changes the document rather than
        describing it."""
        elements = [element(0), element(1)]
        with pytest.raises(ValueError, match="returned 1 elements"):
            validate_ordering(elements, elements[:1])

    def test_duplicating_an_element_is_refused(self) -> None:
        elements = [element(0), element(1)]
        with pytest.raises(ValueError, match="changed the element set"):
            validate_ordering(elements, [elements[0], elements[0]])

    def test_substituting_an_element_is_refused(self) -> None:
        elements = [element(0), element(1)]
        with pytest.raises(ValueError, match="changed the element set"):
            validate_ordering(elements, [elements[0], element(99)])


class TestDataset:
    def test_the_bundled_example_loads(self, pages: list[BenchmarkPage]) -> None:
        assert len(pages) == 2
        assert all(page.elements for page in pages)

    def test_the_reference_order_is_recovered(self, pages: list[BenchmarkPage]) -> None:
        """The first example is a two column page whose stream order interleaves
        the columns, which is the case the research exists to fix."""
        two_column = next(page for page in pages if page.id == "two-column-basic")
        assert [item.id for item in two_column.reference_elements] == [0, 1, 3, 2, 4]

    def test_a_page_without_a_reference_order_is_refused(self, tmp_path: Path) -> None:
        """A page that cannot be scored would silently inflate every result."""
        path = tmp_path / "bad.jsonl"
        path.write_text(
            json.dumps({"id": "x", "elements": [{"id": 0, "bbox": [0, 0, 1, 1]}]}) + "\n"
        )
        with pytest.raises(DatasetError, match="reading_order_index"):
            load_dataset(path)

    def test_a_non_permutation_reference_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "x",
                    "elements": [
                        {"id": 0, "bbox": [0, 0, 1, 1], "reading_order_index": 0},
                        {"id": 1, "bbox": [0, 0, 1, 1], "reading_order_index": 5},
                    ],
                }
            )
            + "\n"
        )
        with pytest.raises(DatasetError, match="permutation"):
            load_dataset(path)

    def test_duplicate_element_identifiers_are_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "x",
                    "elements": [
                        {"id": 0, "bbox": [0, 0, 1, 1], "reading_order_index": 0},
                        {"id": 0, "bbox": [0, 0, 1, 1], "reading_order_index": 1},
                    ],
                }
            )
            + "\n"
        )
        with pytest.raises(DatasetError, match="not unique"):
            load_dataset(path)

    def test_invalid_json_names_the_line(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"id": "ok", "elements": []}\nnot json\n')
        with pytest.raises(DatasetError, match=r"line 1|line 2"):
            load_dataset(path)

    def test_a_missing_file_is_reported_clearly(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetError, match="no dataset at"):
            load_dataset(tmp_path / "absent.jsonl")

    def test_a_dataset_round_trips(self, pages: list[BenchmarkPage], tmp_path: Path) -> None:
        from remediator.roeval import write_dataset

        path = tmp_path / "out.jsonl"
        write_dataset(path, pages)
        reloaded = load_dataset(path)
        assert [page.id for page in reloaded] == [page.id for page in pages]
        assert [page.reference for page in reloaded] == [page.reference for page in pages]


class TestRunner:
    def test_every_strategy_runs_without_error(self, pages: list[BenchmarkPage]) -> None:
        for result in run_benchmark(sorted(available()), pages):
            assert not result.failures, [page.error for page in result.failures]

    def test_the_baseline_does_not_match_the_reference(self, pages: list[BenchmarkPage]) -> None:
        """If the stream order were already right there would be no research
        problem. The example dataset is built so it is not."""
        assert run_strategy("stream-order", pages).exact_matches == 0

    def test_a_strategy_that_corrupts_a_page_is_recorded_not_swallowed(
        self, pages: list[BenchmarkPage]
    ) -> None:
        register(
            as_strategy("test-drops", "Drops an element.", lambda e, i=None: list(e)[:-1]),
            replace=True,
        )
        result = run_strategy("test-drops", pages)
        assert result.failures
        assert "elements" in result.failures[0].error

    def test_a_strategy_that_raises_is_recorded(self, pages: list[BenchmarkPage]) -> None:
        def explode(elements, image=None):
            raise RuntimeError("deliberate")

        register(as_strategy("test-raises", "Raises.", explode), replace=True)
        result = run_strategy("test-raises", pages)
        assert all(page.error and "deliberate" in page.error for page in result.pages)

    def test_a_perfect_strategy_is_recognised(self, pages: list[BenchmarkPage]) -> None:
        """Confirms the exact-order column can reach the top, so a zero means
        the strategy did not order the page rather than that nothing can."""
        by_page = {page.id: [item.id for item in page.reference_elements] for page in pages}

        def oracle(elements, image=None):
            order = by_page[
                next(
                    page.id
                    for page in pages
                    if {item.id for item in page.elements} == {item.id for item in elements}
                    and len(page.elements) == len(elements)
                )
            ]
            position = {identifier: index for index, identifier in enumerate(order)}
            return sorted(elements, key=lambda item: position[item.id])

        register(as_strategy("test-oracle", "Knows the answer.", oracle), replace=True)
        assert run_strategy("test-oracle", pages).exact_matches == len(pages)

    def test_time_and_memory_are_measured(self, pages: list[BenchmarkPage]) -> None:
        """The specification sets a compute budget alongside the accuracy
        target, so a strategy that wins while needing gigabytes has not met it."""
        result = run_strategy("stream-order", pages)
        assert result.total_seconds >= 0
        assert result.peak_bytes > 0


class TestReportingIsHonest:
    def test_the_metrics_are_not_implemented_yet(self, pages: list[BenchmarkPage]) -> None:
        """Phase 2 of the research specification. When this test starts failing,
        somebody has implemented calculate_evaluation_metrics and the
        leaderboard becomes meaningful."""
        results = run_benchmark(["stream-order", "xy-cut"], pages)
        assert not metrics_are_implemented(results)

    def test_the_leaderboard_says_so_rather_than_showing_bare_zeros(
        self, pages: list[BenchmarkPage]
    ) -> None:
        """A table of zeros presented without comment reads as a result."""
        rendered = to_markdown(run_benchmark(["stream-order", "xy-cut"], pages), len(pages))
        assert "calculate_evaluation_metrics" in rendered
        assert "Phase 2" in rendered

    def test_the_leaderboard_lists_every_strategy(self, pages: list[BenchmarkPage]) -> None:
        names = sorted(available())
        rendered = to_markdown(run_benchmark(names, pages), len(pages))
        for name in names:
            assert f"`{name}`" in rendered

    def test_the_json_report_is_machine_readable(self, pages: list[BenchmarkPage]) -> None:
        payload = json.loads(to_json(run_benchmark(["stream-order"], pages), len(pages)))
        assert payload["pages"] == len(pages)
        assert payload["metricsImplemented"] is False
        assert payload["strategies"][0]["name"] == "stream-order"

    def test_errors_appear_in_the_leaderboard(self, pages: list[BenchmarkPage]) -> None:
        register(as_strategy("test-broken", "Broken.", lambda e, i=None: list(e)[:1]), replace=True)
        rendered = to_markdown(run_benchmark(["test-broken"], pages), len(pages))
        assert "errored" in rendered


class TestResearchBoundary:
    """The harness must not have implemented the research it supports."""

    def test_the_research_functions_are_still_stubs(self) -> None:
        from remediator import reading_order

        blocks = [{"id": 1, "text": "b"}, {"id": 0, "text": "a"}]
        assert reading_order.heuristic_xy_cut(blocks) == blocks
        assert reading_order.unsupervised_llm_sort(blocks) == blocks
        assert reading_order.extract_text_blocks("x.pdf") == []
        assert reading_order.calculate_evaluation_metrics(blocks, blocks) == {
            "sequence_correlation": 0.0,
            "text_overlap_similarity": 0.0,
        }

    def test_the_harness_does_not_extract_elements_from_documents(self) -> None:
        """Phase 1 belongs to remediator.reading_order.extract_text_blocks.

        The harness consumes prepared data so the two do not duplicate work.
        """
        import remediator.roeval.dataset as dataset

        source = Path(dataset.__file__).read_text(encoding="utf-8")
        assert "pikepdf" not in source
        assert "pdfplumber" not in source


class TestPipelineIntegration:
    def test_the_default_leaves_the_order_alone(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        """The call site is wired but inert, so output is unchanged until an
        algorithm exists."""
        import pikepdf

        from remediator.pipeline import remediate_single_pdf

        source = make_text_pdf(pages=1)  # type: ignore[operator]
        default = tmp_path / "default.pdf"
        explicit = tmp_path / "explicit.pdf"
        remediate_single_pdf(str(source), str(default))
        remediate_single_pdf(str(source), str(explicit), reading_order_strategy="xy-cut")

        def tags(path: Path) -> list[str]:
            with pikepdf.open(path) as pdf:
                return [str(kid.get("/S")) for kid in pdf.Root.StructTreeRoot.K.K]

        assert tags(default) == tags(explicit)

    def test_a_strategy_can_reorder_the_structure_tree(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        """Proves the call site works, so an implementation switches on with a
        flag rather than needing the pipeline changed."""
        import pikepdf

        from remediator.pipeline import remediate_single_pdf

        register(
            as_strategy(
                "test-bottom-up",
                "Orders elements from the bottom of the page upward, which is "
                "the reverse of normal reading order and therefore visible.",
                # PDF places the origin at the bottom left, so ascending y walks
                # up the page and reverses the order these lines were written in.
                lambda elements, image=None: sorted(elements, key=lambda e: e.bbox[1]),
            ),
            replace=True,
        )

        source = make_text_pdf(pages=1, lines_per_page=["First", "Second", "Third", "Fourth"])  # type: ignore[operator]
        normal = tmp_path / "normal.pdf"
        reordered = tmp_path / "reordered.pdf"
        remediate_single_pdf(str(source), str(normal))
        remediate_single_pdf(str(source), str(reordered), reading_order_strategy="test-bottom-up")

        def tree_order(path: Path) -> list[int]:
            """The logical sequence a screen reader follows."""
            with pikepdf.open(path) as pdf:
                return [int(kid["/K"]) for kid in pdf.Root.StructTreeRoot.K.K]

        def parent_tree_order(path: Path) -> list[int]:
            """Indexed by marked-content identifier, so it must not change."""
            with pikepdf.open(path) as pdf:
                return [int(entry["/K"]) for entry in pdf.Root.StructTreeRoot.ParentTree.Nums[1]]

        assert tree_order(normal) != tree_order(reordered), "the reading order did not change"
        assert sorted(tree_order(reordered)) == sorted(tree_order(normal))
        assert parent_tree_order(reordered) == parent_tree_order(normal), (
            "the parent tree is indexed by marked-content identifier and must not be reordered"
        )

    def test_a_failing_strategy_falls_back_to_the_stream_order(
        self, make_text_pdf: object, tmp_path: Path
    ) -> None:
        """A broken experiment must not corrupt a document."""
        import pikepdf

        from remediator.pipeline import remediate_single_pdf

        def explode(elements, image=None):
            raise RuntimeError("deliberate")

        register(as_strategy("test-pipeline-raises", "Raises.", explode), replace=True)
        source = make_text_pdf(pages=1)  # type: ignore[operator]
        target = tmp_path / "out.pdf"
        remediate_single_pdf(
            str(source), str(target), reading_order_strategy="test-pipeline-raises"
        )
        with pikepdf.open(target) as pdf:
            assert len(pdf.Root.StructTreeRoot.K.K) > 0
