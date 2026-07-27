# ADA PDF Remediator & Layout Research Platform

An automated PDF accessibility remediation engine and open-source research platform designed to transform complex, un-accessible PDF documents into fully compliant **PDF/UA-1 (ISO 14289-1)** and **WCAG 2.1** accessible PDFs.

---

## Key Features

- **Flatten-to-Figures Pipeline**: Automatically detects complex vector graphics, tables, and formula curves, flattens them into high-resolution visual crops, and injects tagged `/Figure` structure elements with mandatory `/BBox` and alt text attributes.
- **Document Catalog & Structure Tree Reconstruction**: Generates `/StructTreeRoot`, `/ParentTree`, `/MarkInfo`, and `/MCID` marked content tags required by screen readers.
- **CMap & Font Patching**: Automatically generates `/ToUnicode` mapping streams for legacy embedded fonts using metadata heuristics and OCR fallback.
- **Compliance Audit Suite**: Built-in CLI auditor (`check_compliance.py`) to verify PDF/UA-1 metadata, display preferences, structure tag trees, figure alternative text, font encodings, and marked content stream tagging.
- **Layout & Reading Order Research Framework**: Modular architecture with stubbed entrypoints (`remediator/reading_order.py`) and planning specs for researchers and open-source contributors.

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

## Quickstart

### 1. Environment Setup

Clone the repository and install dependencies in editable mode:

```bash
# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install core dependencies
pip install -r requirements.txt

# Or install as an editable package
pip install -e .
```

> **Note**: For font OCR fallback and page rasterization, ensure system packages `tesseract-ocr` and `poppler` are installed on your machine (`brew install tesseract poppler` on macOS).

---

## Usage

### Remediating a PDF Document

To remediate an un-accessible PDF and generate a PDF/UA-1 compliant document:

```bash
# Using CLI script
python remediate_pdf.py samples/physics/physics.pdf outputs/remediated_physics.pdf

# Or using installed CLI command
remediate-pdf samples/physics/physics.pdf outputs/remediated_physics.pdf
```

### Auditing Accessibility Compliance

To run the compliance audit suite on any PDF file:

```bash
# Using CLI script
python check_compliance.py outputs/remediated_physics.pdf

# Or using installed CLI command
check-compliance outputs/remediated_physics.pdf
```

### Programmatic Python API

```python
from remediator import remediate_single_pdf, run_compliance_check

# Remediate input PDF
remediate_single_pdf("input.pdf", "output_accessible.pdf")

# Audit output PDF
is_compliant = run_compliance_check("output_accessible.pdf", verbose=True)
print("Compliant:", is_compliant)
```

---

## Contributing to Research Tasks

We welcome open-source contributions! Active research proposals and tasks are documented under [`docs/planning/`](docs/planning/):

1. **Document Layout & Reading Order Recovery** ([`docs/planning/layout_reading_order_proposal.md`](docs/planning/layout_reading_order_proposal.md))
   - Code entrypoint: [`remediator/reading_order.py`](remediator/reading_order.py)
   - Focus: Implementing Recursive XY-Cut, LLM perplexity flow-sorting, and VLM zero-shot alignment.

2. **Image Alt-Text Generation** ([`docs/planning/alt_text_research_spec.md`](docs/planning/alt_text_research_spec.md))
   - Focus: Evaluating micro-VLMs (Florence-2, Moondream2) for domain-specific chart/math equation description.

For detailed guidelines on picking up these tasks, see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

This project is licensed under the MIT License.
