"""Construction of PDF number trees (ISO 32000-1, 7.9.7).

A number tree maps integer keys to arbitrary objects. The structure tree's
``/ParentTree`` is one, keyed by the values that pages carry in
``/StructParents`` and that annotations carry in ``/StructParent``.

The specification permits a single root node holding every entry in one
``/Nums`` array, and that is what small documents get here because it is the
cheapest correct answer. Beyond a threshold the entries are distributed across
balanced leaves under intermediate nodes carrying ``/Limits``, which is the
shape the specification describes for large trees and the one that lets a
consumer binary search rather than scan. A thousand-page document otherwise
produces a single array with several thousand entries that every reader must
walk linearly.

The tree this module builds satisfies, at every level:

* keys within a leaf appear in ascending order;
* ``/Limits`` equals ``[first_key, last_key]`` of the subtree beneath the node;
* sibling limit ranges are disjoint and ascending, so a lookup can descend by
  comparison alone;
* every key given to :func:`build_number_tree` appears exactly once.

:func:`validate_number_tree` checks all four and is used by the test suite.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

import pikepdf

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: Entries per leaf node. The specification gives no required value. Adobe's
#: own output clusters in the dozens, and a leaf of this size keeps a leaf
#: comfortably inside one object while bounding depth: 32 leaves of 64 entries
#: already cover 2048 keys at depth two.
DEFAULT_LEAF_SIZE = 64

#: Maximum children per intermediate node, chosen to match the leaf size so the
#: tree stays shallow and roughly square.
DEFAULT_FAN_OUT = 64

#: Below this many entries a flat root is used. A linear scan of a few dozen
#: entries costs less than the extra indirection of a tree.
FLAT_THRESHOLD = 128


def _nums_array(entries: Sequence[tuple[int, pikepdf.Object]]) -> pikepdf.Array:
    """Build a ``/Nums`` array, which interleaves keys and values."""
    array = pikepdf.Array()
    for key, value in entries:
        array.append(pikepdf.Integer(key))
        array.append(value)
    return array


def _limits(first: int, last: int) -> pikepdf.Array:
    return pikepdf.Array([pikepdf.Integer(first), pikepdf.Integer(last)])


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_number_tree(
    pdf: pikepdf.Pdf,
    entries: Iterable[tuple[int, pikepdf.Object]],
    *,
    leaf_size: int = DEFAULT_LEAF_SIZE,
    fan_out: int = DEFAULT_FAN_OUT,
    flat_threshold: int = FLAT_THRESHOLD,
) -> pikepdf.Object:
    """Return an indirect number tree root mapping each key to its value.

    Args:
        pdf: The document the nodes are created in.
        entries: ``(key, value)`` pairs. Keys must be unique; order is
            irrelevant because they are sorted here.
        leaf_size: Entries stored in each leaf once the tree is not flat.
        fan_out: Maximum children per intermediate node.
        flat_threshold: Entry count at or below which a single root node
            holding every entry is produced.

    Raises:
        ValueError: If a key is repeated, or if the shape parameters are less
            than two, which would prevent the tree from ever converging.
    """
    if leaf_size < 2 or fan_out < 2:
        raise ValueError("leaf_size and fan_out must both be at least 2")

    ordered = sorted(entries, key=lambda item: item[0])
    keys = [key for key, _ in ordered]
    if len(set(keys)) != len(keys):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        raise ValueError(f"number tree keys must be unique; repeated: {duplicates}")

    if not ordered:
        return pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array()))

    if len(ordered) <= flat_threshold:
        return pdf.make_indirect(pikepdf.Dictionary(Nums=_nums_array(ordered)))

    # Leaves first, then intermediate levels until a single node remains.
    nodes: list[tuple[int, int, pikepdf.Object]] = []
    for group in _chunk(ordered, leaf_size):
        first, last = group[0][0], group[-1][0]
        leaf = pdf.make_indirect(
            pikepdf.Dictionary(Nums=_nums_array(group), Limits=_limits(first, last))
        )
        nodes.append((first, last, leaf))

    while len(nodes) > 1:
        parents: list[tuple[int, int, pikepdf.Object]] = []
        for group in _chunk(nodes, fan_out):
            first, last = group[0][0], group[-1][1]
            parent = pdf.make_indirect(
                pikepdf.Dictionary(
                    Kids=pikepdf.Array([node for _, _, node in group]),
                    Limits=_limits(first, last),
                )
            )
            parents.append((first, last, parent))
        nodes = parents

    # The root must not carry /Limits; only its descendants do.
    root_node = nodes[0][2]
    if "/Limits" in root_node:
        del root_node["/Limits"]
    return root_node


def lookup(root: pikepdf.Object, key: int) -> pikepdf.Object | None:
    """Resolve ``key`` by descending the tree, mirroring a consumer's lookup.

    Returns ``None`` when the key is absent. Used by the tests to prove the
    built tree is navigable by limit comparison rather than by scanning.
    """
    node = root
    while True:
        if "/Nums" in node:
            nums = node["/Nums"]
            for index in range(0, len(nums), 2):
                if int(nums[index]) == key:
                    return nums[index + 1]
            return None
        kids = node.get("/Kids")
        if kids is None:
            return None
        for kid in kids:
            limits = kid.get("/Limits")
            if limits is None:
                continue
            if int(limits[0]) <= key <= int(limits[1]):
                node = kid
                break
        else:
            return None


def validate_number_tree(root: pikepdf.Object, expected_keys: Sequence[int]) -> None:
    """Assert the structural invariants of a number tree.

    Raises:
        AssertionError: With a description of the first invariant violated.
    """
    seen: list[int] = []

    def walk(node: pikepdf.Object, is_root: bool) -> tuple[int, int]:
        has_nums = "/Nums" in node
        has_kids = "/Kids" in node
        if has_nums == has_kids:
            raise AssertionError("a node must carry exactly one of /Nums or /Kids")

        if has_nums:
            nums = node["/Nums"]
            if len(nums) % 2 != 0:
                raise AssertionError("/Nums must hold key and value pairs")
            keys = [int(nums[i]) for i in range(0, len(nums), 2)]
            if keys != sorted(keys):
                raise AssertionError(f"/Nums keys are not ascending: {keys}")
            seen.extend(keys)
            low, high = (keys[0], keys[-1]) if keys else (0, -1)
        else:
            kids = node["/Kids"]
            if len(kids) == 0:
                raise AssertionError("/Kids must not be empty")
            ranges = [walk(kid, is_root=False) for kid in kids]
            for earlier, later in pairwise(ranges):
                if earlier[1] >= later[0]:
                    raise AssertionError(
                        f"sibling limits overlap or are unordered: {earlier} then {later}"
                    )
            low, high = ranges[0][0], ranges[-1][1]

        limits = node.get("/Limits")
        if is_root:
            if limits is not None:
                raise AssertionError("the root node must not carry /Limits")
        else:
            if limits is None:
                raise AssertionError("every non-root node must carry /Limits")
            if (int(limits[0]), int(limits[1])) != (low, high):
                raise AssertionError(
                    f"/Limits {[int(limits[0]), int(limits[1])]} does not match "
                    f"the subtree range {[low, high]}"
                )
        return low, high

    walk(root, is_root=True)

    if sorted(seen) != sorted(expected_keys):
        missing = sorted(set(expected_keys) - set(seen))
        extra = sorted(set(seen) - set(expected_keys))
        raise AssertionError(f"key set mismatch; missing={missing} unexpected={extra}")
    if len(seen) != len(set(seen)):
        raise AssertionError("a key appears more than once in the tree")


__all__ = [
    "DEFAULT_FAN_OUT",
    "DEFAULT_LEAF_SIZE",
    "FLAT_THRESHOLD",
    "build_number_tree",
    "lookup",
    "validate_number_tree",
]
