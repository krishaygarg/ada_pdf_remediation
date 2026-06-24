#!/usr/bin/env python3
import os
import sys
import io
import pikepdf
import pdfplumber
from pdf2image import convert_from_path
from PIL import Image
from datetime import datetime, timezone

def merge_bboxes(boxes):
    """
    Consolidates overlapping or intersecting bounding boxes into disjoint regions.
    Uses padding to group nearby elements (e.g., table cells/lines or formula curves).
    """
    if not boxes:
        return []
    
    n = len(boxes)
    parent = list(range(n))
    
    def find(i):
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]
    
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j
            
    def boxes_overlap(box1, box2):
        x0_1, top_1, x1_1, bottom_1 = box1
        x0_2, top_2, x1_2, bottom_2 = box2
        padding = 2.0  # Points padding to merge adjacent shapes
        return not (
            x1_1 + padding < x0_2 or 
            x0_1 - padding > x1_2 or 
            bottom_1 + padding < top_2 or 
            top_1 - padding > bottom_2
        )

    for i in range(n):
        for j in range(i + 1, n):
            if boxes_overlap(boxes[i], boxes[j]):
                union(i, j)
                
    groups = {}
    for i in range(n):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(boxes[i])
        
    merged = []
    for g_boxes in groups.values():
        x0 = min(b[0] for b in g_boxes)
        top = min(b[1] for b in g_boxes)
        x1 = max(b[2] for b in g_boxes)
        bottom = max(b[3] for b in g_boxes)
        merged.append([x0, top, x1, bottom])
        
    return merged

def multiply_matrices(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return [
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2
    ]

def transform_point(x, y, m):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)

def get_operator_coords(op_name, operands):
    coords = []
    if op_name in ('m', 'l'):
        if len(operands) >= 2:
            coords.append((float(operands[0]), float(operands[1])))
    elif op_name == 're':
        if len(operands) >= 4:
            x, y, w, h = float(operands[0]), float(operands[1]), float(operands[2]), float(operands[3])
            coords.append((x, y))
            coords.append((x + w, y + h))
    elif op_name == 'c':
        if len(operands) >= 6:
            coords.append((float(operands[0]), float(operands[1])))
            coords.append((float(operands[2]), float(operands[3])))
            coords.append((float(operands[4]), float(operands[5])))
    elif op_name in ('v', 'y'):
        if len(operands) >= 4:
            coords.append((float(operands[0]), float(operands[1])))
            coords.append((float(operands[2]), float(operands[3])))
    return coords

def filter_page_content(page_obj, complex_bboxes_pdf_space):
    """
    Parses the page content stream. Dynamically tracks the Coordinate Transformation Matrix (CTM)
    and text matrices. Strips path drawing operations inside complex bboxes, wraps path drawing
    operators outside complex bboxes inside '/Artifact', and filters text content inside complex bboxes.
    Yields blocks of instructions: ('text', ops), ('empty_text', ops), ('artifact', ops), or ('other', op).
    """
    try:
        instructions = pikepdf.parse_content_stream(page_obj)
    except Exception:
        return
    
    path_construction_ops = {'m', 'l', 'c', 'v', 'y', 'h', 're'}
    path_painting_ops = {'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'n'}
    clipping_ops = {'W', 'W*'}
    
    ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    ctm_stack = []
    
    t_m = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    t_lm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    t_leading = 0.0
    
    in_text_block = False
    text_block_ops = []
    has_visible_text = False
    
    path_buffer = []
    
    for operands, operator in instructions:
        op_name = str(operator)
        
        # Strip pre-existing marked content operators to avoid nesting structural blocks
        if op_name in ('BDC', 'BMC', 'EMC'):
            continue
            
        # Track CTM
        if op_name == 'q':
            ctm_stack.append(list(ctm))
        elif op_name == 'Q':
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op_name == 'cm':
            if len(operands) >= 6:
                ctm = multiply_matrices([float(x) for x in operands], ctm)
            
        # Track text state
        if op_name == 'BT':
            in_text_block = True
            text_block_ops = []
            has_visible_text = False
            t_m = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            t_lm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            t_leading = 0.0
            text_block_ops.append((operands, operator))
            continue
            
        if in_text_block:
            text_block_ops.append((operands, operator))
            
            # Update matrices
            if op_name == 'Tm':
                if len(operands) >= 6:
                    t_m = [float(x) for x in operands]
                    t_lm = list(t_m)
            elif op_name in ('Td', 'TD'):
                if len(operands) >= 2:
                    tx_o, ty_o = float(operands[0]), float(operands[1])
                    if op_name == 'TD':
                        t_leading = -ty_o
                    t_lm = multiply_matrices([1.0, 0.0, 0.0, 1.0, tx_o, ty_o], t_lm)
                    t_m = list(t_lm)
            elif op_name == 'T*':
                t_lm = multiply_matrices([1.0, 0.0, 0.0, 1.0, 0.0, -t_leading], t_lm)
                t_m = list(t_lm)
            elif op_name == 'TL':
                if len(operands) >= 1:
                    t_leading = float(operands[0])
            elif op_name in ("'", '"'):
                tx_o, ty_o = 0.0, -t_leading
                t_lm = multiply_matrices([1.0, 0.0, 0.0, 1.0, tx_o, ty_o], t_lm)
                t_m = list(t_lm)
                
            # Perform text content filtering/visibility check for text showing operators
            if op_name in ('Tj', 'TJ', "'", '"'):
                tx_c, ty_c = t_m[4], t_m[5]
                x_pdf, y_pdf = transform_point(tx_c, ty_c, ctm)
                
                inside = False
                for bbox in complex_bboxes_pdf_space:
                    bx0, by0, bx1, by1 = bbox
                    if bx0 <= x_pdf <= bx1 and by0 <= y_pdf <= by1:
                        inside = True
                        break
                        
                if inside:
                    if op_name == 'Tj':
                        operands[0] = pikepdf.String("")
                    elif op_name == 'TJ':
                        operands[0] = pikepdf.Array()
                    elif op_name == "'":
                        operands[0] = pikepdf.String("")
                    elif op_name == '"':
                        operands[2] = pikepdf.String("")
                else:
                    if op_name == 'Tj':
                        if str(operands[0]).strip():
                            has_visible_text = True
                    elif op_name == 'TJ':
                        for item in operands[0]:
                            if isinstance(item, pikepdf.String):
                                if str(item).strip():
                                    has_visible_text = True
                                    break
                    elif op_name in ("'", '"'):
                        if str(operands[-1]).strip():
                            has_visible_text = True
                            
            if op_name == 'ET':
                in_text_block = False
                if has_visible_text:
                    yield 'text', text_block_ops
                else:
                    yield 'empty_text', text_block_ops
            continue
            
        # Handle path operators
        if op_name in path_construction_ops or op_name in clipping_ops:
            path_buffer.append(((operands, operator), list(ctm)))
            continue
            
        if op_name in path_painting_ops:
            path_buffer.append(((operands, operator), list(ctm)))
            
            # Process the full path sequence in the buffer
            coords_pdf = []
            for (item_ops, item_op), item_ctm in path_buffer:
                item_op_name = str(item_op)
                coords_c = get_operator_coords(item_op_name, item_ops)
                for cx, cy in coords_c:
                    px, py = transform_point(cx, cy, item_ctm)
                    coords_pdf.append((px, py))
                    
            inside_complex = False
            if coords_pdf:
                for px, py in coords_pdf:
                    for bbox in complex_bboxes_pdf_space:
                        bx0, by0, bx1, by1 = bbox
                        if bx0 <= px <= bx1 and by0 <= py <= by1:
                            inside_complex = True
                            break
                    if inside_complex:
                        break
                        
            if not inside_complex:
                yield 'artifact', [op_item for op_item, _ in path_buffer]
                
            path_buffer = []
            continue
            
        # Flush path buffer if other operator is met (usually doesn't happen for valid PDFs)
        if path_buffer:
            inside_complex = False
            coords_pdf = []
            for (item_ops, item_op), item_ctm in path_buffer:
                item_op_name = str(item_op)
                coords_c = get_operator_coords(item_op_name, item_ops)
                for cx, cy in coords_c:
                    px, py = transform_point(cx, cy, item_ctm)
                    coords_pdf.append((px, py))
            if coords_pdf:
                for px, py in coords_pdf:
                    for bbox in complex_bboxes_pdf_space:
                        bx0, by0, bx1, by1 = bbox
                        if bx0 <= px <= bx1 and by0 <= py <= by1:
                            inside_complex = True
                            break
                    if inside_complex:
                        break
            if not inside_complex:
                yield 'artifact', [op_item for op_item, _ in path_buffer]
            path_buffer = []
            
        yield 'other', (operands, operator)

def remediate_single_pdf(input_path: str, output_path: str):
    """
    Performs Flatten-to-Figures PDF accessibility remediation.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input PDF not found: {input_path}")
        
    print(f"[REMEDIATOR] Opening input PDF: {input_path}")
    
    # Render all PDF pages upfront for visual cropping
    # We render at 200 DPI for high-resolution crops
    print("[REMEDIATOR] Rendering page snapshots for visual rasterization...")
    page_images = convert_from_path(input_path, dpi=200)
    
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
        document_elem = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name("/StructElem"),
            S=pikepdf.Name("/Document"),
            K=pikepdf.Array()
        ))
        
        all_pages_struct_elems = []
        
        # Loop through pages
        for page_idx, (pikepage, plumbpage) in enumerate(zip(pdf.pages, plumber.pages)):
            print(f"[REMEDIATOR] Segmenting and reconstructing Page {page_idx + 1}/{len(pdf.pages)}...")
            
            page_width = float(plumbpage.width)
            page_height = float(plumbpage.height)
            
            # Assign page structural index
            pikepage["/StructParents"] = pikepdf.Integer(page_idx)
            
            # 2. SEGMENTATION & COORDINATE EXTRACTION
            bboxes = []
            
            # Detect tables
            tables = plumbpage.find_tables()
            for t in tables:
                bboxes.append(list(t.bbox))
                
            # Detect drawings
            for draw_type in ['rects', 'lines', 'curves', 'images']:
                elements = getattr(plumbpage, draw_type, [])
                for elem in elements:
                    x0 = float(elem.get('x0', 0))
                    top = float(elem.get('top', 0))
                    x1 = float(elem.get('x1', 0))
                    bottom = float(elem.get('bottom', 0))
                    w = x1 - x0
                    h = bottom - top
                    if w < 3 and h < 3:
                        continue
                    bboxes.append([x0, top, x1, bottom])
                    
            # Merge overlapping bboxes
            merged_bboxes = merge_bboxes(bboxes)
            print(f"  - Detected {len(merged_bboxes)} complex components to flatten.")
            
            # Convert merged bboxes to PDF bottom-left coordinates
            complex_bboxes_pdf = []
            for bbox in merged_bboxes:
                x0, top, x1, bottom = bbox
                pdf_x0 = x0
                pdf_x1 = x1
                pdf_y0 = page_height - bottom
                pdf_y1 = page_height - top
                complex_bboxes_pdf.append([pdf_x0, pdf_y0, pdf_x1, pdf_y1])
                
            # Reconstruct content stream
            final_ops = []
            mcid = 0
            page_struct_elems = []
            
            # Prepend 'q' to isolate original page coordinates
            final_ops.append(([], pikepdf.Operator("q")))
            
            # Filter page contents (strip paths & strip text inside complex bboxes)
            generator = filter_page_content(pikepage, complex_bboxes_pdf)
            if generator:
                for item_type, data in generator:
                    if item_type == 'text':
                        # Wrap text block in /P << /MCID mcid >> BDC
                        final_ops.append(([pikepdf.Name("/P"), pikepdf.Dictionary(MCID=mcid)], pikepdf.Operator("BDC")))
                        final_ops.extend(data)
                        final_ops.append(([], pikepdf.Operator("EMC")))
                        
                        # Create structural P tag
                        p_elem = pdf.make_indirect(pikepdf.Dictionary(
                            Type=pikepdf.Name("/StructElem"),
                            S=pikepdf.Name("/P"),
                            P=document_elem,
                            Pg=pikepage.obj,
                            K=pikepdf.Integer(mcid)
                        ))
                        document_elem.K.append(p_elem)
                        page_struct_elems.append(p_elem)
                        mcid += 1
                    elif item_type == 'empty_text':
                        final_ops.extend(data)
                    elif item_type == 'artifact':
                        # Wrap path block in /Artifact << /Subtype /Layout >> BDC ... EMC
                        final_ops.append(([pikepdf.Name("/Artifact"), pikepdf.Dictionary(Subtype=pikepdf.Name("/Layout"))], pikepdf.Operator("BDC")))
                        final_ops.extend(data)
                        final_ops.append(([], pikepdf.Operator("EMC")))
                    else: # other
                        final_ops.append(data)
                        
            # Append 'Q' to restore default page coordinates
            final_ops.append(([], pikepdf.Operator("Q")))
            
            # Crop complex components and insert them as Figure images
            page_image = page_images[page_idx]
            for idx, bbox in enumerate(merged_bboxes):
                x0, top, x1, bottom = bbox
                
                # Render coordinates to PIL pixels
                img_w, img_h = page_image.size
                scale_x = img_w / page_width if page_width > 0 else 1.0
                scale_y = img_h / page_height if page_height > 0 else 1.0
                
                cx0 = max(0.0, min(x0 * scale_x, img_w))
                ctop = max(0.0, min(top * scale_y, img_h))
                cx1 = max(0.0, min(x1 * scale_x, img_w))
                cbottom = max(0.0, min(bottom * scale_y, img_h))
                
                if cx1 <= cx0 or cbottom <= ctop:
                    continue
                    
                # Take visual snapshot crop of page element
                cropped = page_image.crop((cx0, ctop, cx1, cbottom))
                crop_io = io.BytesIO()
                # Convert to RGB mode for JPEG format compatibility
                rgb_cropped = cropped.convert("RGB")
                rgb_cropped.save(crop_io, format="JPEG", quality=95)
                jpeg_bytes = crop_io.getvalue()
                
                # Create atomic image XObject
                img_stream = pikepdf.Stream(pdf, jpeg_bytes)
                img_stream.Type = pikepdf.Name("/XObject")
                img_stream.Subtype = pikepdf.Name("/Image")
                img_stream.Width = rgb_cropped.width
                img_stream.Height = rgb_cropped.height
                img_stream.ColorSpace = pikepdf.Name("/DeviceRGB")
                img_stream.BitsPerComponent = 8
                img_stream.Filter = pikepdf.Name("/DCTDecode")
                
                # Register resource XObject
                if "/Resources" not in pikepage:
                    pikepage.Resources = pikepdf.Dictionary()
                if "/XObject" not in pikepage.Resources:
                    pikepage.Resources.XObject = pikepdf.Dictionary()
                    
                img_res_name = f"ImgF{page_idx}_{idx}"
                pikepage.Resources.XObject[pikepdf.Name(f"/{img_res_name}")] = img_stream
                
                # Write to stream
                pdf_x0 = x0
                pdf_x1 = x1
                pdf_y0 = page_height - bottom
                pdf_y1 = page_height - top
                w_pts = pdf_x1 - pdf_x0
                h_pts = pdf_y1 - pdf_y0
                
                # Insert Image drawing command wrapped in marked content
                final_ops.append(([pikepdf.Name("/Figure"), pikepdf.Dictionary(MCID=mcid)], pikepdf.Operator("BDC")))
                final_ops.append(([], pikepdf.Operator("q")))
                final_ops.append(([w_pts, 0, 0, h_pts, pdf_x0, pdf_y0], pikepdf.Operator("cm")))
                final_ops.append(([pikepdf.Name(f"/{img_res_name}")], pikepdf.Operator("Do")))
                final_ops.append(([], pikepdf.Operator("Q")))
                final_ops.append(([], pikepdf.Operator("EMC")))
                
                # Create structural Figure tag with mandatory BBox and Alt properties
                # BBox must be nested inside an Attribute dictionary /A owned by /Layout
                attr_dict = pikepdf.Dictionary(
                    O=pikepdf.Name("/Layout"),
                    BBox=pikepdf.Array([pdf_x0, pdf_y0, pdf_x1, pdf_y1])
                )
                fig_elem = pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/Figure"),
                    P=document_elem,
                    Pg=pikepage.obj,
                    K=pikepdf.Integer(mcid),
                    Alt=pikepdf.String("Image"),
                    A=attr_dict
                ))
                document_elem.K.append(fig_elem)
                page_struct_elems.append(fig_elem)
                mcid += 1
                
            # Write reconstructed stream back to the page contents
            if final_ops:
                pikepage.Contents = pikepdf.Stream(pdf, pikepdf.unparse_content_stream(final_ops))
            else:
                pikepage.Contents = pikepdf.Stream(pdf, b"")
                
            all_pages_struct_elems.append(page_struct_elems)
            
        # 5. GLOBAL BRUTE-FORCE METADATA INJECTION
        # Set Reading Language
        root.Lang = pikepdf.String("en-US")
        
        # Display Title in Preferences
        if "/ViewerPreferences" not in root:
            root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        else:
            root.ViewerPreferences.DisplayDocTitle = True
            
        # Ensure title exists in Info dict
        title = "Accessible Document"
        if "/Title" in pdf.docinfo and str(pdf.docinfo.Title).strip():
            title = str(pdf.docinfo.Title)
        else:
            pdf.docinfo["/Title"] = title
            
        pdf.docinfo["/Producer"] = "ADA PDF Remediator"
        
        now = datetime.now(timezone.utc)
        pdf_date = f"D:{now.strftime('%Y%m%d%H%M%S')}+00'00'"
        xmp_date = now.replace(microsecond=0).isoformat()
        
        pdf.docinfo["/ModDate"] = pdf_date
        if "/CreationDate" not in pdf.docinfo:
            pdf.docinfo["/CreationDate"] = pdf_date
            
        # Append XML Metadata stream
        xmp_template = f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.6-c015">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
    xmlns:pdfuaid="http://www.aiim.org/pdfuaid/ns/id/"
    xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/"
    xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#"
    xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">
   
   <dc:format>application/pdf</dc:format>
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>
   <dc:creator><rdf:Seq><rdf:li>ADA PDF Remediator</rdf:li></rdf:Seq></dc:creator>
   <xmp:CreateDate>{xmp_date}</xmp:CreateDate>
   <xmp:ModifyDate>{xmp_date}</xmp:ModifyDate>
   <xmp:MetadataDate>{xmp_date}</xmp:MetadataDate>
   <pdf:Producer>ADA PDF Remediator</pdf:Producer>
   
   <pdfuaid:part>1</pdfuaid:part>

   <pdfaExtension:schemas>
    <rdf:Bag>
     <rdf:li rdf:parseType="Resource">
      <pdfaSchema:schema>PDF/UA Identification Schema</pdfaSchema:schema>
      <pdfaSchema:namespaceURI>http://www.aiim.org/pdfuaid/ns/id/</pdfaSchema:namespaceURI>
      <pdfaSchema:prefix>pdfuaid</pdfaSchema:prefix>
      <pdfaSchema:property>
       <rdf:Seq>
        <rdf:li rdf:parseType="Resource">
         <pdfaProperty:name>part</pdfaProperty:name>
         <pdfaProperty:valueType>Integer</pdfaProperty:valueType>
         <pdfaProperty:category>internal</pdfaProperty:category>
         <pdfaProperty:description>Part of ISO 14289 standard</pdfaProperty:description>
        </rdf:li>
       </rdf:Seq>
      </pdfaSchema:property>
     </rdf:li>
    </rdf:Bag>
   </pdfaExtension:schemas>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

        meta_stream = pikepdf.Stream(pdf, xmp_template.encode("utf-8"))
        meta_stream.Type = pikepdf.Name("/Metadata")
        meta_stream.Subtype = pikepdf.Name("/XML")
        root.Metadata = meta_stream
        
        # Build ParentTree structure
        parent_tree_nums = pikepdf.Array()
        for idx, page_elems in enumerate(all_pages_struct_elems):
            parent_tree_nums.append(pikepdf.Integer(idx))
            parent_tree_nums.append(pdf.make_indirect(pikepdf.Array(page_elems)))
            
        parent_tree = pdf.make_indirect(pikepdf.Dictionary(Nums=parent_tree_nums))
        struct_tree_root = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name("/StructTreeRoot"),
            K=document_elem,
            ParentTree=parent_tree
        ))
        document_elem.P = struct_tree_root
        root.StructTreeRoot = struct_tree_root
        
        # Fix missing /ToUnicode mappings for fonts
        font_tounicode = {}
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == pikepdf.Name("/Font"):
                base_font = str(obj.get("/BaseFont", ""))
                if base_font and "/ToUnicode" in obj:
                    font_tounicode[base_font] = obj.ToUnicode
                    
        DEFAULT_TOUNICODE_CMAP = (
            "/CIDInit /ProcSet findresource begin\n"
            "12 dict begin\n"
            "begincmap\n"
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /Custom-ToUnicode def\n"
            "/CMapType 2 def\n"
            "1 begincodespacerange <00> <FF> endcodespacerange\n"
            "1 beginbfrange <00> <FF> <0000> endbfrange\n"
            "endcmap\n"
            "CMapName currentdict /CMap defineresource pop\n"
            "end end"
        )
        
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == pikepdf.Name("/Font"):
                if "/ToUnicode" not in obj:
                    base_font = str(obj.get("/BaseFont", ""))
                    if base_font and base_font in font_tounicode:
                        obj.ToUnicode = font_tounicode[base_font]
                    else:
                        cmap_stream = pikepdf.Stream(pdf, DEFAULT_TOUNICODE_CMAP.encode("utf-8"))
                        obj.ToUnicode = cmap_stream
                        
        print(f"[REMEDIATOR] Saving remediated PDF output: {output_path}")
        pdf.save(output_path)
        
    print("[REMEDIATOR] Pipeline completed successfully!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python remediate_pdf.py <input_pdf_path> <output_pdf_path>")
        sys.exit(1)
    remediate_single_pdf(sys.argv[1], sys.argv[2])
