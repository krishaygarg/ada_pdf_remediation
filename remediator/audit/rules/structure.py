"""Rules covering structure element semantics.

Matterhorn checkpoints 09 (Appropriate tags), 13 (Graphics), 14 (Headings),
15 (Tables), 16 (Lists), 17 (Mathematical expressions) and 19 (Notes and
references).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pikepdf

from ..context import DocumentContext, StructNode
from ..model import Determination, Finding, RuleMetadata, Severity
from ..registry import rule

#: Alternate text that is present but says nothing useful. Matching these is a
#: warning rather than an error: the file conforms, but a reader gains nothing.
_UNINFORMATIVE_ALT = re.compile(
    r"^\s*(image|figure|picture|graphic|photo|chart|diagram|logo|icon|untitled|"
    r"placeholder|alt(\s*text)?|todo|tbd|n/?a|\d+)?\s*$",
    re.IGNORECASE,
)

_FILENAME_LIKE = re.compile(r"\.(png|jpe?g|gif|bmp|tiff?|svg|emf|wmf|eps|pdf)\s*$", re.IGNORECASE)


def _alternate_text(node: StructNode) -> str | None:
    """The element's alternate description, from /Alt or /ActualText."""
    for key in ("/Alt", "/ActualText"):
        value = node.element.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


@rule(
    RuleMetadata(
        condition="13-004",
        checkpoint_name="Graphics",
        summary="A figure has no alternate description",
        clause="7.3",
        wcag=("1.1.1",),
    )
)
def figures_have_alternate_text(context: DocumentContext) -> Iterator[Finding]:
    for node in context.nodes_with_role("Figure"):
        if _alternate_text(node) is None:
            yield Finding(
                condition="13-004",
                message="A Figure element has neither /Alt nor /ActualText.",
                location=node.location(),
                remedy=(
                    "Describe what the figure conveys. If it is decorative, mark "
                    "it as an artifact instead of tagging it as a figure."
                ),
            )


@rule(
    RuleMetadata(
        condition="13-005",
        checkpoint_name="Graphics",
        summary="A figure's alternate description carries no information",
        clause="7.3",
        wcag=("1.1.1",),
        determination=Determination.HUMAN,
        default_severity=Severity.WARNING,
    )
)
def figure_alternate_text_is_informative(context: DocumentContext) -> Iterator[Finding]:
    """Alternate text that repeats the word 'image' conveys nothing.

    Whether a description is adequate is a human judgement, so this reports the
    cases that are certainly inadequate and leaves the rest alone.
    """
    for node in context.nodes_with_role("Figure"):
        text = _alternate_text(node)
        if text is None:
            continue
        if _UNINFORMATIVE_ALT.match(text):
            yield Finding(
                condition="13-005",
                message=f"A Figure is described only as {text!r}, which conveys nothing.",
                severity=Severity.WARNING,
                location=node.location(),
                remedy="Describe the content or purpose of the figure.",
            )
        elif _FILENAME_LIKE.search(text):
            yield Finding(
                condition="13-005",
                message=f"A Figure's description {text!r} looks like a file name.",
                severity=Severity.WARNING,
                location=node.location(),
                remedy="Replace the file name with a description of the content.",
            )


@rule(
    RuleMetadata(
        condition="13-008",
        checkpoint_name="Graphics",
        summary="A figure does not declare a bounding box",
        clause="7.3",
        wcag=("1.3.1",),
        default_severity=Severity.WARNING,
    )
)
def figures_declare_a_bounding_box(context: DocumentContext) -> Iterator[Finding]:
    """A /BBox lets a reader locate and magnify the figure on the page."""
    for node in context.nodes_with_role("Figure"):
        attributes = node.element.get("/A")
        candidates = []
        if isinstance(attributes, pikepdf.Array):
            candidates = list(attributes)
        elif isinstance(attributes, pikepdf.Dictionary):
            candidates = [attributes]

        has_layout_bbox = any(
            isinstance(entry, pikepdf.Dictionary)
            and str(entry.get("/O", "")) == "/Layout"
            and "/BBox" in entry
            for entry in candidates
        )
        if has_layout_bbox:
            continue

        if "/BBox" in node.element:
            yield Finding(
                condition="13-008",
                message=(
                    "A Figure carries /BBox directly on the structure element "
                    "rather than inside a /Layout attribute dictionary."
                ),
                severity=Severity.WARNING,
                location=node.location(),
                remedy="Move /BBox into /A << /O /Layout /BBox [...] >>.",
            )
        else:
            yield Finding(
                condition="13-008",
                message="A Figure declares no bounding box.",
                severity=Severity.WARNING,
                location=node.location(),
                remedy="Add /A << /O /Layout /BBox [x0 y0 x1 y1] >> giving the figure's extent.",
            )


@rule(
    RuleMetadata(
        condition="17-002",
        checkpoint_name="Mathematical expressions",
        summary="A formula has no alternate description",
        clause="7.9",
        wcag=("1.1.1",),
    )
)
def formulas_have_alternate_text(context: DocumentContext) -> Iterator[Finding]:
    for node in context.nodes_with_role("Formula"):
        if _alternate_text(node) is None:
            yield Finding(
                condition="17-002",
                message="A Formula element has neither /Alt nor /ActualText.",
                location=node.location(),
                remedy=(
                    "Provide the expression in words or as MathML. A rendered "
                    "equation is unreadable to a screen reader without it."
                ),
            )


@rule(
    RuleMetadata(
        condition="14-002",
        checkpoint_name="Headings",
        summary="A heading level is skipped",
        clause="7.4",
        wcag=("1.3.1", "2.4.6"),
    )
)
def numbered_headings_do_not_skip_levels(context: DocumentContext) -> Iterator[Finding]:
    """H1 followed by H3 leaves a reader unable to tell what was missed.

    ISO 14289-1 7.4.2 requires numbered headings to descend without gaps.
    """
    pattern = re.compile(r"^H([1-6])$")
    previous: int | None = None
    for node in context.struct_nodes:
        match = pattern.match(node.role)
        if match is None:
            continue
        level = int(match.group(1))
        if previous is not None and level > previous + 1:
            yield Finding(
                condition="14-002",
                message=(
                    f"A level {level} heading follows a level {previous} heading, "
                    f"skipping level {previous + 1}."
                ),
                location=node.location(),
                remedy=f"Use H{previous + 1}, or restructure the section hierarchy.",
            )
        previous = level


@rule(
    RuleMetadata(
        condition="14-003",
        checkpoint_name="Headings",
        summary="The first heading in the document is not level one",
        clause="7.4",
        wcag=("1.3.1",),
        default_severity=Severity.WARNING,
    )
)
def first_heading_is_level_one(context: DocumentContext) -> Iterator[Finding]:
    pattern = re.compile(r"^H([1-6])$")
    for node in context.struct_nodes:
        match = pattern.match(node.role)
        if match is None:
            continue
        level = int(match.group(1))
        if level != 1:
            yield Finding(
                condition="14-003",
                message=f"The first heading in the document is level {level}, not level 1.",
                severity=Severity.WARNING,
                location=node.location(),
                remedy="Start the heading hierarchy at H1.",
            )
        return


@rule(
    RuleMetadata(
        condition="15-003",
        checkpoint_name="Tables",
        summary="A table has no header cells",
        clause="7.5",
        wcag=("1.3.1",),
    )
)
def tables_have_header_cells(context: DocumentContext) -> Iterator[Finding]:
    """Without TH cells a screen reader cannot announce what a value means."""
    for table in context.nodes_with_role("Table"):
        has_header = any(descendant.role == "TH" for descendant in _descendants(table))
        if not has_header:
            yield Finding(
                condition="15-003",
                message="A Table contains no TH cells, so its data cells have no headers.",
                location=table.location(),
                remedy="Tag the header row or column cells as TH.",
            )


@rule(
    RuleMetadata(
        condition="15-005",
        checkpoint_name="Tables",
        summary="A header cell does not declare its scope",
        clause="7.5",
        wcag=("1.3.1",),
        default_severity=Severity.WARNING,
    )
)
def header_cells_declare_scope(context: DocumentContext) -> Iterator[Finding]:
    for node in context.nodes_with_role("TH"):
        attributes = node.element.get("/A")
        candidates: list[pikepdf.Object] = []
        if isinstance(attributes, pikepdf.Array):
            candidates = list(attributes)
        elif isinstance(attributes, pikepdf.Dictionary):
            candidates = [attributes]

        has_scope = any(
            isinstance(entry, pikepdf.Dictionary) and "/Scope" in entry for entry in candidates
        )
        if not has_scope:
            yield Finding(
                condition="15-005",
                message="A TH cell does not declare /Scope.",
                severity=Severity.WARNING,
                location=node.location(),
                remedy=(
                    "Add /A << /O /Table /Scope /Row >> or /Column so a reader "
                    "knows which cells the header governs."
                ),
            )


@rule(
    RuleMetadata(
        condition="15-006",
        checkpoint_name="Tables",
        summary="Table rows and cells are nested incorrectly",
        clause="7.5",
        wcag=("1.3.1",),
    )
)
def table_cells_are_nested_in_rows(context: DocumentContext) -> Iterator[Finding]:
    for node in context.nodes_with_role("TD", "TH"):
        parent = node.parent
        if parent is None or parent.role != "TR":
            yield Finding(
                condition="15-006",
                message=(
                    f"A {node.role} cell has parent "
                    f"{parent.role if parent else 'none'} rather than TR."
                ),
                location=node.location(),
                remedy="Place every TD and TH inside a TR.",
            )

    for node in context.nodes_with_role("TR"):
        parent = node.parent
        allowed = {"Table", "THead", "TBody", "TFoot"}
        if parent is None or parent.role not in allowed:
            yield Finding(
                condition="15-006",
                message=(
                    f"A TR has parent {parent.role if parent else 'none'} rather "
                    "than Table, THead, TBody or TFoot."
                ),
                location=node.location(),
                remedy="Place every TR inside a Table or one of its row groups.",
            )


@rule(
    RuleMetadata(
        condition="16-001",
        checkpoint_name="Lists",
        summary="List items and their parts are nested incorrectly",
        clause="7.6",
        wcag=("1.3.1",),
    )
)
def list_structure_is_well_formed(context: DocumentContext) -> Iterator[Finding]:
    for node in context.nodes_with_role("LI"):
        parent = node.parent
        if parent is None or parent.role != "L":
            yield Finding(
                condition="16-001",
                message=(f"An LI has parent {parent.role if parent else 'none'} rather than L."),
                location=node.location(),
                remedy="Place every LI inside an L element.",
            )

    for node in context.nodes_with_role("Lbl", "LBody"):
        parent = node.parent
        # Lbl is also permitted inside a numbered heading structure in some
        # producers, but inside a list it must belong to an LI.
        if parent is not None and parent.role == "L":
            yield Finding(
                condition="16-001",
                message=f"A {node.role} is a direct child of L rather than of LI.",
                location=node.location(),
                remedy="Wrap the label and body in an LI.",
            )


@rule(
    RuleMetadata(
        condition="19-003",
        checkpoint_name="Notes and references",
        summary="A note has no identifier",
        clause="7.9",
        wcag=("1.3.1",),
        default_severity=Severity.WARNING,
    )
)
def notes_have_identifiers(context: DocumentContext) -> Iterator[Finding]:
    """A Note needs an /ID so a reference elsewhere can point at it."""
    for node in context.nodes_with_role("Note"):
        if "/ID" not in node.element:
            yield Finding(
                condition="19-003",
                message="A Note element has no /ID, so nothing can reference it.",
                severity=Severity.WARNING,
                location=node.location(),
                remedy="Give the Note an /ID and reference it from the citation.",
            )


@rule(
    RuleMetadata(
        condition="09-004",
        checkpoint_name="Appropriate tags",
        summary="A structure element that must contain content is empty",
        clause="7.1",
        wcag=("1.3.1",),
        default_severity=Severity.WARNING,
    )
)
def content_elements_are_not_empty(context: DocumentContext) -> Iterator[Finding]:
    """A paragraph tag with nothing inside adds noise to the reading order."""
    content_roles = {"P", "H1", "H2", "H3", "H4", "H5", "H6", "H", "Lbl", "LBody", "TD", "TH"}
    for node in context.struct_nodes:
        if node.role not in content_roles:
            continue
        if node.children:
            continue
        kids = node.element.get("/K")
        if kids is None or (isinstance(kids, pikepdf.Array) and len(kids) == 0):
            yield Finding(
                condition="09-004",
                message=f"A {node.tag} element contains no content.",
                severity=Severity.WARNING,
                location=node.location(),
                remedy="Remove the empty element or give it the content it should describe.",
            )


def _descendants(node: StructNode) -> Iterator[StructNode]:
    for child in node.children:
        yield child
        yield from _descendants(child)
