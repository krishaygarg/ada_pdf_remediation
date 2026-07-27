# Document Layout Detection & Reading Order Recovery: Summer Research Proposal

## Introduction & Research Novelty: The "What" and "Why"

### What We Are Doing
The goal of this summer project is to design a system that ingests a raw PDF document and automatically reconstructs its layout elements into a logically ordered reading tree. 

When a visually complex page contains multiple columns, tables, headers, and sidebars, the system must:
1.  Determine the correct linear sequence (reading order) of the text.
2.  Identify hierarchical relationships between elements (e.g., matching captions to figures, or paragraphs to their headers).
3.  Map these ordered elements back to the physical characters in the PDF byte stream without changing the layout coordinates.

### Why We Are Doing It (The Accessibility Need)
Screen readers (text-to-speech tools used by blind or visually impaired users) do not read text based on how it looks on the page; they read characters in the exact order they are written in the PDF's raw binary stream. 

In PDFs compiled by standard software (especially double-column academic papers), this stream order is often scrambled due to the compiler appending text blocks out of sequence. A screen reader will read across columns, interrupt sentences with floating figures, or read footnotes in the middle of a paragraph. To make a PDF accessible (compliant with WCAG 2.1 and PDF/UA-1 standards), we must inject an XML-like tree catalog (`/StructTreeRoot`) that explicitly defines the correct reading order.

### Why This is Novel Research
Most existing solutions are heavily supervised (requiring massive manually labeled document layout training sets) or purely visual (using decoders that transcribe images into text but lose all coordinate connections to the original PDF characters, which breaks document remediation).

We are exploring a **Zero-Labeling framework** that combines classical spatial layout heuristics with pre-trained, out-of-the-box models. This project investigates:
*   How pre-trained Large Language Models (LLMs) can perform **unsupervised grammatical flow-sorting** by scoring the transition perplexity between adjacent text blocks.
*   How pre-trained Vision-Language Models (VLMs) can transcribe the page, and how we can use **sequence alignment** to project this visual reading order back onto the physical PDF character positions.

---

## 1. Problem Definition & Constraint Scope

### Input / Output Definition
*   **Input:** A raw, single PDF document containing pages, text drawing operations, and visual graphics/borders.
*   **Output:** The logically ordered sequence of text blocks matching human reading flow, and a hierarchical relation tree mapping logical blocks (e.g., matching captions to figures, or paragraphs to their parent headers).

### The "Missing Link" in the Current System
Right now, our pipeline parses text in the raw binary byte order. **There is no layout analysis, column sorting, reading order recovery, or hierarchical grouping.** The missing link we must implement is the intermediate parsing module that analyzes the layout structure and outputs an ordered representation before writing the final `/StructTreeRoot` tree catalog.

### Target Performance Constraints
Every proposed approach must be evaluated against these core thresholds:
*   **Accuracy:** The reconstructed text sequence must closely match the reference reading flow.
*   **Robustness:** Must survive academic layout anomalies (column-spanning tables, inline math, and footnotes).
*   **Annotation Budget:** **Zero manual data labeling required.**
*   **Compute Footprint:** Must run locally on standard laptops ($\le 4\,\text{GB}$ VRAM).

---

## 2. Survey of Method Families: Research Ideas to Explore

Below are the three general families of approaches to investigate. You are encouraged to search for academic papers (on Google Scholar, arXiv, or ACL Web) representing these families and summarize their findings for the literature review:

### Family A: Classical & Geometric Algorithms
*   **Core Idea:** Using the spatial geometry of the text blocks on the page (coordinates, sizes, alignments) to group and order them.
*   **Things to search for:** Recursive XY-Cut algorithms, Run-Length Smearing Algorithms (RLSA), whitespace projection profile analysis, and document page segmentation.
*   **Goal:** Research how these methods split columns and why they fail when column-spanning tables or inline equations are introduced.

### Family B: Pre-trained Layout & OCR Parsers
*   **Core Idea:** Using pre-trained visual object detection models to locate and label page objects (e.g., titles, headers, paragraphs, figures, tables).
*   **Things to search for:** LayoutParser, PubLayNet models, and bounding box category classification.
*   **Goal:** Research how layout box detection can be used as a pre-processing step, and how these models handle reading sequence sorting.

### Family C: Unsupervised Sequence & Flow Sorting
*   **Core Idea:** Using natural language models or visual decoders out-of-the-box (without retraining or labeling) to predict the logical flow of text.
*   **Things to search for:** Pointer networks, text transition perplexity using pre-trained language models, visual document transformers (like Nougat or Florence-2), and sequence alignment.
*   **Goal:** Research how local language models can score transitions between text blocks to resolve column-split ambiguities, or how sequence alignment can project transcribed text back onto raw coordinates.
