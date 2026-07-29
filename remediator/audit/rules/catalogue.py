"""Rules covering the document catalogue: metadata, language and mark info.

Matterhorn checkpoints 06 (Metadata), 07 (Dictionary) and 11 (Declared natural
language).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pikepdf

from ..context import DocumentContext
from ..model import Finding, Location, RuleMetadata
from ..registry import rule

#: ISO 14289-1 clause 5. The conventional prefix is "pdfuaid" but the URI path
#: segment is "pdfua"; confusing the two produces a document no conforming
#: validator recognises as PDF/UA.
PDFUA_ID_NAMESPACE = "http://www.aiim.org/pdfua/ns/id/"
INCORRECT_PDFUA_NAMESPACE = "http://www.aiim.org/pdfuaid/ns/id/"

#: BCP 47 language tag, restricted to the shape ISO 14289-1 requires.
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")


@rule(
    RuleMetadata(
        condition="06-001",
        checkpoint_name="Metadata",
        summary="The document catalogue has no XMP metadata stream",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def metadata_stream_present(context: DocumentContext) -> Iterator[Finding]:
    if "/Metadata" not in context.root:
        yield Finding(
            condition="06-001",
            message="The document catalogue has no /Metadata stream.",
            remedy="Attach an XMP packet carrying the title and the PDF/UA identifier.",
        )


@rule(
    RuleMetadata(
        condition="06-002",
        checkpoint_name="Metadata",
        summary="The XMP metadata does not declare a document title",
        clause="7.1",
        wcag=("2.4.2",),
    )
)
def metadata_declares_title(context: DocumentContext) -> Iterator[Finding]:
    text = context.metadata_text
    if not text:
        return
    if "dc:title" not in text:
        yield Finding(
            condition="06-002",
            message="The XMP metadata does not declare dc:title.",
            remedy="Add a dc:title entry describing the document.",
        )


@rule(
    RuleMetadata(
        condition="06-004",
        checkpoint_name="Metadata",
        summary="The PDF/UA identifier is missing or uses the wrong namespace",
        clause="5",
        wcag=("4.1.2",),
    )
)
def pdfua_identifier_present(context: DocumentContext) -> Iterator[Finding]:
    text = context.metadata_text
    if not text:
        return

    if INCORRECT_PDFUA_NAMESPACE in text and PDFUA_ID_NAMESPACE not in text:
        # Worth calling out separately: the packet looks right at a glance and
        # some checkers score it as compliant, but a conforming validator
        # cannot identify the file as PDF/UA at all.
        yield Finding(
            condition="06-004",
            message=(
                "The PDF/UA identifier uses the namespace "
                f"{INCORRECT_PDFUA_NAMESPACE}, which is not the one ISO 14289-1 "
                "clause 5 defines."
            ),
            remedy=(
                f"Use {PDFUA_ID_NAMESPACE}. The conventional prefix is 'pdfuaid' "
                "but the URI path segment is 'pdfua'."
            ),
        )
        return

    if PDFUA_ID_NAMESPACE not in text:
        yield Finding(
            condition="06-004",
            message="The XMP metadata does not carry the PDF/UA identifier.",
            remedy=f"Add a pdfuaid:part property in the namespace {PDFUA_ID_NAMESPACE}.",
        )
        return

    if not re.search(r"<pdfuaid:part>\s*\d+\s*</pdfuaid:part>", text) and not re.search(
        r'pdfuaid:part\s*=\s*"\d+"', text
    ):
        yield Finding(
            condition="06-004",
            message="The PDF/UA identification schema is present but declares no part number.",
            remedy="Set pdfuaid:part to 1 for PDF/UA-1.",
        )


@rule(
    RuleMetadata(
        condition="06-003",
        checkpoint_name="Metadata",
        summary="The viewer is not told to display the document title",
        clause="7.1",
        wcag=("2.4.2",),
    )
)
def display_doc_title_enabled(context: DocumentContext) -> Iterator[Finding]:
    prefs = context.root.get("/ViewerPreferences")
    if not isinstance(prefs, pikepdf.Dictionary) or "/DisplayDocTitle" not in prefs:
        yield Finding(
            condition="06-003",
            message="/ViewerPreferences does not set /DisplayDocTitle.",
            remedy=(
                "Set /DisplayDocTitle to true so the reader shows the document "
                "title rather than the file name."
            ),
        )
        return
    if not bool(prefs["/DisplayDocTitle"]):
        yield Finding(
            condition="06-003",
            message="/DisplayDocTitle is set to false.",
            remedy="Set /DisplayDocTitle to true.",
        )


@rule(
    RuleMetadata(
        condition="07-001",
        checkpoint_name="Dictionary",
        summary="The document is not declared as tagged",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def marked_as_tagged(context: DocumentContext) -> Iterator[Finding]:
    mark_info = context.root.get("/MarkInfo")
    if not isinstance(mark_info, pikepdf.Dictionary):
        yield Finding(
            condition="07-001",
            message="The document catalogue has no /MarkInfo dictionary.",
            remedy="Add /MarkInfo with /Marked set to true.",
        )
        return
    if not bool(mark_info.get("/Marked", False)):
        yield Finding(
            condition="07-001",
            message="/MarkInfo does not set /Marked to true.",
            remedy="Set /MarkInfo /Marked to true.",
        )


@rule(
    RuleMetadata(
        condition="07-002",
        checkpoint_name="Dictionary",
        summary="The tagging is flagged as unreliable through /Suspects",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def suspects_not_set(context: DocumentContext) -> Iterator[Finding]:
    mark_info = context.root.get("/MarkInfo")
    if isinstance(mark_info, pikepdf.Dictionary) and bool(mark_info.get("/Suspects", False)):
        yield Finding(
            condition="07-002",
            message="/MarkInfo /Suspects is true, which declares the tagging unreliable.",
            remedy="Correct the tagging and remove /Suspects, or set it to false.",
        )


@rule(
    RuleMetadata(
        condition="11-001",
        checkpoint_name="Declared natural language",
        summary="The document does not declare a default language",
        clause="7.2",
        wcag=("3.1.1",),
    )
)
def catalogue_declares_language(context: DocumentContext) -> Iterator[Finding]:
    lang = context.root.get("/Lang")
    if lang is None or not str(lang).strip():
        yield Finding(
            condition="11-001",
            message="The document catalogue does not declare /Lang.",
            remedy=(
                "Set /Lang to the document's primary language as a BCP 47 tag, "
                "for example en-US. A screen reader otherwise guesses the "
                "pronunciation rules."
            ),
        )


@rule(
    RuleMetadata(
        condition="11-006",
        checkpoint_name="Declared natural language",
        summary="A declared language is not a well formed language tag",
        clause="7.2",
        wcag=("3.1.1", "3.1.2"),
    )
)
def language_tags_are_well_formed(context: DocumentContext) -> Iterator[Finding]:
    lang = context.root.get("/Lang")
    if lang is not None:
        value = str(lang).strip()
        if value and not _LANGUAGE_TAG.match(value):
            yield Finding(
                condition="11-006",
                message=f"The catalogue declares /Lang as {value!r}, which is not a BCP 47 tag.",
                remedy="Use a tag such as en, en-US or fr-CA.",
            )

    for node in context.struct_nodes:
        element_lang = node.element.get("/Lang")
        if element_lang is None:
            continue
        value = str(element_lang).strip()
        if value and not _LANGUAGE_TAG.match(value):
            yield Finding(
                condition="11-006",
                message=(
                    f"A {node.tag} element declares /Lang as {value!r}, which is not a BCP 47 tag."
                ),
                location=node.location(),
                remedy="Use a tag such as en, en-US or fr-CA.",
            )


@rule(
    RuleMetadata(
        condition="01-003",
        checkpoint_name="Real content",
        summary="The document has no logical structure",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def structure_tree_present(context: DocumentContext) -> Iterator[Finding]:
    struct_root = context.root.get("/StructTreeRoot")
    if struct_root is None:
        yield Finding(
            condition="01-003",
            message="The document has no /StructTreeRoot, so it carries no logical structure.",
            remedy="Tag the document. Without a structure tree nothing else can be assessed.",
        )
        return
    if "/ParentTree" not in struct_root:
        yield Finding(
            condition="01-003",
            message="/StructTreeRoot has no /ParentTree, so marked content cannot be resolved.",
            remedy="Build a parent tree mapping each page and annotation key to its elements.",
        )
    if not context.struct_roots:
        yield Finding(
            condition="01-003",
            message="The structure tree contains no elements.",
            remedy="Populate /StructTreeRoot /K with the document's structure.",
        )


@rule(
    RuleMetadata(
        condition="02-001",
        checkpoint_name="Role mapping",
        summary="A non-standard structure type is not mapped to a standard one",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def non_standard_types_are_mapped(context: DocumentContext) -> Iterator[Finding]:
    from ..context import STANDARD_STRUCTURE_TYPES

    reported: set[str] = set()
    for node in context.struct_nodes:
        if node.tag in STANDARD_STRUCTURE_TYPES or node.tag in reported:
            continue
        if node.role in STANDARD_STRUCTURE_TYPES:
            continue
        reported.add(node.tag)
        yield Finding(
            condition="02-001",
            message=(
                f"The structure type {node.tag!r} is not a standard type and the "
                "role map does not resolve it to one."
            ),
            location=node.location(),
            remedy=f"Add a /RoleMap entry mapping {node.tag} to a standard structure type.",
        )


@rule(
    RuleMetadata(
        condition="02-003",
        checkpoint_name="Role mapping",
        summary="The role map contains a circular mapping",
        clause="7.1",
        wcag=("1.3.1",),
    )
)
def role_map_has_no_cycles(context: DocumentContext) -> Iterator[Finding]:
    role_map = context.role_map
    for start in role_map:
        seen: set[str] = set()
        current = start
        while current in role_map and current not in seen:
            seen.add(current)
            current = role_map[current]
        if current in seen:
            yield Finding(
                condition="02-003",
                message=f"The role map entry for {start!r} resolves in a cycle.",
                location=Location(),
                remedy="Map each custom type to a standard structure type directly.",
            )
            return
