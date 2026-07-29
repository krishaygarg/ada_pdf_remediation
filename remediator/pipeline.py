import os
from datetime import datetime, timezone

import pdfplumber
import pikepdf

from .content_filter import filter_page_content
from .font_patcher import generate_tounicode_cmap
from .numbertree import build_number_tree

#: Namespace URI of the PDF/UA identification schema, ISO 14289-1 clause 5.
#: The conventional prefix is "pdfuaid" but the URI path segment is "pdfua".
PDFUA_ID_NAMESPACE = "http://www.aiim.org/pdfua/ns/id/"


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
        pass
    return "Link"


def _xml_escape(value: str) -> str:
    """Escape text for inclusion in an XMP character data section."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def remediate_single_pdf(input_path: str, output_path: str):
    """
    Performs PDF accessibility remediation.
    """
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

    print(f"[REMEDIATOR] Opening input PDF: {input_path}")

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

        # Loop through pages
        for page_idx, (pikepage, plumbpage) in enumerate(zip(pdf.pages, plumber.pages)):
            print(
                f"[REMEDIATOR] Segmenting and reconstructing Page {page_idx + 1}/{len(pdf.pages)}..."
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

            # Filter page contents (strip paths & strip text inside complex bboxes)
            generator = filter_page_content(pikepage, complex_bboxes_pdf)
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
                                pass
                except Exception:
                    pass

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
            page_text = (plumbpage.extract_text() or "").strip()
            if len(page_text) < 10:
                print("  - Scanned image page detected! Generating invisible OCR text layer...")
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

            # Write reconstructed stream back to the page contents
            if final_ops:
                pikepage.Contents = pikepdf.Stream(pdf, pikepdf.unparse_content_stream(final_ops))
            else:
                pikepage.Contents = pikepdf.Stream(pdf, b"")

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

        print("[REMEDIATOR] Patching missing font /ToUnicode CMap character mappings...")
        font_objs = []
        try:
            for page in pdf.pages:
                if "/Resources" in page:
                    res = page.Resources
                    if isinstance(res, pikepdf.Dictionary) and "/Font" in res:
                        fonts_dict = res.Font
                        if isinstance(fonts_dict, pikepdf.Dictionary):
                            for k in fonts_dict.keys():
                                try:
                                    f_obj = fonts_dict[k]
                                    if f_obj not in font_objs:
                                        font_objs.append(f_obj)
                                except Exception:
                                    pass
        except Exception:
            pass

        for idx, obj in enumerate(font_objs):
            try:
                if isinstance(obj, pikepdf.Dictionary) and "/ToUnicode" not in obj:
                    base_font = "Unknown"
                    if "/BaseFont" in obj:
                        base_font = str(obj.get("/BaseFont", "Unknown"))
                    print(f"  - Patching font {idx} ({base_font})...")
                    generated_cmap = generate_tounicode_cmap(obj, base_font, input_path)
                    cmap_stream = pikepdf.Stream(pdf, generated_cmap.encode("utf-8"))
                    obj["/ToUnicode"] = cmap_stream
            except Exception as e:
                print(f"  - Skipping font {idx} due to error: {e}")

        print(f"[REMEDIATOR] Saving remediated PDF output: {output_path}")
        pdf.save(output_path)

    print("[REMEDIATOR] Pipeline completed successfully!")

    # Clean up temporary raster images if any remain
    pass
