#!/usr/bin/env python3
"""OCR text layer generation for scanned pages.

Tesseract already reports which block, paragraph and line each word belongs to.
The previous implementation discarded that and emitted one ``/P`` structure
element per word, so a screen reader announced every single word as its own
paragraph. A page of two hundred words produced two hundred paragraphs.

This groups words back into their paragraphs and draws each line as one text
run, which is both what a reader expects and a far smaller content stream.

The invisible text is fitted to the image. A word recognised as 40 points wide
must be drawn 40 points wide, or selecting it highlights the wrong part of the
page. The horizontal scale operator solves for that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pikepdf

from .config import ensure_tmp_dir

#: Words recognised below this confidence are dropped. Tesseract reports low
#: confidence on speckle and scan artifacts, and inserting those as text makes
#: the layer worse than leaving the region unrecognised.
MIN_CONFIDENCE = 30

#: Rendering resolution. Recognition accuracy improves up to roughly this point
#: and then flattens while memory keeps growing.
RENDER_DPI = 300

#: Average glyph width of Helvetica as a fraction of the font size, used to
#: estimate a run's natural width when fitting it to the recognised box.
_HELVETICA_AVERAGE_WIDTH = 0.5

_FONT_RESOURCE_NAME = "/AdaOcrHelvetica"


@dataclass
class OcrWord:
    text: str
    left: float
    top: float
    width: float
    height: float
    confidence: float


@dataclass
class OcrLine:
    words: list[OcrWord] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def left(self) -> float:
        return min(word.left for word in self.words)

    @property
    def right(self) -> float:
        return max(word.left + word.width for word in self.words)

    @property
    def top(self) -> float:
        return min(word.top for word in self.words)

    @property
    def bottom(self) -> float:
        return max(word.top + word.height for word in self.words)

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass
class OcrParagraph:
    lines: list[OcrLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


def group_words(data: dict[str, Any]) -> list[OcrParagraph]:
    """Group Tesseract's word-level output into paragraphs and lines.

    ``image_to_data`` returns parallel arrays including ``block_num``,
    ``par_num`` and ``line_num``. Those already express the layout Tesseract
    inferred, so grouping is a matter of reading them rather than
    reconstructing the geometry from coordinates.
    """
    count = len(data.get("text", []))
    buckets: dict[tuple[int, int], dict[int, OcrLine]] = {}
    order: list[tuple[int, int]] = []

    for index in range(count):
        text = str(data["text"][index]).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence < MIN_CONFIDENCE:
            continue

        key = (int(data["block_num"][index]), int(data["par_num"][index]))
        line_number = int(data["line_num"][index])
        if key not in buckets:
            buckets[key] = {}
            order.append(key)
        line = buckets[key].setdefault(line_number, OcrLine())
        line.words.append(
            OcrWord(
                text=text,
                left=float(data["left"][index]),
                top=float(data["top"][index]),
                width=float(data["width"][index]),
                height=float(data["height"][index]),
                confidence=confidence,
            )
        )

    paragraphs: list[OcrParagraph] = []
    for key in order:
        lines = [
            buckets[key][number] for number in sorted(buckets[key]) if buckets[key][number].words
        ]
        if lines:
            paragraphs.append(OcrParagraph(lines=lines))
    return paragraphs


def horizontal_scale(text: str, font_size: float, target_width: float) -> float:
    """Percentage for the ``Tz`` operator that fits ``text`` into ``target_width``.

    The invisible layer has to line up with the image underneath it. Otherwise
    selecting a word highlights a different part of the page and a screen
    reader's caret points somewhere else again. Helvetica's average glyph width
    gives the natural width; the ratio to the recognised width is the scale.

    Clamped to a sane band so one mis-recognised box cannot stretch a run across
    the whole page.
    """
    if not text or font_size <= 0 or target_width <= 0:
        return 100.0
    natural = len(text) * font_size * _HELVETICA_AVERAGE_WIDTH
    if natural <= 0:
        return 100.0
    return max(10.0, min(400.0, (target_width / natural) * 100.0))


def _ensure_font(pdf_doc: pikepdf.Pdf, page: pikepdf.Object) -> None:
    """Register the invisible layer's font in the page resources."""
    if "/Resources" not in page:
        page.Resources = pikepdf.Dictionary()
    if "/Font" not in page.Resources:
        page.Resources.Font = pikepdf.Dictionary()
    if _FONT_RESOURCE_NAME not in page.Resources.Font:
        page.Resources.Font[_FONT_RESOURCE_NAME] = pdf_doc.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type1"),
                BaseFont=pikepdf.Name("/Helvetica"),
                Encoding=pikepdf.Name("/WinAnsiEncoding"),
            )
        )


def _encodable(text: str) -> str:
    """Reduce text to what the WinAnsi-encoded base font can represent.

    The layer is invisible, so an unrepresentable character changes nothing
    visually, but it would be extracted as the wrong character. Dropping it
    leaves a gap instead, which is the recoverable failure.
    """
    return "".join(character for character in text if character.encode("cp1252", "ignore"))


def generate_ocr_text_ops(
    pdf_path: str,
    page_idx: int,
    page_width: float,
    page_height: float,
    start_mcid: int,
    pdf_doc: pikepdf.Pdf,
    pikepage: pikepdf.Object,
    document_elem: pikepdf.Object,
    language: str = "eng",
) -> tuple[list[Any], list[Any], int]:
    """Build an invisible, tagged text layer for a scanned page.

    Returns ``(operators, structure elements, next marked-content identifier)``.
    One structure element is produced per recognised paragraph, not per word.
    """
    ops: list[Any] = []
    elements: list[Any] = []
    mcid = start_mcid

    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as exc:
        print(f"[REMEDIATOR-OCR] OCR support is not installed ({exc}); skipping the text layer.")
        return ops, elements, mcid

    try:
        images = convert_from_path(
            pdf_path,
            dpi=RENDER_DPI,
            first_page=page_idx + 1,
            last_page=page_idx + 1,
            output_folder=str(ensure_tmp_dir()),
        )
        if not images:
            return ops, elements, mcid

        image = images[0]
        image_width, image_height = image.size
        scale_x = page_width / image_width if image_width else 1.0
        scale_y = page_height / image_height if image_height else 1.0

        data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
        paragraphs = group_words(data)
        if not paragraphs:
            return ops, elements, mcid

        _ensure_font(pdf_doc, pikepage)

        ops.append(([], pikepdf.Operator("BT")))
        # Rendering mode 3 draws nothing. The text is present for selection,
        # search and assistive technology without altering the page.
        ops.append(([pikepdf.Integer(3)], pikepdf.Operator("Tr")))

        for paragraph in paragraphs:
            drawn = False
            for line in paragraph.lines:
                text = _encodable(line.text)
                if not text:
                    continue
                if not drawn:
                    ops.append(
                        (
                            [pikepdf.Name("/P"), pikepdf.Dictionary(MCID=mcid)],
                            pikepdf.Operator("BDC"),
                        )
                    )
                    drawn = True

                font_size = max(4.0, line.height * scale_y)
                target_width = (line.right - line.left) * scale_x
                scale = horizontal_scale(text, font_size, target_width)

                # PDF places the origin at the bottom left; the image reports a
                # top-left origin, so the vertical axis is inverted.
                x = line.left * scale_x
                y = page_height - (line.bottom * scale_y)

                ops.append(([pikepdf.Name(_FONT_RESOURCE_NAME), font_size], pikepdf.Operator("Tf")))
                ops.append(([scale], pikepdf.Operator("Tz")))
                ops.append(([1.0, 0.0, 0.0, 1.0, x, y], pikepdf.Operator("Tm")))
                ops.append(([pikepdf.String(text)], pikepdf.Operator("Tj")))

            if drawn:
                ops.append(([], pikepdf.Operator("EMC")))
                element = pdf_doc.make_indirect(
                    pikepdf.Dictionary(
                        Type=pikepdf.Name("/StructElem"),
                        S=pikepdf.Name("/P"),
                        P=document_elem,
                        Pg=pikepage.obj,
                        K=pikepdf.Integer(mcid),
                    )
                )
                document_elem.K.append(element)
                elements.append(element)
                mcid += 1

        ops.append(([], pikepdf.Operator("ET")))
        print(
            f"  - Recognised {len(paragraphs)} paragraphs "
            f"({sum(len(p.lines) for p in paragraphs)} lines) on page {page_idx + 1}"
        )

    except Exception as exc:
        print(f"[REMEDIATOR-OCR] Text layer generation failed on page {page_idx + 1}: {exc}")
        return [], [], start_mcid

    return ops, elements, mcid


__all__ = [
    "MIN_CONFIDENCE",
    "RENDER_DPI",
    "OcrLine",
    "OcrParagraph",
    "OcrWord",
    "generate_ocr_text_ops",
    "group_words",
    "horizontal_scale",
]
