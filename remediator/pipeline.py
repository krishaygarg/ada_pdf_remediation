import os
import io
import shutil
import pikepdf
import pdfplumber
from datetime import datetime, timezone
from pdf2image import convert_from_path
from PIL import Image

from .config import LOCAL_TMP
from .utils import merge_bboxes
from .content_filter import filter_page_content
from .font_patcher import generate_tounicode_cmap
from .ocr_engine import generate_ocr_text_ops

def remediate_single_pdf(input_path: str, output_path: str):
    """
    Performs Flatten-to-Figures PDF accessibility remediation.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input PDF not found: {input_path}")
        
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
                
            # Detect standalone raster image objects
            images = getattr(plumbpage, 'images', [])
            for elem in images:
                x0 = float(elem.get('x0', 0))
                top = float(elem.get('top', 0))
                x1 = float(elem.get('x1', 0))
                bottom = float(elem.get('bottom', 0))
                w = x1 - x0
                h = bottom - top
                if w < 5 and h < 5:
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
                        
            # Check if page is a scanned document (lacks live text operators)
            page_text = (plumbpage.extract_text() or "").strip()
            if len(page_text) < 10:
                print(f"  - Scanned image page detected! Generating invisible OCR text layer...")
                ocr_ops, ocr_elems, mcid = generate_ocr_text_ops(
                    input_path, page_idx, page_width, page_height, mcid, pdf, document_elem
                )
                if ocr_ops:
                    final_ops.extend(ocr_ops)
                    page_struct_elems.extend(ocr_elems)

            # Append 'Q' to restore default page coordinates
            final_ops.append(([], pikepdf.Operator("Q")))
            
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
                    
        print(f"[REMEDIATOR] Patching missing /ToUnicode mappings...")
        for idx, obj in enumerate(pdf.objects):
            if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == pikepdf.Name("/Font"):
                base_font = str(obj.get("/BaseFont", ""))
                if "/ToUnicode" not in obj:
                    print(f"  - Font {idx} ({base_font}) missing /ToUnicode.")
                    if base_font and base_font in font_tounicode:
                        print(f"    * Using cached mapping for {base_font}")
                        obj.ToUnicode = font_tounicode[base_font]
                    else:
                        print(f"    * Generating dynamic CMap for {base_font}...")
                        generated_cmap = generate_tounicode_cmap(obj, base_font, input_path)
                        print(f"    * Injecting stream for {base_font}...")
                        cmap_stream = pikepdf.Stream(pdf, generated_cmap.encode("utf-8"))
                        obj.ToUnicode = cmap_stream
                        
        print(f"[REMEDIATOR] Saving remediated PDF output: {output_path}")
        pdf.save(output_path)
        
    print("[REMEDIATOR] Pipeline completed successfully!")
    
    # Clean up temporary raster images if any remain
    pass
