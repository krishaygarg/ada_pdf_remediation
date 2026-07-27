# ADA PDF Remediator & Layout Research Platform

An automated PDF accessibility remediation engine and research framework designed to make complex PDF documents fully accessible and compliant with **PDF/UA-1 (ISO 14289-1)** and **WCAG 2.1** standards.

---

## High-Level Overview

### The Problem We Are Solving

Screen readers and assistive technologies used by blind and visually impaired individuals rely on structural tags and explicit reading order embedded within a PDF's internal binary stream. 

Most standard PDFs—especially academic papers, technical reports, and complex documents—lack accessibility metadata. Their text streams are often compiled out of sequence across multiple columns, inline equations interrupt paragraphs, and figures, graphs, or tables lack alternative text descriptions and structural tags. As a result, screen readers either jump across columns out of order or fail to read critical content entirely.

### How We Do It

The ADA PDF Remediator automatically parses, restructures, and repairs PDF binary streams into fully accessible documents:

1. **Visual Component Segmentation & Flattening**: Detects complex overlapping tables, vector curves, and formulas, flattens them into high-resolution visual figure crops, and inserts tagged `/Figure` structure elements equipped with mandatory `/BBox` attributes and alternative text.
2. **Structural Tag Tree Reconstruction**: Generates a complete logical tag tree (`/StructTreeRoot`), parent mapping dictionary (`/ParentTree`), marked info tags (`/MarkInfo`), and marked content stream identifiers (`/MCID`) to define exact screen reader reading order.
3. **Font Character Map Repair**: Scans embedded fonts for missing `/ToUnicode` character mappings and dynamically constructs CMap streams using metadata heuristics and OCR fallback.
4. **Automated Compliance Auditing**: Evaluates remediated output documents against PDF/UA-1 metadata requirements, viewer display title preferences, structure trees, and font encoding rules.

---

## Directory Structure

```text
ADA_jun_23/
├── remediator/                # Core Python package
│   ├── __init__.py            # Package exports (remediate_single_pdf, run_compliance_check)
│   ├── pipeline.py            # Main PDF remediation & tag reconstruction pipeline
│   ├── compliance.py          # Accessibility compliance auditor engine
│   ├── content_filter.py      # Content stream parser, CTM tracker & operator filter
│   ├── reading_order.py       # Reading Order & Layout Recovery algorithms (Research Stubs)
│   ├── font_patcher.py        # Dynamic /ToUnicode CMap generator & OCR fallback
│   ├── utils.py               # Spatial math & bounding box merger utilities
│   └── config.py              # Environment & workspace configuration
├── docs/                      # Research specs & planning documents
│   └── planning/
│       ├── layout_reading_order_proposal.md  # Proposal for Layout & Reading Order recovery
│       ├── alt_text_research_spec.md        # Spec for VLM-based figure Alt-Text generation
│       └── research_timeline.md             # 3-Month research phase roadmap
├── samples/                   # Sample PDF files
├── check_compliance.py       # CLI runner for PDF accessibility audit
├── remediate_pdf.py           # CLI runner for PDF remediation pipeline
├── pyproject.toml             # Standard setuptools packaging metadata
├── requirements.txt           # Dependency specifications
├── README.md                  # Project overview & documentation
└── CONTRIBUTING.md            # Contributor guide & research onboarding
```

---

## Quickstart & Usage

### 1. Installation

```bash
# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

> **System Dependencies**: Ensure `tesseract` and `poppler` are installed on your system (`brew install tesseract poppler` on macOS).

### 2. Remediating a PDF Document

```bash
# Using CLI script
python remediate_pdf.py samples/physics/physics.pdf outputs/remediated_physics.pdf

# Or using installed CLI command
remediate-pdf samples/physics/physics.pdf outputs/remediated_physics.pdf
```

### 3. Auditing Accessibility Compliance

```bash
# Using CLI script
python check_compliance.py outputs/remediated_physics.pdf

# Or using installed CLI command
check-compliance outputs/remediated_physics.pdf
```

### 4. Python API

```python
from remediator import remediate_single_pdf, run_compliance_check

# Remediate input PDF
remediate_single_pdf("input.pdf", "output_accessible.pdf")

# Audit output PDF
is_compliant = run_compliance_check("output_accessible.pdf", verbose=True)
print("Compliant:", is_compliant)
```

---

## Research & Development Roadmap

Ongoing research tasks and technical specifications are located under [`docs/planning/`](docs/planning/):

1. **Document Layout & Reading Order Recovery** ([`docs/planning/layout_reading_order_proposal.md`](docs/planning/layout_reading_order_proposal.md))
   - Code entrypoint: [`remediator/reading_order.py`](remediator/reading_order.py)
   - Objective: Implementing Recursive XY-Cut heuristics, LLM perplexity flow-sorting, and VLM zero-shot alignment.

2. **Technical Image Alt-Text Generation** ([`docs/planning/alt_text_research_spec.md`](docs/planning/alt_text_research_spec.md))
   - Objective: Evaluating micro-VLMs (Florence-2, Moondream2) for domain-specific math formula and chart description.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on contributing to these research initiatives.
