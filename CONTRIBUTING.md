# Contributing to ADA PDF Remediator & Research

Thank you for your interest in contributing! This codebase is designed to be accessible for both core open-source software contributions and academic research tasks outlined under [`docs/planning/`](docs/planning/).

---

## 1. Development Workflow

### Environment Setup
1. Fork and clone the repository.
2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies in editable mode:
   ```bash
   pip install -e ".[experimental]"
   ```
4. Verify your environment by running a compliance check on a sample PDF:
   ```bash
   python check_compliance.py samples/physics/physics.pdf
   ```

---

## 2. How to Contribute to Planning Tasks (`docs/planning/`)

Our active research roadmap is organized into proposals and specs inside `docs/planning/`. Here is how you can pick up and contribute to each major area:

### A. Layout & Reading Order Recovery
- **Reference Spec**: [`docs/planning/layout_reading_order_proposal.md`](docs/planning/layout_reading_order_proposal.md)
- **Target File**: [`remediator/reading_order.py`](remediator/reading_order.py)
- **Goal**: In complex double-column academic papers or multi-layout documents, PDF byte streams often scramble reading order. We need algorithms to recover human-like reading order.

**Tasks to pick up in `remediator/reading_order.py`**:
1. **Phase 1: Data Preparation (`extract_text_blocks`)**: Implement PDF text block parsing and JSON extraction using `pdfplumber` or `fitz`.
2. **Phase 2: Baseline Heuristics (`heuristic_xy_cut`)**: Implement the classical Recursive XY-Cut algorithm for 2-column document splitting.
3. **Phase 2: Evaluation Metrics (`calculate_evaluation_metrics`)**: Implement sequence alignment metrics (Kendall's Tau, Levenshtein edit distance, BLEU) comparing predicted reading order against ground truth.
4. **Phase 3: Advanced Models (`unsupervised_llm_sort` & `zero_shot_vlm_align`)**: Implement LLM text transition perplexity scoring or VLM sequence projection.

---

### B. Technical Image Alt-Text Generation
- **Reference Spec**: [`docs/planning/alt_text_research_spec.md`](docs/planning/alt_text_research_spec.md)
- **Target Folder**: [`experimental/math_vlm/`](experimental/math_vlm/)
- **Goal**: Generate high-fidelity descriptions for mathematical formulas, charts, and diagrams extracted from PDFs.

**Tasks to pick up**:
1. **Family A (Quantized Micro-VLMs)**: Benchmark lightweight models (e.g. `microsoft/Florence-2-base`, Moondream2) on image crops of math formulas and line graphs.
2. **Family B (Domain Fine-Tuning)**: Extend [`experimental/math_vlm/finetune.py`](experimental/math_vlm/finetune.py) to train PEFT/LoRA adapters on formula/chart datasets.
3. **Family C (Router Classifier)**: Build a lightweight classifier (e.g., MobileNetV4) that routes figure crops to specialised micro-models (Math vs Chart vs Diagram).

---

### C. Compliance Auditor Enhancements
- **Target File**: [`remediator/compliance.py`](remediator/compliance.py)
- **Goal**: Expand WCAG 2.1 AAA and PDF/UA-1 rules checked by the compliance auditor (e.g. table header `/TH` tagging checks, link annotation `/Link` verification).

---

## 3. Code Style & PR Guidelines

- **Python Standard**: Use PEP 8 styling conventions with clear docstrings and type hints.
- **No Hardcoded Machine Paths**: Use workspace-relative paths (`os.path.dirname(...)` or `remediator.config.LOCAL_TMP`) instead of absolute user directory paths.
- **Verification**: Before submitting a PR, run:
  1. `python remediate_pdf.py samples/physics/physics.pdf tmp/test.pdf`
  2. `python check_compliance.py tmp/test.pdf`
  Ensure all automated checks pass cleanly.
