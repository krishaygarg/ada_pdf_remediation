"""Rectangle clustering.

``merge_bboxes`` in :mod:`remediator.utils` compares every pair of rectangles,
so grouping the path fragments on a page of vector artwork costs O(n squared)
comparisons. A page with fifty thousand path operators, which a single detailed
figure produces, makes that the dominant cost of the whole run.

This module groups the same rectangles with a sweep line. Rectangles are sorted
by their left edge and only those whose horizontal extents currently overlap are
compared, which is O(n log n) plus the number of pairs that genuinely touch.
The result is defined to be identical to the pairwise version, and a property
test asserts that on random input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from collections.abc import Iterable, Sequence

#: Rectangles within this distance of each other are treated as one region.
#: Hairline table rules and the cell content they enclose are typically a point
#: or two apart, and separating them produces a figure per rule.
DEFAULT_PADDING = 2.0


class Box(NamedTuple):
    """A rectangle in PDF user space."""

    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def union(self, other: Box) -> Box:
        return Box(
            min(self.x0, other.x0),
            min(self.top, other.top),
            max(self.x1, other.x1),
            max(self.bottom, other.bottom),
        )

    def contains(self, other: Box) -> bool:
        return (
            self.x0 <= other.x0
            and self.top <= other.top
            and self.x1 >= other.x1
            and self.bottom >= other.bottom
        )

    def intersects(self, other: Box, padding: float = 0.0) -> bool:
        return not (
            self.x1 + padding < other.x0
            or self.x0 - padding > other.x1
            or self.bottom + padding < other.top
            or self.top - padding > other.bottom
        )


class _DisjointSet:
    """Union-find with path compression and union by size."""

    def __init__(self, count: int) -> None:
        self._parent = list(range(count))
        self._size = [1] * count

    def find(self, item: int) -> int:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        if self._size[a] < self._size[b]:
            a, b = b, a
        self._parent[b] = a
        self._size[a] += self._size[b]


def cluster_boxes(
    boxes: Sequence[Box] | Iterable[Sequence[float]],
    padding: float = DEFAULT_PADDING,
) -> list[Box]:
    """Group rectangles that touch, within ``padding``, and return their unions.

    Two rectangles join a group when they are within ``padding`` of each other
    on both axes. Grouping is transitive, so a chain of touching rectangles
    forms one region.

    The result is the same set of regions the pairwise implementation produces.
    What differs is the work: sorting by left edge means a rectangle is only
    compared against those still open on the sweep line.
    """
    items = [Box(*map(float, box)) for box in boxes]
    if len(items) <= 1:
        return list(items)

    order = sorted(range(len(items)), key=lambda index: items[index].x0)
    groups = _DisjointSet(len(items))

    # Indices whose right edge, widened by the padding, has not yet been passed.
    active: list[int] = []
    for index in order:
        box = items[index]
        still_active: list[int] = []
        for candidate in active:
            if items[candidate].x1 + padding < box.x0:
                # Sorted order guarantees this rectangle cannot touch any later
                # one either, so it leaves the sweep line for good.
                continue
            still_active.append(candidate)
            if box.intersects(items[candidate], padding):
                groups.union(index, candidate)
        still_active.append(index)
        active = still_active

    merged: dict[int, Box] = {}
    for index, box in enumerate(items):
        root = groups.find(index)
        merged[root] = merged[root].union(box) if root in merged else box
    return list(merged.values())


def significant_regions(
    boxes: Iterable[Sequence[float]],
    *,
    page_width: float,
    page_height: float,
    padding: float = DEFAULT_PADDING,
    min_area_ratio: float = 0.0025,
    max_area_ratio: float = 0.95,
) -> list[Box]:
    """Cluster rectangles and keep those large enough to be a figure.

    Two thresholds, both expressed as a fraction of the page. Below the lower
    one a region is a rule, an underline or a bullet, and tagging it as a figure
    adds noise to the reading order. Above the upper one it is a page border or
    a background wash, and tagging that as a figure hides the entire page behind
    one element.
    """
    page_area = max(1.0, page_width * page_height)
    regions = cluster_boxes([Box(*map(float, box)) for box in boxes], padding)
    lower = page_area * min_area_ratio
    upper = page_area * max_area_ratio
    return sorted(
        (region for region in regions if lower <= region.area <= upper),
        key=lambda region: (region.top, region.x0),
    )


__all__ = ["DEFAULT_PADDING", "Box", "cluster_boxes", "significant_regions"]
