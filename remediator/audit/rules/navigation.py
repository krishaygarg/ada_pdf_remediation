"""Rules covering document navigation, outlines and tables of contents.

Matterhorn checkpoints 05 (Bookmarks) and 20 (Table of Contents).
"""

from __future__ import annotations

from collections.abc import Iterator

import pikepdf

from ..context import DocumentContext, StructNode
from ..model import Finding, RuleMetadata, Severity
from ..registry import rule


@rule(
    RuleMetadata(
        condition="05-001",
        checkpoint_name="Bookmarks",
        summary="A long document or one with headings has no outline / bookmarks tree",
        clause="7.1",
        wcag=("2.4.5",),
        default_severity=Severity.WARNING,
    )
)
def document_has_outlines_tree(context: DocumentContext) -> Iterator[Finding]:
    """ISO 14289-1 7.1 requires documents > 21 pages to carry bookmarks."""
    num_pages = len(context.pdf.pages)
    has_headings = len(context.nodes_with_role("H1", "H2", "H3", "H4", "H5", "H6", "H")) > 2

    if num_pages > 21 or has_headings:
        outlines = context.root.get("/Outlines")
        if not isinstance(outlines, pikepdf.Dictionary) or "/First" not in outlines:
            yield Finding(
                condition="05-001",
                message=(
                    f"The document has {num_pages} pages and section headings "
                    "but carries no /Outlines bookmark tree."
                ),
                severity=Severity.WARNING,
                remedy="Build a document outline tree (/Outlines) reflecting the section headings.",
            )


@rule(
    RuleMetadata(
        condition="20-001",
        checkpoint_name="Table of Contents",
        summary="A TOC element does not contain TOCI children",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def toc_elements_contain_toci(context: DocumentContext) -> Iterator[Finding]:
    """A Table of Contents structure element must contain TOCI items."""
    for toc in context.nodes_with_role("TOC"):
        has_toci = any(child.role == "TOCI" for child in _descendants(toc))
        if not has_toci:
            yield Finding(
                condition="20-001",
                message="A TOC structure element contains no TOCI (TOC Item) children.",
                location=toc.location(),
                remedy="Tag each entry inside the Table of Contents as a TOCI element.",
            )


@rule(
    RuleMetadata(
        condition="20-002",
        checkpoint_name="Table of Contents",
        summary="A TOCI item is not inside a TOC structure element",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def toci_items_are_inside_toc(context: DocumentContext) -> Iterator[Finding]:
    for toci in context.nodes_with_role("TOCI"):
        parent = toci.parent
        while parent is not None and parent.role not in ("TOC", "TOCI"):
            parent = parent.parent
        if parent is None:
            yield Finding(
                condition="20-002",
                message="A TOCI structure item is not enclosed within a TOC structure element.",
                location=toci.location(),
                remedy="Wrap all TOCI items inside a TOC container element.",
            )


def _descendants(node: StructNode) -> Iterator[StructNode]:
    for child in node.children:
        yield child
        yield from _descendants(child)
