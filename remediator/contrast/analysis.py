"""Measuring the contrast of every text run in a document.

The hard part is not the arithmetic, it is deciding what the background behind
a given piece of text actually is. A PDF has no notion of a background: there
is only paint order. Text may sit on the page, on a filled rectangle, on a
gradient, on a photograph, or on all of those in layers.

The approach here is to render the page and read the answer off the pixels,
which is what a reader sees and therefore the only definition that matters.
Within a run's bounding box the pixels form two populations, the glyphs and
whatever is behind them. The glyph colour is declared in the content stream, so
the populations can be separated by distance from it in CIELAB, and the
background is the median of the far population. Anti-aliased edge pixels fall
between the two and are excluded by the same threshold.

This makes checkpoint 04 of the Matterhorn Protocol, Colour and Contrast,
machine determinable. The protocol classifies it as requiring human judgement,
and no open source tool appears to attempt it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .color import Rgb, apca_contrast, contrast_ratio, delta_e, to_lab

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from collections.abc import Iterator

    from numpy.typing import NDArray

#: Rendering resolution. High enough that a 6 point glyph still covers several
#: pixels, low enough that a 400 page document stays workable.
DEFAULT_DPI = 144

#: WCAG 2.1 calls text large at 18 point, or 14 point when bold. Large text
#: carries a lower threshold because stroke weight, not just luminance
#: difference, determines whether an edge is resolvable.
LARGE_TEXT_POINTS = 18.0
LARGE_BOLD_POINTS = 14.0

#: WCAG 1.4.3 Contrast (Minimum), level AA.
AA_NORMAL = 4.5
AA_LARGE = 3.0

#: WCAG 1.4.6 Contrast (Enhanced), level AAA.
AAA_NORMAL = 7.0
AAA_LARGE = 4.5

#: APCA guidance, reported alongside rather than enforced. Lc 60 is roughly
#: where body text becomes comfortable; Lc 45 suits larger or heavier text.
APCA_BODY = 60.0
APCA_LARGE = 45.0

#: Pixels closer than this fraction of the observed spread to the declared text
#: colour are treated as glyph, not background.
_SEPARATION_FRACTION = 0.5

#: Below this spread the region is effectively one colour, which means the text
#: is invisible rather than low contrast.
_UNIFORM_REGION_DELTA_E = 4.0

#: A run needs at least this many background pixels for the median to mean
#: anything.
_MIN_BACKGROUND_PIXELS = 12


class Verdict(enum.Enum):
    PASS_AAA = "pass-aaa"
    PASS_AA = "pass-aa"
    FAIL_AA = "fail-aa"
    INVISIBLE = "invisible"
    UNDETERMINED = "undetermined"

    @property
    def is_failure(self) -> bool:
        return self in (Verdict.FAIL_AA, Verdict.INVISIBLE)


@dataclass(frozen=True)
class TextRun:
    """One run of text with a single colour and size."""

    page_index: int
    text: str
    bbox: tuple[float, float, float, float]
    color: Rgb
    size: float
    bold: bool
    font: str

    @property
    def is_large(self) -> bool:
        return self.size >= LARGE_TEXT_POINTS or (self.bold and self.size >= LARGE_BOLD_POINTS)


@dataclass(frozen=True)
class ContrastFinding:
    """The contrast measurement for one text run."""

    run: TextRun
    background: Rgb | None
    ratio: float | None
    apca: float | None
    verdict: Verdict
    detail: str = ""

    @property
    def required_ratio(self) -> float:
        return AA_LARGE if self.run.is_large else AA_NORMAL

    @property
    def apca_target(self) -> float:
        return APCA_LARGE if self.run.is_large else APCA_BODY

    def describe(self) -> str:
        if self.verdict is Verdict.INVISIBLE:
            return f"Text {self.run.text[:40]!r} is not distinguishable from its background."
        if self.ratio is None or self.background is None:
            return f"Contrast for {self.run.text[:40]!r} could not be determined. {self.detail}"
        size = f"{self.run.size:.1f}pt{' bold' if self.run.bold else ''}"
        return (
            f"Text {self.run.text[:40]!r} ({size}) has contrast "
            f"{self.ratio:.2f}:1 against its background "
            f"({self.run.color.to_hex()} on {self.background.to_hex()}), "
            f"below the {self.required_ratio}:1 required. "
            f"APCA Lc {self.apca:+.0f}."
        )


def _classify_verdict(ratio: float, large: bool) -> Verdict:
    if ratio >= (AAA_LARGE if large else AAA_NORMAL):
        return Verdict.PASS_AAA
    if ratio >= (AA_LARGE if large else AA_NORMAL):
        return Verdict.PASS_AA
    return Verdict.FAIL_AA


def iter_text_runs(document: Any, page_index: int) -> Iterator[TextRun]:
    """Yield the text runs on a page, with their declared colour and size."""
    page = document[page_index]
    raw = page.get_text("dict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text", ""))
                if not text.strip():
                    continue
                bbox = tuple(float(value) for value in span.get("bbox", (0, 0, 0, 0)))
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                flags = int(span.get("flags", 0))
                yield TextRun(
                    page_index=page_index,
                    text=text,
                    bbox=bbox,  # type: ignore[arg-type]
                    color=Rgb.from_int(int(span.get("color", 0))),
                    size=float(span.get("size", 0.0)),
                    # Bit 4 of the span flags marks a bold face in PyMuPDF.
                    bold=bool(flags & 16),
                    font=str(span.get("font", "")),
                )


def estimate_background(
    pixels: list[tuple[int, int, int]], text_color: Rgb
) -> tuple[Rgb | None, str]:
    """Separate background pixels from glyph pixels and return their median.

    Returns ``(colour, note)``. The colour is ``None`` when the region does not
    contain two distinguishable populations, which happens when the text is the
    same colour as what is behind it.
    """
    if len(pixels) < _MIN_BACKGROUND_PIXELS:
        return None, "the run covers too few pixels to sample"

    distances = [(delta_e(Rgb.from_bytes(*pixel), text_color), pixel) for pixel in pixels]
    spread = max(distance for distance, _ in distances)

    if spread < _UNIFORM_REGION_DELTA_E:
        return None, "the region is a single colour"

    threshold = spread * _SEPARATION_FRACTION
    background_pixels = [pixel for distance, pixel in distances if distance >= threshold]
    if len(background_pixels) < _MIN_BACKGROUND_PIXELS:
        # Heavy or tightly set text can fill its own bounding box. Falling back
        # to the farthest quartile still samples the lightest available ground.
        background_pixels = [
            pixel for _distance, pixel in sorted(distances)[-len(distances) // 4 :]
        ]
    if not background_pixels:
        return None, "no background pixels could be isolated"

    # The median is taken in CIELAB, where distance is roughly perceptual, and
    # then resolved back to a colour that genuinely occurs in the region rather
    # than to an interpolated value that may not.
    labs = [to_lab(Rgb.from_bytes(*pixel)) for pixel in background_pixels]
    median = tuple(sorted(channel[index] for channel in labs)[len(labs) // 2] for index in range(3))
    best = min(
        range(len(labs)),
        key=lambda i: sum((labs[i][c] - median[c]) ** 2 for c in range(3)),
    )
    return Rgb.from_bytes(*background_pixels[best]), ""


def _srgb_array_to_lab(pixels: NDArray[Any]) -> NDArray[Any]:
    """Convert an ``(n, 3)`` array of 8 bit sRGB to CIELAB.

    The scalar path in :mod:`.color` is the readable reference, and the two are
    held together by a test. This version exists because a single page carries
    hundreds of thousands of pixels, and converting them one at a time made the
    analysis take twenty seconds for five pages.
    """
    import numpy as np

    channels = pixels.astype(np.float64) / 255.0
    linear = np.where(channels <= 0.04045, channels / 12.92, ((channels + 0.055) / 1.055) ** 2.4)
    transform = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = linear @ transform.T / np.array(_D65_WHITE)

    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz > epsilon, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    return np.stack(
        [
            116.0 * f[:, 1] - 16.0,
            500.0 * (f[:, 0] - f[:, 1]),
            200.0 * (f[:, 1] - f[:, 2]),
        ],
        axis=1,
    )


_D65_WHITE = (0.95047, 1.00000, 1.08883)


def _estimate_background_vectorised(
    pixels: NDArray[Any], text_lab: NDArray[Any]
) -> tuple[tuple[int, int, int] | None, str]:
    """Vectorised counterpart of :func:`estimate_background`.

    Returns ``(rgb tuple or None, note)`` with the same semantics.
    """
    import numpy as np

    if len(pixels) < _MIN_BACKGROUND_PIXELS:
        return None, "the run covers too few pixels to sample"

    labs = _srgb_array_to_lab(pixels)
    distances = np.sqrt(((labs - text_lab) ** 2).sum(axis=1))
    spread = float(distances.max())

    if spread < _UNIFORM_REGION_DELTA_E:
        return None, "the region is a single colour"

    mask = distances >= spread * _SEPARATION_FRACTION
    if int(mask.sum()) < _MIN_BACKGROUND_PIXELS:
        # Heavy or tightly set text can fill its own bounding box. Taking the
        # farthest quartile still samples the ground rather than the ink.
        cutoff = max(1, len(distances) // 4)
        mask = np.zeros(len(distances), dtype=bool)
        mask[np.argsort(distances)[-cutoff:]] = True

    selected_labs = labs[mask]
    selected_rgb = pixels[mask]
    if len(selected_rgb) == 0:  # pragma: no cover - mask always selects something
        return None, "no background pixels could be isolated"

    median = np.median(selected_labs, axis=0)
    best = int(np.argmin(((selected_labs - median) ** 2).sum(axis=1)))
    chosen = selected_rgb[best]
    return (int(chosen[0]), int(chosen[1]), int(chosen[2])), ""


def analyse_page(document: Any, page_index: int, dpi: int = DEFAULT_DPI) -> list[ContrastFinding]:
    """Measure the contrast of every text run on one page."""
    import fitz
    import numpy as np

    page = document[page_index]
    scale = dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    raster = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.stride // pixmap.n, pixmap.n
    )[:, : pixmap.width, :3]

    findings: list[ContrastFinding] = []
    for run in iter_text_runs(document, page_index):
        # One pixel of margin catches the ground immediately around the glyphs,
        # which matters for a run whose box is fitted tightly to its ink.
        x0 = max(0, int(run.bbox[0] * scale) - 1)
        y0 = max(0, int(run.bbox[1] * scale) - 1)
        x1 = min(pixmap.width, int(run.bbox[2] * scale) + 2)
        y1 = min(pixmap.height, int(run.bbox[3] * scale) + 2)
        region = raster[y0:y1, x0:x1].reshape(-1, 3)

        text_lab = np.array(to_lab(run.color))
        sampled, note = _estimate_background_vectorised(region, text_lab)

        if sampled is None:
            verdict = (
                Verdict.INVISIBLE
                if note == "the region is a single colour"
                else Verdict.UNDETERMINED
            )
            findings.append(
                ContrastFinding(
                    run=run, background=None, ratio=None, apca=None, verdict=verdict, detail=note
                )
            )
            continue

        background = Rgb.from_bytes(*sampled)
        ratio = contrast_ratio(run.color, background)
        findings.append(
            ContrastFinding(
                run=run,
                background=background,
                ratio=ratio,
                apca=apca_contrast(run.color, background),
                verdict=_classify_verdict(ratio, run.is_large),
            )
        )
    return findings


#: Analyses are cached by path, modification time and resolution. The three
#: contrast rules each ask for the whole document, and rendering it three times
#: would triple the cost of the most expensive checkpoint for no benefit.
_ANALYSIS_CACHE: dict[tuple[str, float, int, int | None], list[ContrastFinding]] = {}
_CACHE_LIMIT = 4


def analyse_document(
    path: str | Path, dpi: int = DEFAULT_DPI, max_pages: int | None = None
) -> list[ContrastFinding]:
    """Measure the contrast of every text run in a document."""
    import fitz

    resolved = Path(path)
    try:
        key = (str(resolved.resolve()), resolved.stat().st_mtime, dpi, max_pages)
    except OSError:  # pragma: no cover - the caller has already opened the file
        key = (str(resolved), 0.0, dpi, max_pages)
    cached = _ANALYSIS_CACHE.get(key)
    if cached is not None:
        return cached

    findings: list[ContrastFinding] = []
    with fitz.open(str(path)) as document:
        count = len(document) if max_pages is None else min(len(document), max_pages)
        for index in range(count):
            findings.extend(analyse_page(document, index, dpi=dpi))

    if len(_ANALYSIS_CACHE) >= _CACHE_LIMIT:
        _ANALYSIS_CACHE.pop(next(iter(_ANALYSIS_CACHE)))
    _ANALYSIS_CACHE[key] = findings
    return findings


def clear_analysis_cache() -> None:
    """Discard cached analyses, for tests and long-running processes."""
    _ANALYSIS_CACHE.clear()


def summarise(findings: list[ContrastFinding]) -> dict[str, int]:
    """Count findings by verdict, for a report header."""
    counts = dict.fromkeys((verdict.value for verdict in Verdict), 0)
    for finding in findings:
        counts[finding.verdict.value] += 1
    return counts


__all__ = [
    "AAA_LARGE",
    "AAA_NORMAL",
    "AA_LARGE",
    "AA_NORMAL",
    "APCA_BODY",
    "APCA_LARGE",
    "DEFAULT_DPI",
    "ContrastFinding",
    "TextRun",
    "Verdict",
    "analyse_document",
    "analyse_page",
    "clear_analysis_cache",
    "estimate_background",
    "iter_text_runs",
    "summarise",
]
