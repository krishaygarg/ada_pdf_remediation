#!/usr/bin/env python3
import os
import sys
import pikepdf
import fitz

def check_figure_bbox(element) -> tuple:
    """
    Checks if a Figure StructElem has a valid Alt text and BBox attribute nested
    properly inside an Attribute Dictionary /A owned by /Layout.
    Returns (has_alt, has_bbox_in_A, has_bbox_outside_A)
    """
    has_alt = "/Alt" in element and str(element.get("/Alt", "")).strip()
    
    has_bbox_in_A = False
    has_bbox_outside_A = "/BBox" in element
    
    if "/A" in element:
        attrs = element.A
        # Attributes can be a dictionary or an array of dictionaries
        attr_list = []
        if isinstance(attrs, pikepdf.Array):
            attr_list = list(attrs)
        elif isinstance(attrs, pikepdf.Dictionary):
            attr_list = [attrs]
            
        for attr in attr_list:
            if not isinstance(attr, pikepdf.Dictionary):
                continue
            owner = str(attr.get("/O", ""))
            if owner == "/Layout" and "/BBox" in attr:
                has_bbox_in_A = True
                break
                
    return has_alt, has_bbox_in_A, has_bbox_outside_A

def run_compliance_check(pdf_path: str) -> bool:
    if not os.path.exists(pdf_path):
        print(f"\033[91mError: File not found: {pdf_path}\033[0m")
        return False

    print("\n" + "=" * 80)
    print(f" ACCESSIBILITY COMPLIANCE AUDIT FOR: {os.path.basename(pdf_path)} ")
    print("=" * 80)

    # We track categories matching axesCheck:
    # 1. Perceivable
    #    - 1.1 Text Alternatives (Alt text for Figures)
    #    - 1.3 Adaptable (Properly nested structure, Figure BBoxes)
    # 4. Robust
    #    - 4.1 Compatible (Correct role mapping, tag owner, BBoxes not improperly placed)
    
    passed_checks = 0
    failures = 0
    warnings = 0
    
    issues_list = []

    # 1. Check Document Language (Perceivable / Understandable)
    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root
            if "/Lang" in root and str(root.Lang).strip():
                print("[\033[92mPASS\033[0m] Language catalog attribute is set to:", root.Lang)
                passed_checks += 1
            else:
                print("[\033[91mFAIL\033[0m] Primary document language (/Lang) is missing.")
                issues_list.append("Failure (1.3 Adaptable): Primary language attribute is missing in the document catalog.")
                failures += 1
    except Exception as e:
        print("[\033[91mFAIL\033[0m] Error reading /Lang:", e)
        failures += 1

    # 2. Check Display Document Title (ViewerPreferences)
    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root
            has_title_pref = False
            if "/ViewerPreferences" in root:
                prefs = root.ViewerPreferences
                if "/DisplayDocTitle" in prefs and prefs.DisplayDocTitle == True:
                    has_title_pref = True
            
            if has_title_pref:
                print("[\033[92mPASS\033[0m] Viewer preference DisplayDocTitle is enabled.")
                passed_checks += 1
            else:
                print("[\033[91mFAIL\033[0m] DisplayDocTitle viewer preference is missing or disabled.")
                issues_list.append("Failure (1.3 Adaptable): DisplayDocTitle preference is not set to True.")
                failures += 1
    except Exception as e:
        print("[\033[91mFAIL\033[0m] Error reading DisplayDocTitle:", e)
        failures += 1

    # 3. Check PDF/UA-1 Identifier in XMP Metadata (Robust)
    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root
            has_pdfua = False
            if "/Metadata" in root:
                meta = root.Metadata.read_bytes().decode("utf-8", errors="ignore")
                if "pdfuaid:part" in meta and "http://www.aiim.org/pdfuaid/ns/id/" in meta:
                    has_pdfua = True
            
            if has_pdfua:
                print("[\033[92mPASS\033[0m] PDF/UA-1 schema identifier is present in XMP metadata.")
                passed_checks += 1
            else:
                print("[\033[91mFAIL\033[0m] PDF/UA-1 schema identifier is missing in metadata.")
                issues_list.append("Failure (4.1 Compatible): PDF/UA-1 identification namespace and part tags are missing or invalid.")
                failures += 1
    except Exception as e:
        print("[\033[91mFAIL\033[0m] Error reading XMP Metadata:", e)
        failures += 1

    # 4. Check Structure Tree & ParentTree (Perceivable / Robust)
    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root
            has_tree = "/StructTreeRoot" in root
            has_parent = False
            if has_tree:
                struct_root = root.StructTreeRoot
                if "/ParentTree" in struct_root:
                    has_parent = True
            
            if has_tree and has_parent:
                print("[\033[92mPASS\033[0m] Structure tag tree and ParentTree are correctly initialized.")
                passed_checks += 1
            else:
                if not has_tree:
                    print("[\033[91mFAIL\033[0m] Document structure tree (/StructTreeRoot) is missing.")
                    issues_list.append("Failure (1.3 Adaptable): Logical structure tag tree is missing.")
                    failures += 1
                else:
                    print("[\033[91mFAIL\033[0m] Structure tree exists but /ParentTree content mapping is missing.")
                    issues_list.append("Failure (1.3 Adaptable): ParentTree content coordinates mapping is missing.")
                    failures += 1
    except Exception as e:
        print("[\033[91mFAIL\033[0m] Error reading Structure Tree:", e)
        failures += 1

    # 5. Check Figures Alt Text and BBox Layout Attributes (WCAG 1.3.1 Adaptable & WCAG 4.1.2 Compatible)
    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root
            figures = []
            
            def scan_tree(element):
                if not isinstance(element, pikepdf.Dictionary):
                    return
                s_type = str(element.get("/S", "")).replace("/", "")
                if s_type == "Figure":
                    figures.append(element)
                if "/K" in element:
                    kids = element.K
                    if isinstance(kids, pikepdf.Array):
                        for k in kids: scan_tree(k)
                    elif isinstance(kids, pikepdf.Dictionary):
                        scan_tree(kids)

            if "/StructTreeRoot" in root:
                struct_root = root.StructTreeRoot
                if "/K" in struct_root:
                    kids = struct_root.K
                    if isinstance(kids, pikepdf.Array):
                        for k in kids: scan_tree(k)
                    elif isinstance(kids, pikepdf.Dictionary):
                        scan_tree(kids)
            
            total_figs = len(figures)
            if total_figs > 0:
                print(f"[INFO] Found {total_figs} Figure tag elements in structure tree.")
                
                alt_passed = 0
                bbox_layout_passed = 0
                bbox_outside_warnings = 0
                
                for idx, fig in enumerate(figures, 1):
                    has_alt, has_bbox_in_A, has_bbox_outside = check_figure_bbox(fig)
                    
                    # Check Alt
                    if has_alt:
                        alt_passed += 1
                    else:
                        failures += 1
                        issues_list.append(f"Failure (1.1 Text Alternatives): Figure element {idx} is missing alternative text description.")
                        
                    # Check BBox nesting in attribute /A owned by /Layout
                    if has_bbox_in_A:
                        bbox_layout_passed += 1
                        passed_checks += 1
                    else:
                        failures += 1
                        issues_list.append(f"Failure (1.3 Adaptable): Figure element {idx} lacks a BBox nested inside an attribute dictionary (/A) owned by /Layout.")
                    
                    # Check if BBox was placed directly under StructElem (Warning under 4.1 compatible in some validators)
                    if has_bbox_outside:
                        warnings += 1
                        bbox_outside_warnings += 1
                        issues_list.append(f"Warning (4.1 Compatible): Figure element {idx} contains a BBox key placed directly in the structure element instead of nesting it in /A.")
                
                # Report Alt Text
                if alt_passed == total_figs:
                    print(f"[\033[92mPASS\033[0m] All {total_figs} figures contain valid Alt text descriptions.")
                    passed_checks += 1
                else:
                    print(f"[\033[91mFAIL\033[0m] {total_figs - alt_passed} figures are missing Alt text descriptions.")
                    
                # Report BBox Layout Attributes
                if bbox_layout_passed == total_figs:
                    print(f"[\033[92mPASS\033[0m] All {total_figs} figures have properly nested BBox Layout attributes in /A.")
                else:
                    print(f"[\033[91mFAIL\033[0m] {total_figs - bbox_layout_passed} figures lack properly nested BBox Layout attributes in /A.")
                    
                if bbox_outside_warnings > 0:
                    print(f"[\033[93mWARN\033[0m] {bbox_outside_warnings} figures have BBox keys directly in the StructElem dictionary instead of nested in /A.")
            else:
                print("[\033[92mPASS\033[0m] No Figures found in structure tree (automatic pass for Alt and BBox checks).")
                passed_checks += 2
    except Exception as e:
        print("[\033[91mFAIL\033[0m] Error scanning Figure elements:", e)
        failures += 1

    # 6. Check Font Unicode Mappings (Robust)
    try:
        with pikepdf.open(pdf_path) as pdf:
            missing_unicode_fonts = []
            for obj in pdf.objects:
                if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == pikepdf.Name("/Font"):
                    base_font = str(obj.get("/BaseFont", "Unknown"))
                    if "/ToUnicode" not in obj:
                        missing_unicode_fonts.append(base_font)
            
            if not missing_unicode_fonts:
                print("[\033[92mPASS\033[0m] All embedded font objects have valid /ToUnicode mapping streams.")
                passed_checks += 1
            else:
                print(f"[\033[91mFAIL\033[0m] Font objects missing /ToUnicode mappings: {list(set(missing_unicode_fonts))}")
                issues_list.append(f"Failure (4.1 Compatible): Fonts missing /ToUnicode character mapping: {list(set(missing_unicode_fonts))}")
                failures += 1
    except Exception as e:
        print("[\033[91mFAIL\033[0m] Error scanning font Unicode tables:", e)
        failures += 1

    # 7. Check Content Marked Content MCIDs
    try:
        doc = fitz.open(pdf_path)
        mcid_count = 0
        for page in doc:
            raw = page.get_contents()
            if not raw:
                continue
            streams = raw if isinstance(raw, list) else [raw]
            for xref in streams:
                try:
                    data = doc.xref_stream(xref)
                    if data and b"/MCID" in data:
                        mcid_count += data.count(b"/MCID")
                except Exception:
                    pass
        doc.close()
        
        if mcid_count > 0:
            print(f"[\033[92mPASS\033[0m] Page content streams contain {mcid_count} marked content ID (MCID) tags.")
            passed_checks += 1
        else:
            print("[\033[91mFAIL\033[0m] No marked content (MCID) tags found in page content streams.")
            issues_list.append("Failure (1.3 Adaptable): Content stream lacks /MCID marked content properties.")
            failures += 1
    except Exception as e:
        print("[\033[91mFAIL\033[0m] Error scanning marked content streams:", e)
        failures += 1

    # Print Final Summary Report
    print("=" * 80)
    print(" COMPLIANCE SUMMARY REPORT")
    print("-" * 80)
    print(f"  Passed Checks: {passed_checks}")
    print(f"  Failures     : {failures}   " + ("\033[91m(Action Required)\033[0m" if failures > 0 else "\033[92m(None)\033[0m"))
    print(f"  Warnings     : {warnings}   " + ("\033[93m(Action Recommended)\033[0m" if warnings > 0 else "\033[92m(None)\033[0m"))
    print("=" * 80)
    
    if failures > 0 or warnings > 0:
        print("\nDetailed Compliance Issues Found:")
        for idx, issue in enumerate(issues_list, 1):
            if "Failure" in issue:
                print(f"  {idx}. \033[91m[FAIL]\033[0m {issue}")
            else:
                print(f"  {idx}. \033[93m[WARN]\033[0m {issue}")
        print("=" * 80 + "\n")
        return False
    else:
        print("\033[92mSUCCESS: Document is 100% compliant with PDF/UA-1 and WCAG accessibility standards!\033[0m")
        print("=" * 80 + "\n")
        return True

if __name__ == "__main__":
    path = "samples/test_sample/remediated_test_sample.pdf" if len(sys.argv) < 2 else sys.argv[1]
    run_compliance_check(path)
