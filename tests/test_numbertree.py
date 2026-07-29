"""Tests for PDF number tree construction (ISO 32000-1, 7.9.7).

The invariants matter because a consumer navigates the tree by comparing keys
against ``/Limits``. A tree whose limits disagree with its contents is not
merely untidy: lookups silently miss, and the structure elements behind those
keys become unreachable to assistive technology.
"""

from __future__ import annotations

import pikepdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remediator.numbertree import (
    DEFAULT_FAN_OUT,
    DEFAULT_LEAF_SIZE,
    FLAT_THRESHOLD,
    build_number_tree,
    lookup,
    validate_number_tree,
)


@pytest.fixture
def pdf() -> pikepdf.Pdf:
    return pikepdf.new()


def _entries(pdf: pikepdf.Pdf, keys: list[int]) -> list[tuple[int, pikepdf.Object]]:
    """Pair each key with a distinguishable indirect object."""
    return [
        (key, pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), K=key)))
        for key in keys
    ]


class TestShape:
    def test_an_empty_tree_is_a_root_with_an_empty_nums_array(self, pdf: pikepdf.Pdf) -> None:
        root = build_number_tree(pdf, [])
        assert "/Nums" in root
        assert len(root["/Nums"]) == 0
        assert "/Limits" not in root

    def test_a_small_tree_stays_flat(self, pdf: pikepdf.Pdf) -> None:
        """A linear scan of a few dozen entries beats the extra indirection."""
        root = build_number_tree(pdf, _entries(pdf, list(range(10))))
        assert "/Nums" in root
        assert "/Kids" not in root

    def test_a_tree_at_the_threshold_is_still_flat(self, pdf: pikepdf.Pdf) -> None:
        root = build_number_tree(pdf, _entries(pdf, list(range(FLAT_THRESHOLD))))
        assert "/Nums" in root

    def test_a_tree_above_the_threshold_branches(self, pdf: pikepdf.Pdf) -> None:
        root = build_number_tree(pdf, _entries(pdf, list(range(FLAT_THRESHOLD + 1))))
        assert "/Kids" in root
        assert "/Nums" not in root

    def test_the_root_carries_no_limits(self, pdf: pikepdf.Pdf) -> None:
        """Only descendants declare limits; the root is entered unconditionally."""
        root = build_number_tree(pdf, _entries(pdf, list(range(500))))
        assert "/Limits" not in root

    def test_depth_grows_logarithmically(self, pdf: pikepdf.Pdf) -> None:
        """A large document must not degrade into one enormous array."""
        root = build_number_tree(pdf, _entries(pdf, list(range(20_000))))

        def depth(node: pikepdf.Object) -> int:
            if "/Nums" in node:
                return 1
            return 1 + max(depth(kid) for kid in node["/Kids"])

        # 20000 entries at 64 per leaf is 313 leaves, which fits in two levels
        # of 64-way branching above them.
        assert depth(root) <= 4

    def test_leaves_hold_at_most_the_configured_number_of_entries(self, pdf: pikepdf.Pdf) -> None:
        root = build_number_tree(pdf, _entries(pdf, list(range(1000))))

        def check(node: pikepdf.Object) -> None:
            if "/Nums" in node:
                assert len(node["/Nums"]) // 2 <= DEFAULT_LEAF_SIZE
                return
            assert len(node["/Kids"]) <= DEFAULT_FAN_OUT
            for kid in node["/Kids"]:
                check(kid)

        check(root)


class TestInvariants:
    @pytest.mark.parametrize("count", [0, 1, 2, 63, 64, 65, 128, 129, 500, 4097])
    def test_invariants_hold_across_sizes(self, pdf: pikepdf.Pdf, count: int) -> None:
        keys = list(range(count))
        root = build_number_tree(pdf, _entries(pdf, keys))
        validate_number_tree(root, keys)

    def test_sparse_and_unordered_keys_are_handled(self, pdf: pikepdf.Pdf) -> None:
        """Page keys are dense but annotation keys need not be contiguous."""
        keys = [900, 3, 17, 4001, 0, 128, 129, 55]
        root = build_number_tree(pdf, _entries(pdf, keys))
        validate_number_tree(root, keys)

    def test_duplicate_keys_are_rejected(self, pdf: pikepdf.Pdf) -> None:
        with pytest.raises(ValueError, match="unique"):
            build_number_tree(pdf, _entries(pdf, [1, 2, 2, 3]))

    @pytest.mark.parametrize(("leaf", "fan"), [(1, 4), (4, 1), (0, 0)])
    def test_degenerate_shape_parameters_are_rejected(
        self, pdf: pikepdf.Pdf, leaf: int, fan: int
    ) -> None:
        """A fan-out below two would never reduce the level, so it must not build."""
        with pytest.raises(ValueError, match="at least 2"):
            build_number_tree(pdf, _entries(pdf, [1, 2]), leaf_size=leaf, fan_out=fan)

    @given(
        st.lists(st.integers(min_value=0, max_value=50_000), min_size=0, max_size=400, unique=True)
    )
    @settings(max_examples=40, deadline=None)
    def test_invariants_hold_for_arbitrary_key_sets(self, keys: list[int]) -> None:
        pdf = pikepdf.new()
        root = build_number_tree(pdf, _entries(pdf, keys))
        validate_number_tree(root, keys)


class TestLookup:
    @pytest.mark.parametrize("count", [5, 128, 129, 700])
    def test_every_key_resolves_to_its_own_value(self, pdf: pikepdf.Pdf, count: int) -> None:
        keys = list(range(count))
        root = build_number_tree(pdf, _entries(pdf, keys))
        for key in keys:
            found = lookup(root, key)
            assert found is not None, f"key {key} is unreachable"
            assert int(found["/K"]) == key, f"key {key} resolved to entry {int(found['/K'])}"

    def test_absent_keys_resolve_to_nothing(self, pdf: pikepdf.Pdf) -> None:
        root = build_number_tree(pdf, _entries(pdf, [0, 1, 2]))
        assert lookup(root, 99) is None

    def test_lookup_descends_by_limits_in_a_branched_tree(self, pdf: pikepdf.Pdf) -> None:
        """Confirms navigation works without scanning every leaf."""
        keys = list(range(0, 4000, 3))
        root = build_number_tree(pdf, _entries(pdf, keys))
        assert "/Kids" in root
        for key in (keys[0], keys[len(keys) // 2], keys[-1]):
            assert int(lookup(root, key)["/K"]) == key
        assert lookup(root, 1) is None


class TestValidatorRejectsMalformedTrees:
    """The validator is only useful if it actually catches breakage."""

    def test_mismatched_limits_are_detected(self, pdf: pikepdf.Pdf) -> None:
        keys = list(range(300))
        root = build_number_tree(pdf, _entries(pdf, keys))
        root["/Kids"][0]["/Limits"][1] = pikepdf.Integer(99_999)
        with pytest.raises(AssertionError, match="does not match"):
            validate_number_tree(root, keys)

    def test_a_missing_key_is_detected(self, pdf: pikepdf.Pdf) -> None:
        keys = list(range(10))
        root = build_number_tree(pdf, _entries(pdf, keys))
        with pytest.raises(AssertionError, match="key set mismatch"):
            validate_number_tree(root, [*keys, 999])

    def test_unsorted_nums_are_detected(self, pdf: pikepdf.Pdf) -> None:
        root = pdf.make_indirect(
            pikepdf.Dictionary(
                Nums=pikepdf.Array(
                    [pikepdf.Integer(5), pikepdf.Integer(0), pikepdf.Integer(1), pikepdf.Integer(0)]
                )
            )
        )
        with pytest.raises(AssertionError, match="not ascending"):
            validate_number_tree(root, [5, 1])

    def test_a_node_with_both_nums_and_kids_is_detected(self, pdf: pikepdf.Pdf) -> None:
        root = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(), Kids=pikepdf.Array()))
        with pytest.raises(AssertionError, match="exactly one"):
            validate_number_tree(root, [])
