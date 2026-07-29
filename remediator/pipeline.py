import logging
import os
from datetime import datetime, timezone

import pdfplumber
import pikepdf

from .alttext import get_provider
from .content_filter import filter_page_content
from .figures import (
    DetectedFigure,
    build_figure_element,
    describe_figures,
    detect_vector_figures,
    is_meaningful_image,
)
from .font_patcher import recover_font_mapping
from .numbertree import build_number_tree
from .progress import ConsoleReporter, ProgressReporter, Stage, emit

#: Namespace URI of the PDF/UA identification schema, ISO 14289-1 clause 5.
#: The conventional prefix is "pdfuaid" but the URI path segment is "pdfua".
PDFUA_ID_NAMESPACE = "http://www.aiim.org/pdfua/ns/id/"

#: Malformed input is expected here, so the guards below continue rather than
#: abort. They log at debug level instead of discarding the reason outright: a
#: document this tool silently gave up on part of is exactly the case that is
#: impossible to diagnose afterwards from a clean-looking run.
_LOG = logging.getLogger(__name__)


def _describe_link_target(annot) -> str:
    """Return a human readable description of where a link annotation leads.

    Falls back to a generic phrase when the destination cannot be read, which
    still satisfies the requirement for a non-empty description while making it
    obvious in review that the link deserves a better one.
    """
    try:
        action = annot.get("/A")
        if isinstance(action, pikepdf.Dictionary):
            subtype = str(action.get("/S", ""))
            if subtype == "/URI":
                uri = str(action.get("/URI", "")).strip()
                if uri:
                    return f"Link to {uri}"
            elif subtype in ("/GoTo", "/GoToR"):
                return "Link to another location in this document"
            elif subtype == "/Launch":
                return "Link that opens an external file"
        if "/Dest" in annot:
            return "Link to another location in this document"
    except Exception:
        _LOG.debug("could not read a link annotation's destination", exc_info=True)
    return "Link"


def _apply_reading_order(
    strategy_name, document_elem, first_kid_index, text_boxes, page_idx, reporter
):
    """Reorder this page's entries in the document's logical tree.

    Two orderings coexist and only one of them is the reading order.

    The parent tree maps a page's key to an array indexed by marked-content
    identifier, so its order is fixed by the content stream and must not be
    touched. The document element's /K array is the logical sequence a screen
    reader follows, and reordering that changes the reading order while leaving
    both the content stream and the parent tree exactly as they were.

    Elements whose geometry could not be recovered keep their original relative
    position. A strategy given no coordinates has nothing to work from, and
    guessing would be worse than leaving them alone.
    """
    from .roeval import PageElement, get, validate_ordering

    kids = document_elem.K
    span = len(kids) - first_kid_index
    if span < 2:
        return

    positioned = []
    for offset in range(span):
        box = text_boxes[offset] if offset < len(text_boxes) else None
        if box is None:
            continue
        positioned.append(
            PageElement(
                id=offset,
                type=str(kids[first_kid_index + offset].get("/S", "/P")).lstrip("/"),
                bbox=(box.x0, box.top, box.x1, box.bottom),
                page_index=page_idx,
            )
        )

    if len(positioned) < 2:
        return

    try:
        ordered = get(strategy_name).sort(positioned)
        validate_ordering(positioned, ordered)
    except Exception as exc:
        emit(
            reporter,
            Stage.ANALYSING_PAGE,
            f"Reading order strategy {strategy_name!r} failed on page {page_idx + 1}; "
            f"keeping the stream order ({exc})",
        )
        return

    rank = {element.id: position for position, element in enumerate(ordered)}
    offsets = sorted(range(span), key=lambda offset: (rank.get(offset, offset), offset))
    reordered = [kids[first_kid_index + offset] for offset in offsets]
    for position, element in enumerate(reordered):
        kids[first_kid_index + position] = element


def _xml_escape(value: str) -> str:
    """Escape text for inclusion in an XMP character data section."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def remediate_single_pdf(
    input_path: str,
    output_path: str,
    *,
    undescribed_images: str = "figure",
    reading_order_strategy: str = "stream-order",
    progress: ProgressReporter | None = None,
):
    """Remediate a PDF towards PDF/UA-1 and WCAG conformance.

    Args:
        input_path: The document to read.
        output_path: Where to write the result. Must differ from the input.
        reading_order_strategy: Name of a registered reading order strategy.
            The default, "stream-order", keeps the content stream's own order,
            which is what this has always done and leaves output unchanged.

            Reordering only becomes useful once one of the algorithms in
            remediator.reading_order is implemented; see
            docs/planning/layout_reading_order_proposal.md. Wiring the call site
            now means that work switches on with a flag rather than needing the
            pipeline changed.
        progress: Receives structured events as the run proceeds. Defaults to
            printing them, which reproduces the previous console output. Pass
            a reporter to drive a progress bar, or NullReporter to stay silent.
        undescribed_images: What to do with an image that no provider could
            describe. ``"figure"``, the default, tags it as content and leaves
            the description missing, so the audit reports it and a person can
            supply one. ``"artifact"`` marks it decorative, which conforms but
            removes the image from the reading order entirely.

            The default deliberately produces a document that does not yet
            conform. The alternative was to hide every image behind an artifact
            tag, which conforms while making the image unreachable, or to write
            a placeholder such as "Image", which conforms while telling a reader
            nothing. Both trade a real reader's experience for a passing score.
    """
    if undescribed_images not in ("figure", "artifact"):
        raise ValueError(
            f"undescribed_images must be 'figure' or 'artifact', not {undescribed_images!r}"
        )
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input PDF not found: {input_path}")

    # Writing over the source would destroy the only copy of the original if
    # remediation failed partway through. The underlying library rejects this
    # too, but with a message about its own API rather than about the call.
    if os.path.exists(output_path) and os.path.samefile(input_path, output_path):
        raise ValueError(
            f"Refusing to overwrite the input document: {input_path}. "
            "Choose a different output path."
        )

    reporter: ProgressReporter = progress if progress is not None else ConsoleReporter()
    emit(reporter, Stage.OPENING, f"Opening {os.path.basename(input_path)}")

    with pikepdf.open(input_path) as pdf, pdfplumber.open(input_path) as plumber:
        # 1. INITIALIZATION & CATALOG SETUP
        root = pdf.Root

        # Clear existing structure mappings
        if "/StructTreeRoot" in root:
            del root["/StructTreeRoot"]
        for page in pdf.pages:
            if "/StructParents" in page:
                del page["/StructParents"]

        # Initialize mark info
        if "/MarkInfo" not in root:
            root.MarkInfo = pikepdf.Dictionary(Marked=True)
        else:
            root.MarkInfo.Marked = True

        # Create Document structural element
        document_elem = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/Document"), K=pikepdf.Array()
            )
        )

        all_pages_struct_elems = []

        # Annotations share the structure parent tree with pages but occupy
        # their own keys. Page k uses key k, so annotation keys start above the
        # last page and are handed out from this counter.
        annotation_parent_entries: list[tuple[int, pikepdf.Object]] = []
        next_struct_parent_key = len(pdf.pages)

        alt_text_provider = get_provider()
        figures_needing_review = 0
        vector_regions_found = 0

        # Loop through pages
        for page_idx, (pikepage, plumbpage) in enumerate(zip(pdf.pages, plumber.pages)):
            emit(
                reporter,
                Stage.ANALYSING_PAGE,
                f"Analysing page {page_idx + 1} of {len(pdf.pages)}",
                current=page_idx + 1,
                total=len(pdf.pages),
            )

            page_width = float(plumbpage.width)
            page_height = float(plumbpage.height)

            # Assign page structural index and keyboard tab navigation order (WCAG 2.4.3 & 1.3.1)
            pikepage["/StructParents"] = pikepdf.Integer(page_idx)
            pikepage["/Tabs"] = pikepdf.Name("/S")

            # 2. SEGMENTATION & COORDINATE EXTRACTION
            complex_bboxes_pdf = []

            # Reconstruct content stream
            final_ops = []
            mcid = 0
            page_struct_elems = []
            first_text_in_page = True

            # Prepend 'q' wrapped in /Artifact marked content to isolate coordinates
            final_ops.append(
                (
                    [
                        pikepdf.Name("/Artifact"),
                        pikepdf.Dictionary(Subtype=pikepdf.Name("/Layout")),
                    ],
                    pikepdf.Operator("BDC"),
                )
            )
            final_ops.append(([], pikepdf.Operator("q")))
            final_ops.append(([], pikepdf.Operator("EMC")))

            # Geometry observed while walking the stream, used below to detect
            # figures without parsing the page a second time.
            geometry: dict[str, list] = {"images": [], "paths": [], "text": []}
            # Where this page's entries begin in the document's logical tree,
            # so the reading order can be rearranged without disturbing the
            # pages already written.
            first_kid_index = len(document_elem.K)
            page_text = plumbpage.extract_text() or ""

            # Filter page contents (strip paths & strip text inside complex bboxes)
            generator = filter_page_content(pikepage, complex_bboxes_pdf, collect=geometry)
            if generator:
                for item_type, data in generator:
                    if item_type == "text":
                        # Classify text block as /H1, /H2, or /P for WCAG 1.3.1 Info and Relationships
                        tag_name = "/P"
                        text_preview = ""
                        for op_data in data:
                            if len(op_data) == 2:
                                ops, op = op_data
                                op_str = str(op)
                                if op_str == "Tj":
                                    text_preview += str(ops[0])
                                elif op_str == "TJ":
                                    for item in ops[0]:
                                        if isinstance(item, pikepdf.String):
                                            text_preview += str(item)
                        text_preview = text_preview.strip()

                        if first_text_in_page and page_idx == 0:
                            tag_name = "/H1"
                            first_text_in_page = False
                        elif text_preview in (
                            "References",
                            "Abstract",
                            "Introduction",
                            "Conclusion",
                            "Methodology",
                            "Results",
                            "Discussion",
                            "Background",
                        ):
                            tag_name = "/H2"

                        # Wrap text block in /Tag << /MCID mcid >> BDC
                        final_ops.append(
                            (
                                [pikepdf.Name(tag_name), pikepdf.Dictionary(MCID=mcid)],
                                pikepdf.Operator("BDC"),
                            )
                        )
                        final_ops.extend(data)
                        final_ops.append(([], pikepdf.Operator("EMC")))

                        # Create structural element
                        p_elem = pdf.make_indirect(
                            pikepdf.Dictionary(
                                Type=pikepdf.Name("/StructElem"),
                                S=pikepdf.Name(tag_name),
                                P=document_elem,
                                Pg=pikepage.obj,
                                K=pikepdf.Integer(mcid),
                            )
                        )
                        document_elem.K.append(p_elem)
                        page_struct_elems.append(p_elem)
                        mcid += 1
                    elif item_type == "empty_text":
                        final_ops.append(
                            (
                                [
                                    pikepdf.Name("/Artifact"),
                                    pikepdf.Dictionary(Subtype=pikepdf.Name("/Layout")),
                                ],
                                pikepdf.Operator("BDC"),
                            )
                        )
                        final_ops.extend(data)
                        final_ops.append(([], pikepdf.Operator("EMC")))
                    elif item_type == "artifact":
                        # Wrap path block in /Artifact << /Subtype /Layout >> BDC ... EMC
                        final_ops.append(
                            (
                                [
                                    pikepdf.Name("/Artifact"),
                                    pikepdf.Dictionary(Subtype=pikepdf.Name("/Layout")),
                                ],
                                pikepdf.Operator("BDC"),
                            )
                        )
                        final_ops.extend(data)
                        final_ops.append(([], pikepdf.Operator("EMC")))
                    else:  # other
                        # An image drawn here is real content, not decoration.
                        # Wrapping it as an artifact, which is what this did
                        # before, hides it from assistive technology entirely
                        # and is the reason no /Figure element was ever
                        # produced despite the documented behaviour.
                        placement = None
                        if (
                            str(data[1]) == "Do"
                            and geometry["images"]
                            and geometry["images"][-1][0] == str(data[0][0])
                        ):
                            candidate = geometry["images"][-1][1]
                            if is_meaningful_image(
                                candidate, page_width=page_width, page_height=page_height
                            ):
                                placement = candidate

                        figure = None
                        alt_text = None
                        if placement is not None:
                            figure = DetectedFigure(
                                bbox=placement, kind="image", xobject_name=str(data[0][0])
                            )
                            _, alt_text, needs_review = describe_figures(
                                [figure],
                                page_index=page_idx,
                                page_width=page_width,
                                page_height=page_height,
                                page_text=page_text,
                                provider=alt_text_provider,
                            )[0]
                            if needs_review:
                                figures_needing_review += 1
                            # Under the artifact policy an image nobody could
                            # describe is treated as decoration, which conforms
                            # at the cost of removing it from the reading order.
                            if alt_text is None and undescribed_images == "artifact":
                                figure = None

                        if figure is not None:
                            final_ops.append(
                                (
                                    [pikepdf.Name("/Figure"), pikepdf.Dictionary(MCID=mcid)],
                                    pikepdf.Operator("BDC"),
                                )
                            )
                            final_ops.append(data)
                            final_ops.append(([], pikepdf.Operator("EMC")))

                            figure_elem = build_figure_element(
                                pdf,
                                figure,
                                parent=document_elem,
                                page=pikepage.obj,
                                mcid=mcid,
                                alt_text=alt_text,
                            )
                            document_elem.K.append(figure_elem)
                            page_struct_elems.append(figure_elem)
                            mcid += 1
                        else:
                            final_ops.append(
                                (
                                    [
                                        pikepdf.Name("/Artifact"),
                                        pikepdf.Dictionary(Subtype=pikepdf.Name("/Layout")),
                                    ],
                                    pikepdf.Operator("BDC"),
                                )
                            )
                            final_ops.append(data)
                            final_ops.append(([], pikepdf.Operator("EMC")))

            # Tag Link annotations for WCAG 1.3.1 and 2.4.4.
            #
            # ISO 32000-1 14.7.4.4 gives annotations their own key space in the
            # structure parent tree: /StructParent on an annotation resolves to
            # a single structure element, whereas /StructParents on a page
            # resolves to an array indexed by marked-content identifier. Reusing
            # the page's index for both, as this previously did, makes one key
            # mean two different things and leaves the annotation unreachable
            # from the tree.
            if "/Annots" in pikepage:
                try:
                    annots = pikepage.Annots
                    if isinstance(annots, pikepdf.Array):
                        for annot in annots:
                            try:
                                if not hasattr(annot, "get"):
                                    continue
                                if annot.get("/Subtype") != pikepdf.Name("/Link"):
                                    continue
                                link_key = next_struct_parent_key
                                next_struct_parent_key += 1
                                annot["/StructParent"] = pikepdf.Integer(link_key)

                                # ISO 14289-1 7.18.5 requires a link to carry an
                                # alternate description in /Contents. Describing
                                # the destination is more useful to a screen
                                # reader than a generic word such as "Hyperlink",
                                # which conveys only what the tag already says.
                                if (
                                    "/Contents" not in annot
                                    or not str(annot.get("/Contents", "")).strip()
                                ):
                                    annot["/Contents"] = pikepdf.String(
                                        _describe_link_target(annot)
                                    )

                                link_elem = pdf.make_indirect(
                                    pikepdf.Dictionary(
                                        Type=pikepdf.Name("/StructElem"),
                                        S=pikepdf.Name("/Link"),
                                        P=document_elem,
                                        Pg=pikepage.obj,
                                        Alt=annot["/Contents"],
                                        K=pikepdf.Dictionary(
                                            Type=pikepdf.Name("/OBJR"),
                                            Obj=annot,
                                            Pg=pikepage.obj,
                                        ),
                                    )
                                )
                                document_elem.K.append(link_elem)
                                annotation_parent_entries.append((link_key, link_elem))
                            except Exception:
                                _LOG.debug(
                                    "skipped tagging a link annotation on page %d",
                                    page_idx + 1,
                                    exc_info=True,
                                )
                except Exception:
                    _LOG.debug("could not read /Annots on page %d", page_idx + 1, exc_info=True)

            # Balance the graphics state stack opened at the top of the page.
            #
            # One 'q' is pushed before the filtered content; exactly one 'Q'
            # closes it. Emitting a second 'Q', as this previously did, popped
            # an empty stack on every page.
            final_ops.append(
                (
                    [
                        pikepdf.Name("/Artifact"),
                        pikepdf.Dictionary(Subtype=pikepdf.Name("/Layout")),
                    ],
                    pikepdf.Operator("BDC"),
                )
            )
            final_ops.append(([], pikepdf.Operator("Q")))
            final_ops.append(([], pikepdf.Operator("EMC")))

            # The OCR layer is emitted after the stack is balanced so its text
            # matrices are interpreted against the identity transform rather
            # than whatever the page's own content left in place.
            if len(page_text.strip()) < 10:
                emit(
                    reporter,
                    Stage.RECOGNISING_TEXT,
                    f"Page {page_idx + 1} looks scanned; recognising its text",
                    current=page_idx + 1,
                    total=len(pdf.pages),
                )
                from .ocr_engine import generate_ocr_text_ops

                ocr_ops, ocr_elems, mcid = generate_ocr_text_ops(
                    input_path,
                    page_idx,
                    page_width,
                    page_height,
                    mcid,
                    pdf,
                    pikepage,
                    document_elem,
                )
                if ocr_ops:
                    final_ops.extend(ocr_ops)
                    page_struct_elems.extend(ocr_elems)

            # Vector artwork is clustered and reported, not restructured.
            #
            # Grouping scattered path operations under one /Figure would mean
            # reordering drawing operations, which changes what the page looks
            # like because paint order is significant. Reporting the regions
            # lets a person tag them deliberately, which is the honest option
            # until a safe grouping strategy exists.
            if geometry["paths"]:
                regions = detect_vector_figures(
                    geometry["paths"],
                    page_width=page_width,
                    page_height=page_height,
                    exclude=[box for _name, box in geometry["images"]],
                )
                if regions:
                    vector_regions_found += len(regions)
                    emit(
                        reporter,
                        Stage.TAGGING_FIGURES,
                        f"{len(regions)} vector region(s) on page {page_idx + 1} may be "
                        "figures; kept as artifacts pending review",
                        regions=len(regions),
                        page=page_idx + 1,
                    )

            # Write reconstructed stream back to the page contents
            if final_ops:
                pikepage.Contents = pikepdf.Stream(pdf, pikepdf.unparse_content_stream(final_ops))
            else:
                pikepage.Contents = pikepdf.Stream(pdf, b"")

            if reading_order_strategy != "stream-order":
                _apply_reading_order(
                    reading_order_strategy,
                    document_elem,
                    first_kid_index,
                    geometry["text"],
                    page_idx,
                    reporter,
                )

            all_pages_struct_elems.append(page_struct_elems)

        # 5. GLOBAL BRUTE-FORCE METADATA INJECTION
        # Set Reading Language
        root["/Lang"] = pikepdf.String("en-US")

        # Display Title in Preferences
        try:
            if "/ViewerPreferences" not in root:
                root["/ViewerPreferences"] = pikepdf.Dictionary(DisplayDocTitle=True)
            else:
                vp = root["/ViewerPreferences"]
                if isinstance(vp, pikepdf.Dictionary):
                    vp["/DisplayDocTitle"] = True
                else:
                    root["/ViewerPreferences"] = pikepdf.Dictionary(DisplayDocTitle=True)
        except Exception:
            root["/ViewerPreferences"] = pikepdf.Dictionary(DisplayDocTitle=True)

        # Ensure title exists in Info dict
        title = "Accessible Document"
        try:
            if "/Title" in pdf.docinfo and str(pdf.docinfo.Title).strip():
                title = str(pdf.docinfo.Title)
            else:
                pdf.docinfo["/Title"] = title
        except Exception:
            pdf.docinfo["/Title"] = title

        pdf.docinfo["/Producer"] = "ADA PDF Remediator"

        now = datetime.now(timezone.utc)
        pdf_date = f"D:{now.strftime('%Y%m%d%H%M%S')}+00'00'"
        xmp_date = now.replace(microsecond=0).isoformat()

        pdf.docinfo["/ModDate"] = pdf_date
        if "/CreationDate" not in pdf.docinfo:
            pdf.docinfo["/CreationDate"] = pdf_date

        # Append the XMP metadata stream carrying the PDF/UA identification.
        #
        # The namespace URI below is the one ISO 14289-1 clause 5 defines. It is
        # deliberately not http://www.aiim.org/pdfuaid/ns/id/: the customary
        # prefix is "pdfuaid" but the URI path segment is "pdfua". Getting this
        # wrong produces a file that looks correct under casual inspection and
        # that some checkers still score as compliant, while a conforming
        # validator cannot identify it as PDF/UA at all.
        xmp_template = f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="ADA PDF Remediator">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
    xmlns:pdfuaid="{PDFUA_ID_NAMESPACE}">
   <dc:format>application/pdf</dc:format>
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{_xml_escape(title)}</rdf:li></rdf:Alt></dc:title>
   <dc:creator><rdf:Seq><rdf:li>ADA PDF Remediator</rdf:li></rdf:Seq></dc:creator>
   <xmp:CreateDate>{xmp_date}</xmp:CreateDate>
   <xmp:ModifyDate>{xmp_date}</xmp:ModifyDate>
   <xmp:MetadataDate>{xmp_date}</xmp:MetadataDate>
   <pdf:Producer>ADA PDF Remediator</pdf:Producer>
   <pdfuaid:part>1</pdfuaid:part>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

        meta_stream = pikepdf.Stream(pdf, xmp_template.encode("utf-8"))
        meta_stream.Type = pikepdf.Name("/Metadata")
        meta_stream.Subtype = pikepdf.Name("/XML")
        root["/Metadata"] = meta_stream

        # Build the structure parent tree.
        #
        # Two kinds of entry share one key space, as ISO 32000-1 14.7.4.4
        # requires: a page's key maps to an array indexed by marked-content
        # identifier, while an annotation's key maps directly to the single
        # element that describes it.
        parent_entries: list[tuple[int, pikepdf.Object]] = [
            (idx, pikepdf.Array(page_elems))
            for idx, page_elems in enumerate(all_pages_struct_elems)
        ]
        parent_entries.extend(annotation_parent_entries)

        parent_tree = build_number_tree(pdf, parent_entries)
        struct_tree_root = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/StructTreeRoot"),
                K=document_elem,
                ParentTree=parent_tree,
                # The highest key in use, so a consumer appending to the tree
                # knows where to continue without rescanning it.
                ParentTreeNextKey=pikepdf.Integer(next_struct_parent_key),
            )
        )
        document_elem["/P"] = struct_tree_root
        root["/StructTreeRoot"] = struct_tree_root

        emit(reporter, Stage.BUILDING_STRUCTURE, "Building the structure tree")
        emit(reporter, Stage.RECOVERING_FONTS, "Recovering font character mappings")
        font_objs = []
        seen_fonts: set[tuple[int, int]] = set()
        try:
            for page in pdf.pages:
                if "/Resources" in page:
                    res = page.Resources
                    if isinstance(res, pikepdf.Dictionary) and "/Font" in res:
                        fonts_dict = res.Font
                        if isinstance(fonts_dict, pikepdf.Dictionary):
                            for _key, f_obj in fonts_dict.items():
                                if not isinstance(f_obj, pikepdf.Dictionary):
                                    continue
                                marker = f_obj.objgen
                                if marker != (0, 0):
                                    if marker in seen_fonts:
                                        continue
                                    seen_fonts.add(marker)
                                font_objs.append(f_obj)
        except Exception:
            # Partial collection is still worth processing: the fonts gathered
            # before the failure get their mappings recovered. The count that
            # follows is reported against font_objs, so it stays truthful about
            # what was actually examined.
            _LOG.debug("stopped collecting fonts after %d", len(font_objs), exc_info=True)

        unresolved_total = 0
        for idx, obj in enumerate(font_objs):
            base_font = str(obj.get("/BaseFont", "Unnamed")).lstrip("/")
            try:
                # Every font is processed, not only those missing a map. An
                # existing map is treated as the most authoritative source and
                # is extended rather than replaced, so a font that already has
                # a good map keeps it and one with a partial map gains the rest.
                recovered = recover_font_mapping(obj, base_font)
                if not recovered.mapping:
                    emit(
                        reporter,
                        Stage.RECOVERING_FONTS,
                        f"{base_font}: no character mapping could be recovered",
                        font=base_font,
                    )
                    continue

                cmap_stream = pikepdf.Stream(pdf, recovered.to_cmap().encode("utf-8"))
                obj["/ToUnicode"] = cmap_stream

                summary = ", ".join(
                    f"{count} from {source}"
                    for source, count in recovered.counts_by_source().items()
                )
                emit(
                    reporter,
                    Stage.RECOVERING_FONTS,
                    f"{base_font}: {recovered.resolved_count} codes mapped ({summary})",
                    font=base_font,
                    mapped=recovered.resolved_count,
                )

                if recovered.unresolved_glyphs:
                    unresolved_total += len(recovered.unresolved_glyphs)
                    names = sorted(set(recovered.unresolved_glyphs.values()))[:6]
                    emit(
                        reporter,
                        Stage.RECOVERING_FONTS,
                        f"{base_font}: {len(recovered.unresolved_glyphs)} codes left "
                        f"unmapped (glyphs: {', '.join(names)})",
                        font=base_font,
                        unresolved=len(recovered.unresolved_glyphs),
                    )
            except Exception as e:
                emit(
                    reporter,
                    Stage.RECOVERING_FONTS,
                    f"{base_font}: recovery failed, leaving the font unchanged ({e})",
                    font=base_font,
                )
                _ = idx

        if figures_needing_review:
            emit(
                reporter,
                Stage.TAGGING_FIGURES,
                f"{figures_needing_review} figure(s) need a human description. "
                "No placeholder text was invented for them.",
                figures_needing_review=figures_needing_review,
            )
        if vector_regions_found:
            emit(
                reporter,
                Stage.TAGGING_FIGURES,
                f"{vector_regions_found} vector region(s) look like figures and are "
                "candidates for manual tagging.",
                vector_regions=vector_regions_found,
            )

        if unresolved_total:
            # Reported rather than papered over. A code mapped to a space looks
            # like success and silently deletes text from the document.
            emit(
                reporter,
                Stage.RECOVERING_FONTS,
                f"{unresolved_total} character codes could not be resolved and were left unmapped.",
                unresolved=unresolved_total,
            )

        emit(reporter, Stage.WRITING, f"Writing {os.path.basename(output_path)}")
        pdf.save(output_path)

    emit(reporter, Stage.DONE, "Remediation finished")
