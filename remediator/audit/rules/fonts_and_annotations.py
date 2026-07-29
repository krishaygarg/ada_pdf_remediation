"""Rules covering fonts and annotations.

Matterhorn checkpoints 28 (Annotations), 30 (XObjects) and 31 (Fonts), plus the
character mapping requirement in checkpoint 10.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pikepdf

from ..context import DocumentContext
from ..model import Finding, Location, RuleMetadata, Severity
from ..registry import rule

#: Annotation subtypes exempt from needing a description. Popup annotations are
#: reached through their parent, and Link handling has its own condition.
_EXEMPT_SUBTYPES = frozenset({"/Popup", "/Widget", "/Projection"})

#: Bit 2 of the annotation flags marks it hidden, which excuses it from the
#: description requirement because it is never presented.
_HIDDEN_FLAG = 2


def _is_hidden(annot: pikepdf.Object) -> bool:
    try:
        return bool(int(annot.get("/F", 0)) & _HIDDEN_FLAG)
    except Exception:
        return False


def _font_descriptors(font: pikepdf.Object) -> Iterator[pikepdf.Object]:
    """Yield the descriptor of a font and of any descendants it delegates to."""
    descriptor = font.get("/FontDescriptor")
    if isinstance(descriptor, pikepdf.Dictionary):
        yield descriptor
    descendants = font.get("/DescendantFonts")
    if isinstance(descendants, pikepdf.Array):
        for descendant in descendants:
            if isinstance(descendant, pikepdf.Dictionary):
                nested = descendant.get("/FontDescriptor")
                if isinstance(nested, pikepdf.Dictionary):
                    yield nested


@rule(
    RuleMetadata(
        condition="31-001",
        checkpoint_name="Fonts",
        summary="A font program is not embedded",
        clause="7.21.4.1",
        wcag=("1.4.5",),
    )
)
def fonts_are_embedded(context: DocumentContext) -> Iterator[Finding]:
    """A reader without the font substitutes glyphs, changing what is shown."""
    reported: set[str] = set()
    for font, object_number in context.fonts:
        base_font = str(font.get("/BaseFont", "unnamed")).lstrip("/")
        subtype = str(font.get("/Subtype", "")).lstrip("/")
        if subtype == "Type3":
            # Type 3 fonts carry their glyph procedures inline.
            continue
        embedded = any(
            any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
            for descriptor in _font_descriptors(font)
        )
        if embedded or base_font in reported:
            continue
        reported.add(base_font)
        yield Finding(
            condition="31-001",
            message=f"The font program for {base_font} is not embedded.",
            location=Location(object_number=object_number),
            remedy=(
                "Embed the font, or regenerate the source document with font "
                "embedding enabled. This cannot be repaired without the font file."
            ),
            context={"base_font": base_font, "subtype": subtype},
        )


@rule(
    RuleMetadata(
        condition="10-001",
        checkpoint_name="Character mappings",
        summary="A font provides no mapping from character codes to Unicode",
        clause="7.21.7",
        wcag=("1.1.1",),
    )
)
def fonts_map_to_unicode(context: DocumentContext) -> Iterator[Finding]:
    reported: set[str] = set()
    for font, object_number in context.fonts:
        subtype = str(font.get("/Subtype", "")).lstrip("/")
        if subtype == "Type0":
            encoding = str(font.get("/Encoding", ""))
            # The predefined Identity encodings still need /ToUnicode; other
            # predefined CMaps carry their own mapping.
            if encoding and not encoding.startswith("/Identity") and "/ToUnicode" not in font:
                continue
        base_font = str(font.get("/BaseFont", "unnamed")).lstrip("/")
        if "/ToUnicode" in font or base_font in reported:
            continue
        reported.add(base_font)
        yield Finding(
            condition="10-001",
            message=f"The font {base_font} has no /ToUnicode mapping.",
            location=Location(object_number=object_number),
            remedy=(
                "Attach a /ToUnicode CMap. Without one, text drawn in this font "
                "cannot be extracted, searched or read aloud."
            ),
            context={"base_font": base_font},
        )


@rule(
    RuleMetadata(
        condition="10-003",
        checkpoint_name="Character mappings",
        summary="A character mapping resolves codes to meaningless values",
        clause="7.21.7",
        wcag=("1.1.1",),
    )
)
def tounicode_maps_are_meaningful(context: DocumentContext) -> Iterator[Finding]:
    """Detects mappings that satisfy the letter of the requirement and nothing else.

    A CMap that sends most codes to U+0020, or to U+FFFD, passes a check for
    the presence of /ToUnicode while making the text unreadable. Extracting the
    text is the only way to notice, which is exactly why it is worth checking.
    """
    entry_pattern = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
    for font, object_number in context.fonts:
        stream = font.get("/ToUnicode")
        if stream is None or not hasattr(stream, "read_bytes"):
            continue
        try:
            raw = bytes(stream.read_bytes())
        except Exception:
            continue

        targets: list[str] = []
        for _source, destination in entry_pattern.findall(raw):
            try:
                decoded = bytes.fromhex(destination.decode("ascii")).decode(
                    "utf-16-be", errors="ignore"
                )
            except Exception:
                continue
            if decoded:
                targets.append(decoded)

        if len(targets) < 16:
            continue

        degenerate = sum(1 for value in targets if value in (" ", "�", "\x00"))
        ratio = degenerate / len(targets)
        if ratio >= 0.5:
            base_font = str(font.get("/BaseFont", "unnamed")).lstrip("/")
            yield Finding(
                condition="10-003",
                message=(
                    f"The /ToUnicode map for {base_font} sends "
                    f"{degenerate} of {len(targets)} codes to a space or "
                    "replacement character."
                ),
                location=Location(object_number=object_number),
                remedy=(
                    "Derive the mapping from the font's own encoding and glyph "
                    "names. Filling unmapped codes with spaces satisfies a "
                    "presence check while destroying the text."
                ),
                context={"degenerate_ratio": round(ratio, 3)},
            )


@rule(
    RuleMetadata(
        condition="28-004",
        checkpoint_name="Annotations",
        summary="An annotation has no alternate description",
        clause="7.18.1",
        wcag=("1.1.1", "4.1.2"),
    )
)
def annotations_have_descriptions(context: DocumentContext) -> Iterator[Finding]:
    for annot, page_index in context.annotations:
        subtype = str(annot.get("/Subtype", ""))
        if subtype in _EXEMPT_SUBTYPES or _is_hidden(annot):
            continue
        contents = str(annot.get("/Contents", "")).strip()
        if contents:
            continue
        yield Finding(
            condition="28-004",
            message=f"A {subtype.lstrip('/') or 'unknown'} annotation has no /Contents.",
            location=Location(page=page_index, object_number=annot.objgen[0] or None),
            remedy="Add /Contents describing what the annotation does or where it leads.",
        )


@rule(
    RuleMetadata(
        condition="28-005",
        checkpoint_name="Annotations",
        summary="An annotation is not reachable from the structure tree",
        clause="7.18.1",
        wcag=("1.3.1",),
    )
)
def annotations_are_in_the_structure_tree(context: DocumentContext) -> Iterator[Finding]:
    if context.root.get("/StructTreeRoot") is None:
        # Absence of the whole tree is reported by condition 01-003; repeating
        # it once per annotation would bury that finding.
        return
    referenced = context.annotation_objgens_in_struct_tree
    for annot, page_index in context.annotations:
        subtype = str(annot.get("/Subtype", ""))
        if subtype in _EXEMPT_SUBTYPES or _is_hidden(annot):
            continue
        if annot.objgen in referenced:
            continue
        yield Finding(
            condition="28-005",
            message=(
                f"A {subtype.lstrip('/') or 'unknown'} annotation is not referenced "
                "by any structure element."
            ),
            location=Location(page=page_index, object_number=annot.objgen[0] or None),
            remedy=(
                "Add a structure element containing an /OBJR that points at the "
                "annotation, so it appears in the reading order."
            ),
        )


@rule(
    RuleMetadata(
        condition="28-006",
        checkpoint_name="Annotations",
        summary="An annotation does not declare a structure parent key",
        clause="7.18.1",
        wcag=("1.3.1",),
    )
)
def annotations_declare_struct_parent(context: DocumentContext) -> Iterator[Finding]:
    """ISO 32000-1 14.7.4.4 requires the key, and requires it to be its own.

    Reusing the page's /StructParents value resolves to an array of content
    elements rather than to the annotation's own element.
    """
    page_keys: dict[int, int] = {}
    for index, page in enumerate(context.pdf.pages):
        value = page.obj.get("/StructParents")
        if value is not None:
            page_keys[int(value)] = index

    for annot, page_index in context.annotations:
        subtype = str(annot.get("/Subtype", ""))
        if subtype in _EXEMPT_SUBTYPES or _is_hidden(annot):
            continue
        value = annot.get("/StructParent")
        if value is None:
            yield Finding(
                condition="28-006",
                message=(
                    f"A {subtype.lstrip('/') or 'unknown'} annotation has no /StructParent entry."
                ),
                location=Location(page=page_index, object_number=annot.objgen[0] or None),
                remedy="Assign a structure parent key that is not used by any page.",
            )
            continue
        key = int(value)
        if key in page_keys:
            yield Finding(
                condition="28-006",
                message=(
                    f"An annotation uses structure parent key {key}, which page "
                    f"{page_keys[key] + 1} already uses. One key cannot resolve to "
                    "both a content array and a single element."
                ),
                location=Location(page=page_index, object_number=annot.objgen[0] or None),
                remedy="Allocate annotation keys from a range above the last page index.",
            )


@rule(
    RuleMetadata(
        condition="28-011",
        checkpoint_name="Annotations",
        summary="A link annotation has no alternate description",
        clause="7.18.5",
        wcag=("2.4.4",),
    )
)
def links_describe_their_destination(context: DocumentContext) -> Iterator[Finding]:
    for annot, page_index in context.annotations:
        if str(annot.get("/Subtype", "")) != "/Link" or _is_hidden(annot):
            continue
        if str(annot.get("/Contents", "")).strip():
            continue
        yield Finding(
            condition="28-011",
            message="A Link annotation has no /Contents describing where it leads.",
            location=Location(page=page_index, object_number=annot.objgen[0] or None),
            remedy=(
                "Add /Contents naming the destination. 'Hyperlink' repeats what "
                "the Link tag already conveys and is not a description."
            ),
        )


@rule(
    RuleMetadata(
        condition="30-002",
        checkpoint_name="XObjects",
        summary="A page does not declare structural tab order",
        clause="7.18.3",
        wcag=("2.4.3",),
        default_severity=Severity.WARNING,
    )
)
def pages_declare_tab_order(context: DocumentContext) -> Iterator[Finding]:
    """Tab order must follow the structure, not the order annotations were added."""
    for index, page in enumerate(context.pdf.pages):
        annots = page.obj.get("/Annots")
        if not isinstance(annots, pikepdf.Array) or len(annots) == 0:
            continue
        tabs = page.obj.get("/Tabs")
        if tabs is None or str(tabs) != "/S":
            yield Finding(
                condition="30-002",
                message=(f"Page {index + 1} carries annotations but does not set /Tabs to /S."),
                severity=Severity.WARNING,
                location=Location(page=index),
                remedy="Set /Tabs to /S so keyboard navigation follows the structure order.",
            )
