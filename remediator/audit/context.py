"""Shared document state handed to every rule.

The previous auditor opened the file once per check, seven times in total, and
re-walked the structure tree whenever it needed it. Rules here receive one
already-parsed context with the expensive traversals computed once and cached,
so adding a rule costs a predicate rather than another parse of the document.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pikepdf

from .model import Location

#: Structure types defined by ISO 32000-1 14.8.4. Anything outside this set has
#: to be mapped to a standard type through the role map to be meaningful.
STANDARD_STRUCTURE_TYPES = frozenset(
    {
        "Document",
        "Part",
        "Art",
        "Sect",
        "Div",
        "BlockQuote",
        "Caption",
        "TOC",
        "TOCI",
        "Index",
        "NonStruct",
        "Private",
        "P",
        "H",
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
        "H6",
        "L",
        "LI",
        "Lbl",
        "LBody",
        "Table",
        "TR",
        "TH",
        "TD",
        "THead",
        "TBody",
        "TFoot",
        "Span",
        "Quote",
        "Note",
        "Reference",
        "BibEntry",
        "Code",
        "Link",
        "Annot",
        "Ruby",
        "RB",
        "RT",
        "RP",
        "Warichu",
        "WT",
        "WP",
        "Figure",
        "Formula",
        "Form",
    }
)

#: Structure types that carry no meaning of their own and are transparent when
#: deciding whether an element is nested correctly.
GROUPING_TYPES = frozenset({"Document", "Part", "Art", "Sect", "Div", "NonStruct"})


@dataclass(slots=True)
class StructNode:
    """One structure element, with the ancestry a rule needs to judge nesting."""

    element: pikepdf.Object
    tag: str
    """The element's own /S value, with the leading slash removed."""

    role: str
    """The tag resolved through the document's role map."""

    parent: StructNode | None
    depth: int
    page_index: int | None
    children: list[StructNode] = field(default_factory=list)

    @property
    def path(self) -> str:
        """Slash separated ancestry, for pinpointing the element in a report."""
        names: list[str] = []
        node: StructNode | None = self
        while node is not None:
            names.append(node.tag)
            node = node.parent
        return "/" + "/".join(reversed(names))

    @property
    def object_number(self) -> int | None:
        number = self.element.objgen[0]
        return number or None

    def location(self) -> Location:
        return Location(
            page=self.page_index,
            object_number=self.object_number,
            struct_path=self.path,
        )

    def ancestors(self) -> Iterator[StructNode]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def nearest_meaningful_ancestor(self) -> StructNode | None:
        """The closest ancestor that is not a pure grouping element."""
        for node in self.ancestors():
            if node.role not in GROUPING_TYPES:
                return node
        return None


class DocumentContext:
    """Everything the rules need about one document, computed once."""

    def __init__(self, pdf: pikepdf.Pdf, path: Path | str) -> None:
        self.pdf = pdf
        self.path = Path(path)

    # -- catalogue ---------------------------------------------------------

    @property
    def root(self) -> pikepdf.Object:
        return self.pdf.Root

    @cached_property
    def page_index_by_objgen(self) -> dict[tuple[int, int], int]:
        return {page.obj.objgen: index for index, page in enumerate(self.pdf.pages)}

    @cached_property
    def metadata_text(self) -> str:
        """The XMP packet as text, or an empty string when there is none."""
        try:
            stream = self.root.get("/Metadata")
            if stream is None:
                return ""
            return bytes(stream.read_bytes()).decode("utf-8", errors="replace")
        except Exception:
            return ""

    @cached_property
    def role_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        try:
            struct_root = self.root.get("/StructTreeRoot")
            if struct_root is None:
                return mapping
            raw = struct_root.get("/RoleMap")
            if not isinstance(raw, pikepdf.Dictionary):
                return mapping
            for key, value in raw.items():
                mapping[str(key).lstrip("/")] = str(value).lstrip("/")
        except Exception:
            pass
        return mapping

    def resolve_role(self, tag: str, _seen: frozenset[str] = frozenset()) -> str:
        """Follow the role map to a standard type, stopping on a cycle.

        A self-referential or circular role map is itself a failure condition
        (checkpoint 02), so this returns the last tag reached rather than
        looping.
        """
        if tag in STANDARD_STRUCTURE_TYPES or tag not in self.role_map or tag in _seen:
            return tag
        return self.resolve_role(self.role_map[tag], _seen | {tag})

    # -- structure tree ----------------------------------------------------

    @cached_property
    def struct_roots(self) -> list[StructNode]:
        """Top level structure nodes, or an empty list when there is no tree."""
        struct_root = self.root.get("/StructTreeRoot")
        if struct_root is None:
            return []

        visited: set[tuple[int, int]] = set()

        def build(
            element: pikepdf.Object, parent: StructNode | None, depth: int
        ) -> StructNode | None:
            if not isinstance(element, pikepdf.Dictionary):
                return None
            if "/S" not in element:
                return None
            objgen = element.objgen
            if objgen != (0, 0):
                if objgen in visited:
                    return None
                visited.add(objgen)

            tag = str(element.get("/S", "")).lstrip("/")
            page_index = parent.page_index if parent else None
            page_ref = element.get("/Pg")
            if page_ref is not None:
                page_index = self.page_index_by_objgen.get(page_ref.objgen, page_index)

            node = StructNode(
                element=element,
                tag=tag,
                role=self.resolve_role(tag),
                parent=parent,
                depth=depth,
                page_index=page_index,
            )

            kids = element.get("/K")
            for kid in self._iter_kids(kids):
                child = build(kid, node, depth + 1)
                if child is not None:
                    node.children.append(child)
            return node

        roots: list[StructNode] = []
        for kid in self._iter_kids(struct_root.get("/K")):
            node = build(kid, None, 0)
            if node is not None:
                roots.append(node)
        return roots

    @staticmethod
    def _iter_kids(kids: pikepdf.Object | None) -> Iterator[pikepdf.Object]:
        if kids is None:
            return
        if isinstance(kids, pikepdf.Array):
            yield from kids
        else:
            yield kids

    @cached_property
    def struct_nodes(self) -> list[StructNode]:
        """Every structure node, in document order."""
        ordered: list[StructNode] = []

        def walk(node: StructNode) -> None:
            ordered.append(node)
            for child in node.children:
                walk(child)

        for root in self.struct_roots:
            walk(root)
        return ordered

    def nodes_with_role(self, *roles: str) -> list[StructNode]:
        wanted = set(roles)
        return [node for node in self.struct_nodes if node.role in wanted]

    # -- fonts and annotations --------------------------------------------

    @cached_property
    def fonts(self) -> list[tuple[pikepdf.Object, int | None]]:
        """Every font dictionary reachable from a page, with its object number."""
        seen: set[tuple[int, int]] = set()
        found: list[tuple[pikepdf.Object, int | None]] = []
        for page in self.pdf.pages:
            resources = page.obj.get("/Resources")
            if not isinstance(resources, pikepdf.Dictionary):
                continue
            fonts = resources.get("/Font")
            if not isinstance(fonts, pikepdf.Dictionary):
                continue
            for _name, font in fonts.items():
                if not isinstance(font, pikepdf.Dictionary):
                    continue
                objgen = font.objgen
                if objgen != (0, 0):
                    if objgen in seen:
                        continue
                    seen.add(objgen)
                found.append((font, objgen[0] or None))
        return found

    @cached_property
    def annotations(self) -> list[tuple[pikepdf.Object, int]]:
        """Every annotation paired with the index of the page carrying it."""
        found: list[tuple[pikepdf.Object, int]] = []
        for index, page in enumerate(self.pdf.pages):
            annots = page.obj.get("/Annots")
            if not isinstance(annots, pikepdf.Array):
                continue
            for annot in annots:
                if isinstance(annot, pikepdf.Dictionary):
                    found.append((annot, index))
        return found

    @cached_property
    def annotation_objgens_in_struct_tree(self) -> set[tuple[int, int]]:
        """Annotations reachable through an object reference in the tree."""
        referenced: set[tuple[int, int]] = set()
        for node in self.struct_nodes:
            for kid in self._iter_kids(node.element.get("/K")):
                if not isinstance(kid, pikepdf.Dictionary):
                    continue
                if str(kid.get("/Type", "")) != "/OBJR":
                    continue
                target = kid.get("/Obj")
                if target is not None:
                    referenced.add(target.objgen)
        return referenced


__all__ = ["GROUPING_TYPES", "STANDARD_STRUCTURE_TYPES", "DocumentContext", "StructNode"]
