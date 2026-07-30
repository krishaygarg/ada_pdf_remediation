"""Rules covering form fields and interactive controls.

Matterhorn checkpoint 27 (Forms).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import cast

import pikepdf

from ..context import DocumentContext
from ..model import Finding, Location, RuleMetadata
from ..registry import rule

_VALID_FIELD_TYPES = frozenset({"/Btn", "/Tx", "/Ch", "/Sig"})


@rule(
    RuleMetadata(
        condition="27-001",
        checkpoint_name="Forms",
        summary="A form field is not reachable from the structure tree",
        clause="7.19.1",
        wcag=("1.3.1", "4.1.2"),
    )
)
def form_fields_are_in_structure_tree(context: DocumentContext) -> Iterator[Finding]:
    """Form fields must be represented in the logical structure tree."""
    if context.root.get("/StructTreeRoot") is None:
        return

    acroform = context.root.get("/AcroForm")
    if not isinstance(acroform, pikepdf.Dictionary):
        return

    fields = acroform.get("/Fields")
    if not isinstance(fields, pikepdf.Array):
        return

    referenced = context.annotation_objgens_in_struct_tree
    field_items: Iterable[pikepdf.Object] = cast(Iterable[pikepdf.Object], fields)
    for index, field_obj in enumerate(field_items):
        if not isinstance(field_obj, pikepdf.Dictionary):
            continue
        objgen = field_obj.objgen
        if objgen != (0, 0) and objgen not in referenced:
            t_name = field_obj.get("/T")
            field_name = str(t_name) if t_name is not None else f"Field_{index + 1}"
            yield Finding(
                condition="27-001",
                message=f"Form field {field_name!r} is not referenced in the structure tree.",
                location=Location(object_number=objgen[0] or None),
                remedy="Include a /Form structure element or OBJR referencing the form field widget.",
            )


@rule(
    RuleMetadata(
        condition="27-002",
        checkpoint_name="Forms",
        summary="A form field has no alternate description or tooltip",
        clause="7.19.1",
        wcag=("1.3.1", "4.1.2"),
    )
)
def form_fields_have_tooltips(context: DocumentContext) -> Iterator[Finding]:
    """ISO 14289-1 7.19.1 requires form fields to declare a tooltip in /TU."""
    acroform = context.root.get("/AcroForm")
    if not isinstance(acroform, pikepdf.Dictionary):
        return

    fields = acroform.get("/Fields")
    if not isinstance(fields, pikepdf.Array):
        return

    field_items: Iterable[pikepdf.Object] = cast(Iterable[pikepdf.Object], fields)
    for index, field_obj in enumerate(field_items):
        if not isinstance(field_obj, pikepdf.Dictionary):
            continue
        tu = field_obj.get("/TU")
        if tu is None or not str(tu).strip():
            t_name = field_obj.get("/T")
            field_name = str(t_name) if t_name is not None else f"Field_{index + 1}"
            yield Finding(
                condition="27-002",
                message=f"Form field {field_name!r} has no /TU tooltip/alternate description.",
                location=Location(object_number=field_obj.objgen[0] or None),
                remedy="Add a /TU entry carrying a clear, human-readable tooltip for screen readers.",
            )


@rule(
    RuleMetadata(
        condition="27-003",
        checkpoint_name="Forms",
        summary="A form field declares an unrecognized or missing field type",
        clause="7.19.1",
        wcag=("4.1.2",),
    )
)
def form_field_types_are_valid(context: DocumentContext) -> Iterator[Finding]:
    acroform = context.root.get("/AcroForm")
    if not isinstance(acroform, pikepdf.Dictionary):
        return

    fields = acroform.get("/Fields")
    if not isinstance(fields, pikepdf.Array):
        return

    field_items: Iterable[pikepdf.Object] = cast(Iterable[pikepdf.Object], fields)
    for index, field_obj in enumerate(field_items):
        if not isinstance(field_obj, pikepdf.Dictionary):
            continue
        ft_obj = field_obj.get("/FT")
        ft = str(ft_obj) if ft_obj is not None else ""
        if not ft or ft not in _VALID_FIELD_TYPES:
            t_name = field_obj.get("/T")
            field_name = str(t_name) if t_name is not None else f"Field_{index + 1}"
            yield Finding(
                condition="27-003",
                message=f"Form field {field_name!r} declares an invalid or missing /FT type: {ft!r}.",
                location=Location(object_number=field_obj.objgen[0] or None),
                remedy="Set /FT to one of /Btn (button), /Tx (text), /Ch (choice), or /Sig (signature).",
            )
