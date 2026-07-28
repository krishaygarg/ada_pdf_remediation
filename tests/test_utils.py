"""Property and unit tests for the spatial primitives in ``remediator.utils``.

These helpers underpin coordinate tracking in the content-stream filter, so a
silent error here misplaces every artifact bounding box in the document. The
algebraic laws are checked with Hypothesis rather than a handful of examples
because the failure mode is numeric, not structural.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from remediator.utils import (
    get_operator_coords,
    merge_bboxes,
    multiply_matrices,
    transform_point,
)

IDENTITY = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

# Values are bounded well inside float precision so that associativity can be
# asserted with a meaningful tolerance instead of an arbitrary one.
_component = st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)
matrices = st.lists(_component, min_size=6, max_size=6)
coordinates = st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False)


def _close(a: float, b: float, *, rel: float = 1e-9, abs_: float = 1e-6) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


class TestMatrixAlgebra:
    """``multiply_matrices`` must implement the PDF 3x3 affine product."""

    @given(matrices)
    def test_identity_is_neutral_on_both_sides(self, m: list[float]) -> None:
        left = multiply_matrices(IDENTITY, m)
        right = multiply_matrices(m, IDENTITY)
        for produced, expected in zip(left, m, strict=True):
            assert _close(produced, expected)
        for produced, expected in zip(right, m, strict=True):
            assert _close(produced, expected)

    @given(matrices, matrices, matrices)
    @settings(max_examples=200)
    def test_multiplication_is_associative(
        self, a: list[float], b: list[float], c: list[float]
    ) -> None:
        left = multiply_matrices(multiply_matrices(a, b), c)
        right = multiply_matrices(a, multiply_matrices(b, c))
        for produced, expected in zip(left, right, strict=True):
            assert _close(produced, expected, rel=1e-6, abs_=1e-3)

    @given(matrices, matrices, coordinates, coordinates)
    @settings(max_examples=200)
    def test_composition_matches_sequential_transformation(
        self, m1: list[float], m2: list[float], x: float, y: float
    ) -> None:
        """Transforming by ``m1 * m2`` equals transforming by m1 then by m2.

        This is the law the content-stream filter relies on when it folds each
        ``cm`` operator into the running transformation matrix.
        """
        composed = transform_point(x, y, multiply_matrices(m1, m2))
        stepwise = transform_point(*transform_point(x, y, m1), m2)
        for produced, expected in zip(composed, stepwise, strict=True):
            assert _close(produced, expected, rel=1e-6, abs_=1e-3)

    @given(coordinates, coordinates)
    def test_identity_transform_is_a_fixed_point(self, x: float, y: float) -> None:
        assert transform_point(x, y, IDENTITY) == (x, y)

    @given(
        st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False),
        st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False),
        coordinates,
        coordinates,
    )
    def test_translation_adds_the_offset(self, tx: float, ty: float, x: float, y: float) -> None:
        moved = transform_point(x, y, [1.0, 0.0, 0.0, 1.0, tx, ty])
        assert _close(moved[0], x + tx, abs_=1e-3)
        assert _close(moved[1], y + ty, abs_=1e-3)

    @given(st.floats(min_value=-math.pi, max_value=math.pi), coordinates, coordinates)
    def test_rotation_preserves_distance_from_the_origin(
        self, theta: float, x: float, y: float
    ) -> None:
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        rotated = transform_point(x, y, [cos_t, sin_t, -sin_t, cos_t, 0.0, 0.0])
        assert _close(math.hypot(*rotated), math.hypot(x, y), rel=1e-6, abs_=1e-6)

    def test_scaling_matrix_multiplies_coordinates(self) -> None:
        assert transform_point(3.0, 4.0, [2.0, 0.0, 0.0, 5.0, 0.0, 0.0]) == (6.0, 20.0)


class TestMergeBboxes:
    """``merge_bboxes`` groups touching rectangles via union-find."""

    def test_empty_input_returns_empty_output(self) -> None:
        assert merge_bboxes([]) == []

    def test_disjoint_boxes_are_preserved(self) -> None:
        boxes = [[0, 0, 10, 10], [100, 100, 110, 110]]
        merged = merge_bboxes(boxes)
        assert len(merged) == 2
        assert sorted(merged) == sorted([[0, 0, 10, 10], [100, 100, 110, 110]])

    def test_overlapping_boxes_collapse_into_their_union(self) -> None:
        merged = merge_bboxes([[0, 0, 10, 10], [5, 5, 20, 20]])
        assert merged == [[0, 0, 20, 20]]

    def test_boxes_within_the_padding_distance_are_joined(self) -> None:
        """The 2 point pad exists so hairline table rules group with their cells."""
        merged = merge_bboxes([[0, 0, 10, 10], [11, 0, 20, 10]])
        assert merged == [[0, 0, 20, 10]]

    def test_grouping_is_transitive_through_a_chain(self) -> None:
        boxes = [[0, 0, 10, 10], [9, 0, 19, 10], [18, 0, 28, 10]]
        assert merge_bboxes(boxes) == [[0, 0, 28, 10]]

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=-500, max_value=500),
                st.integers(min_value=-500, max_value=500),
                st.integers(min_value=0, max_value=100),
                st.integers(min_value=0, max_value=100),
            ),
            min_size=0,
            max_size=25,
        )
    )
    def test_every_input_is_covered_and_the_count_never_grows(
        self, raw: list[tuple[int, int, int, int]]
    ) -> None:
        boxes = [[x, y, x + w, y + h] for x, y, w, h in raw]
        merged = merge_bboxes(boxes)

        assert len(merged) <= len(boxes)
        for x0, top, x1, bottom in merged:
            assert x0 <= x1
            assert top <= bottom
        for box in boxes:
            assert any(
                m[0] <= box[0] and m[1] <= box[1] and m[2] >= box[2] and m[3] >= box[3]
                for m in merged
            ), f"input box {box} is not contained in any merged region"

    def test_a_single_pass_is_not_idempotent(self) -> None:
        """Document a real characteristic of the current grouping rule.

        The 2 point pad is applied when comparing rectangles, but a merged group
        is stored as the tight union of its members. Re-running the merge
        therefore pads regions that already absorbed their neighbours, which can
        join groups that the first pass kept apart. Callers must treat one pass
        as the defined operation rather than assume a fixed point.
        """
        boxes = [[0, 0, 1, 2], [0, 0, 2, 1], [4, 4, 5, 5]]
        once = merge_bboxes(boxes)
        twice = merge_bboxes(once)
        assert sorted(once) == [[0, 0, 2, 2], [4, 4, 5, 5]]
        assert sorted(twice) == [[0, 0, 5, 5]]

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=-200, max_value=200),
                st.integers(min_value=-200, max_value=200),
                st.integers(min_value=1, max_value=60),
                st.integers(min_value=1, max_value=60),
            ),
            min_size=1,
            max_size=15,
        )
    )
    def test_repeated_merging_reaches_a_fixed_point(
        self, raw: list[tuple[int, int, int, int]]
    ) -> None:
        """Iterating the merge terminates, and each pass is non-expanding.

        Every pass either leaves the partition alone or strictly reduces the
        number of regions, so the iteration is bounded by the input size.
        """
        boxes = [[x, y, x + w, y + h] for x, y, w, h in raw]
        current = merge_bboxes(boxes)
        for _ in range(len(boxes) + 1):
            following = merge_bboxes(current)
            assert len(following) <= len(current)
            if sorted(following) == sorted(current):
                break
            current = following
        else:  # pragma: no cover - would indicate a non-terminating merge
            pytest.fail("merge_bboxes did not reach a fixed point")


class TestOperatorCoordinates:
    """Coordinate extraction feeds the artifact/complex-region test."""

    @pytest.mark.parametrize(
        ("operator", "operands", "expected"),
        [
            ("m", [1, 2], [(1.0, 2.0)]),
            ("l", [3, 4], [(3.0, 4.0)]),
            ("re", [10, 20, 5, 7], [(10.0, 20.0), (15.0, 27.0)]),
            ("c", [1, 2, 3, 4, 5, 6], [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]),
            ("v", [1, 2, 3, 4], [(1.0, 2.0), (3.0, 4.0)]),
            ("y", [1, 2, 3, 4], [(1.0, 2.0), (3.0, 4.0)]),
            ("h", [], []),
            ("unknown", [1, 2], []),
        ],
    )
    def test_known_operators_yield_their_control_points(
        self, operator: str, operands: list[float], expected: list[tuple[float, float]]
    ) -> None:
        assert get_operator_coords(operator, operands) == expected

    @pytest.mark.parametrize("operator", ["m", "l", "re", "c", "v", "y"])
    def test_short_operand_lists_are_ignored_rather_than_raising(self, operator: str) -> None:
        """Damaged content streams must not abort the whole remediation run."""
        assert get_operator_coords(operator, []) == []

    @given(
        st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False),
        st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.1, max_value=1e3, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.1, max_value=1e3, allow_nan=False, allow_infinity=False),
    )
    def test_rectangle_corners_bound_the_rectangle(
        self, x: float, y: float, w: float, h: float
    ) -> None:
        assume(w > 0 and h > 0)
        (x0, y0), (x1, y1) = get_operator_coords("re", [x, y, w, h])
        assert x0 < x1
        assert y0 < y1
