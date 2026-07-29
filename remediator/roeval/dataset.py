"""Benchmark datasets.

A dataset is a JSON Lines file with one page per line. Each line carries the
elements found on that page and the order a person judged correct.

This module reads and validates that format. It deliberately does **not**
extract elements from PDFs: that is Phase 1 of the research specification, and
``remediator.reading_order.extract_text_blocks`` is where it belongs. Keeping
the boundary here means the harness consumes data the research produces rather
than duplicating it.

Schema, one JSON object per line::

    {
      "id": "physics-p3",              // unique within the dataset
      "source": "samples/physics.pdf", // optional, for traceability
      "page_index": 2,                 // optional, defaults to 0
      "page_width": 612.0,             // optional
      "page_height": 792.0,            // optional
      "page_image": "pages/p3.png",    // optional, for visual strategies
      "elements": [
        {
          "id": 0,
          "type": "H1",
          "text": "Projectile motion",
          "bbox": [72.0, 88.0, 402.0, 112.0],
          "mcids": [0],
          "reading_order_index": 0     // the ground truth position
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .strategy import PageElement


class DatasetError(ValueError):
    """Raised when a dataset file does not match the schema."""


@dataclass(frozen=True)
class BenchmarkPage:
    """One page of a benchmark, with its reference ordering."""

    id: str
    elements: tuple[PageElement, ...]
    reference: tuple[int, ...]
    """Element identifiers in the order a person judged correct."""

    source: str | None = None
    page_image: str | None = None
    page_width: float | None = None
    page_height: float | None = None

    @property
    def reference_elements(self) -> list[PageElement]:
        by_id = {element.id: element for element in self.elements}
        return [by_id[identifier] for identifier in self.reference]


def _element_from(raw: dict[str, Any], line: int, page_index: int) -> tuple[PageElement, int]:
    for key in ("id", "bbox"):
        if key not in raw:
            raise DatasetError(f"line {line}: an element is missing {key!r}")
    bbox = raw["bbox"]
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        raise DatasetError(f"line {line}: bbox must be four numbers, got {bbox!r}")
    try:
        coordinates = tuple(float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"line {line}: bbox contains a non-number: {bbox!r}") from exc

    order = raw.get("reading_order_index")
    if order is None:
        raise DatasetError(
            f"line {line}: element {raw['id']} has no reading_order_index. "
            "A page without a reference ordering cannot be scored."
        )

    element = PageElement(
        id=int(raw["id"]),
        type=str(raw.get("type", "P")).lstrip("/"),
        bbox=coordinates,  # type: ignore[arg-type]
        text=str(raw.get("text", "")),
        mcids=tuple(int(value) for value in raw.get("mcids", ())),
        page_index=page_index,
        attributes={
            key: value
            for key, value in raw.items()
            if key not in {"id", "type", "bbox", "text", "mcids", "reading_order_index"}
        },
    )
    return element, int(order)


def load_page(raw: dict[str, Any], line: int) -> BenchmarkPage:
    """Build one page from a decoded JSON object."""
    if "elements" not in raw:
        raise DatasetError(f"line {line}: the record has no 'elements'")
    page_index = int(raw.get("page_index", 0))

    pairs = [_element_from(entry, line, page_index) for entry in raw["elements"]]
    if not pairs:
        raise DatasetError(f"line {line}: the record has no elements")

    identifiers = [element.id for element, _ in pairs]
    if len(set(identifiers)) != len(identifiers):
        raise DatasetError(f"line {line}: element identifiers are not unique")

    orders = [order for _, order in pairs]
    if sorted(orders) != list(range(len(orders))):
        raise DatasetError(
            f"line {line}: reading_order_index must be a permutation of "
            f"0..{len(orders) - 1}, got {sorted(orders)}"
        )

    reference = [element.id for element, _ in sorted(pairs, key=lambda pair: pair[1])]
    return BenchmarkPage(
        id=str(raw.get("id", f"line-{line}")),
        elements=tuple(element for element, _ in pairs),
        reference=tuple(reference),
        source=raw.get("source"),
        page_image=raw.get("page_image"),
        page_width=raw.get("page_width"),
        page_height=raw.get("page_height"),
    )


def load_dataset(path: Path | str) -> list[BenchmarkPage]:
    """Read a JSON Lines benchmark file.

    Raises:
        DatasetError: With the line number, when a record does not validate.
            Failing loudly matters here: a silently skipped page would make a
            strategy look better than it is.
    """
    path = Path(path)
    if not path.is_file():
        raise DatasetError(f"no dataset at {path}")

    pages: list[BenchmarkPage] = []
    seen: set[str] = set()
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = text.strip()
        if not stripped or stripped.startswith("//"):
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"line {number}: invalid JSON: {exc.msg}") from exc
        page = load_page(raw, number)
        if page.id in seen:
            raise DatasetError(f"line {number}: duplicate page id {page.id!r}")
        seen.add(page.id)
        pages.append(page)

    if not pages:
        raise DatasetError(f"{path} contains no records")
    return pages


def write_dataset(path: Path | str, pages: list[BenchmarkPage]) -> None:
    """Write pages back out, for tooling that builds datasets."""
    lines = []
    for page in pages:
        position = {identifier: index for index, identifier in enumerate(page.reference)}
        lines.append(
            json.dumps(
                {
                    "id": page.id,
                    "source": page.source,
                    "page_index": page.elements[0].page_index if page.elements else 0,
                    "page_width": page.page_width,
                    "page_height": page.page_height,
                    "page_image": page.page_image,
                    "elements": [
                        {
                            "id": element.id,
                            "type": element.type,
                            "text": element.text,
                            "bbox": list(element.bbox),
                            "mcids": list(element.mcids),
                            "reading_order_index": position[element.id],
                        }
                        for element in page.elements
                    ],
                }
            )
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["BenchmarkPage", "DatasetError", "load_dataset", "load_page", "write_dataset"]
