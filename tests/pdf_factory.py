"""Builders for small, deterministic PDF documents used across the test suite.

Fixture documents are generated rather than committed as binaries. Generated
documents keep the repository small, make the exact structure under test
visible in the diff, and let a test state the precise malformation it cares
about instead of relying on an opaque file.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pikepdf

LETTER = (612.0, 792.0)

_BASE14 = {
    "Helvetica": pikepdf.Name("/Helvetica"),
    "Times-Roman": pikepdf.Name("/Times-Roman"),
    "Courier": pikepdf.Name("/Courier"),
}


def _font_dict(pdf: pikepdf.Pdf, base_font: str, with_tounicode: bool) -> pikepdf.Object:
    font = pikepdf.Dictionary(
        Type=pikepdf.Name("/Font"),
        Subtype=pikepdf.Name("/Type1"),
        BaseFont=_BASE14.get(base_font, pikepdf.Name(f"/{base_font}")),
        Encoding=pikepdf.Name("/WinAnsiEncoding"),
    )
    if with_tounicode:
        cmap = (
            "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CMapName /Test-ToUnicode def\n/CMapType 2 def\n"
            "1 begincodespacerange <00> <FF> endcodespacerange\n"
            "1 beginbfchar <41> <0041> endbfchar\n"
            "endcmap\nend\nend"
        )
        font["/ToUnicode"] = pikepdf.Stream(pdf, cmap.encode("ascii"))
    return pdf.make_indirect(font)


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_text_pdf(
    path: Path,
    *,
    pages: int = 1,
    lines_per_page: Sequence[str] | None = None,
    base_font: str = "Helvetica",
    with_tounicode: bool = True,
    page_size: tuple[float, float] = LETTER,
    title: str | None = None,
) -> Path:
    """Write a minimal text-bearing PDF and return its path.

    Each line becomes its own ``BT``/``ET`` block, which is the granularity the
    remediation pipeline treats as one logical text block.
    """
    lines = list(lines_per_page or ["Paragraph one.", "Paragraph two.", "Paragraph three."])
    pdf = pikepdf.new()
    font = _font_dict(pdf, base_font, with_tounicode)

    for _ in range(pages):
        ops: list[str] = []
        y = page_size[1] - 72.0
        for offset, line in enumerate(lines):
            ops.append(f"BT /F1 12 Tf 1 0 0 1 72 {y - offset * 24:.2f} Tm ({_escape(line)}) Tj ET")
        # A stroked rule, which the pipeline should classify as an artifact.
        rule_y = y - len(lines) * 24 - 12
        ops.append(f"0.5 w 72 {rule_y:.2f} m 300 {rule_y:.2f} l S")
        content = "\n".join(ops).encode("ascii")

        page = pikepdf.Dictionary(
            Type=pikepdf.Name("/Page"),
            MediaBox=pikepdf.Array([0, 0, page_size[0], page_size[1]]),
            Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)),
            Contents=pikepdf.Stream(pdf, content),
        )
        pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))

    if title:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta["dc:title"] = title

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    pdf.close()
    return path


def build_pdf_with_link(
    path: Path,
    *,
    uri: str = "https://example.org/",
    page_size: tuple[float, float] = LETTER,
) -> Path:
    """Write a one-page PDF containing text plus a single Link annotation."""
    pdf = pikepdf.new()
    font = _font_dict(pdf, "Helvetica", with_tounicode=True)
    ops = "\n".join(
        [
            "BT /F1 12 Tf 1 0 0 1 72 700 Tm (Paragraph before the link.) Tj ET",
            "BT /F1 12 Tf 1 0 0 1 72 660 Tm (Visit the project homepage.) Tj ET",
            "BT /F1 12 Tf 1 0 0 1 72 620 Tm (Paragraph after the link.) Tj ET",
        ]
    ).encode("ascii")

    annot = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/Link"),
            Rect=pikepdf.Array([72, 655, 300, 675]),
            Border=pikepdf.Array([0, 0, 0]),
            A=pikepdf.Dictionary(
                S=pikepdf.Name("/URI"),
                URI=pikepdf.String(uri),
            ),
        )
    )
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, page_size[0], page_size[1]]),
        Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)),
        Contents=pikepdf.Stream(pdf, ops),
        Annots=pikepdf.Array([annot]),
    )
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    pdf.close()
    return path


def build_image_only_pdf(
    path: Path,
    *,
    text: str = "SCANNED",
    page_size: tuple[float, float] = LETTER,
) -> Path:
    """Write a PDF whose only content is a raster image, simulating a scan.

    Used to exercise the OCR fallback. The image is a plain white field with a
    black bar so the file stays tiny; tests that need real recognised words
    render their own bitmap.
    """
    from PIL import Image, ImageDraw

    width, height = 850, 1100
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, 100, 100 + 12 * len(text), 160], fill="black")

    pdf = pikepdf.new()
    raw = image.tobytes()
    xobject = pikepdf.Stream(pdf, raw)
    xobject.Type = pikepdf.Name("/XObject")
    xobject.Subtype = pikepdf.Name("/Image")
    xobject.Width = width
    xobject.Height = height
    xobject.ColorSpace = pikepdf.Name("/DeviceRGB")
    xobject.BitsPerComponent = 8

    content = f"q {page_size[0]} 0 0 {page_size[1]} 0 0 cm /Im1 Do Q".encode("ascii")
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, page_size[0], page_size[1]]),
        Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im1=pdf.make_indirect(xobject))),
        Contents=pikepdf.Stream(pdf, content),
    )
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    pdf.close()
    return path


def graphics_stack_depths(pdf_path: Path) -> list[tuple[int, int]]:
    """Return ``(final_depth, minimum_depth)`` of the ``q``/``Q`` stack per page.

    A well formed content stream never lets the minimum drop below zero (which
    would pop an empty stack) and finishes at exactly zero.
    """
    results: list[tuple[int, int]] = []
    with pikepdf.open(pdf_path) as pdf:
        for page in pdf.pages:
            depth = 0
            minimum = 0
            for _operands, operator in pikepdf.parse_content_stream(page):
                name = str(operator)
                if name == "q":
                    depth += 1
                elif name == "Q":
                    depth -= 1
                    minimum = min(minimum, depth)
            results.append((depth, minimum))
    return results


def page_mcids(pdf_path: Path) -> list[list[int]]:
    """Return the marked-content identifiers appearing in each page's stream."""
    out: list[list[int]] = []
    with pikepdf.open(pdf_path) as pdf:
        for page in pdf.pages:
            found: list[int] = []
            for operands, operator in pikepdf.parse_content_stream(page):
                if str(operator) != "BDC" or len(operands) < 2:
                    continue
                properties = operands[1]
                if isinstance(properties, pikepdf.Dictionary) and "/MCID" in properties:
                    found.append(int(properties["/MCID"]))
            out.append(found)
    return out


def iter_struct_elements(pdf: pikepdf.Pdf) -> Iterable[pikepdf.Object]:
    """Yield every structure element reachable from the structure tree root.

    Cycle detection keys on the PDF object number rather than the Python
    ``id()`` of the wrapper. pikepdf materialises a fresh wrapper on each
    access, so ``id()`` is neither stable nor unique and would drop or duplicate
    nodes depending on when the garbage collector runs.
    """
    root = pdf.Root.get("/StructTreeRoot")
    if root is None:
        return

    visited: set[tuple[int, int]] = set()

    def walk(node: pikepdf.Object) -> Iterable[pikepdf.Object]:
        if not isinstance(node, pikepdf.Dictionary):
            return
        objgen = node.objgen
        if objgen != (0, 0):
            if objgen in visited:
                return
            visited.add(objgen)
        if str(node.get("/Type", "")) == "/StructElem":
            yield node
        kids = node.get("/K")
        if isinstance(kids, pikepdf.Array):
            for kid in kids:
                yield from walk(kid)
        elif isinstance(kids, pikepdf.Dictionary):
            yield from walk(kids)

    yield from walk(root)
