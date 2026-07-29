# Image Alt Text Generation for Document Accessibility: Research Proposal

## Introduction & Research Novelty: The "What" and "Why"

### What We Are Doing
The goal of this project is to design and evaluate a highly efficient system that takes an isolated image crop (representing a chart, graph, equation, or diagram) as input and directly generates a high-quality alternative text (Alt text) description as output. 

This research focuses on:
1.  **Image-to-Text Mapping:** Translating visual graphics directly into semantically rich descriptions suitable for accessibility.
2.  **Domain Specialization:** Generating highly accurate representations for specialized academic/technical visual content (such as mathematical equations, plots, line graphs, and flowcharts).
3.  **Resource & Cost Optimization:** Achieving near-state-of-the-art alt-text quality using inexpensive, lightweight models that can run locally on standard hardware or with minimal API costs.

*Note: Layout analysis, document parsing, and locating/extracting images from pages are out of scope for this spec; we assume the input is a pre-isolated image crop.*

### Why We Are Doing It (The Accessibility Need)
Visually impaired users relying on screen readers cannot access critical information locked inside image crops of academic, financial, or technical documents. 

Standard alt-text generation is particularly inadequate for technical content:
*   **Equations:** A math equation rendered as an image crop is completely unreadable unless converted to LaTeX, MathML, or natural spoken English.
*   **Graphs and Charts:** Line graphs, scatter plots, and bar charts contain trends and precise data values. Without descriptive alt text detailing the axis labels, legends, and key trends, the data is completely lost.

To comply with WCAG 2.1 Success Criterion 1.1.1 (Non-text Content) and PDF/UA standards, we need an automated, high-fidelity mapping from raw image crop to specialized alt text.

### Why This is Novel Research
Generating alt text for technical images is historically treated in one of two ways: using expensive, massive closed-source VLMs (like GPT-4o or Claude 3.5 Sonnet) which is cost-prohibitive at scale, or using generic captioning models (like BLIP-base) which yield over-simplified, useless descriptions (e.g., "a blue line graph").

Our research investigates the trade-off between cost, compute footprint, and domain accuracy:
*   **Domain-Tuned Micro-VLMs:** How lightweight visual-language models ($\le 2\text{B}$ parameters) can be fine-tuned or adapted to match or exceed frontier models on specific technical tasks (like OCR-ing complex formulas or summarizing plot directions).
*   **Compute-Efficient Processing:** Evaluating quantized models (4-bit/8-bit) and CPU-friendly model architectures to enable local, low-latency deployment on standard developer or user machines without requiring expensive cloud GPUs.

---

## 1. Problem Definition & Constraint Scope

### Input / Output Definition
*   **Input:** An isolated image crop of a document figure, chart, flowchart, or math expression.
*   **Output:** A high-quality, descriptive alternative text string that translates the visual content into readable/spoken text.

### The "Missing Link" in the Current System
Currently, document remediation pipelines use static placeholders (e.g., `Alt="Image"`) when tagging figures. The missing link is an efficient, direct image-to-alt-text engine that ingests the image crop, routes it to an appropriate lightweight processor, and returns the domain-specific descriptive string.

### Target Performance Constraints
Every proposed approach must be evaluated against these core thresholds:
*   **Domain Fidelity:** Mathematical equations must be translated into correct mathematical notation (e.g., LaTeX or spoken math equivalence). Charts and graphs must have axes, legends, and main trends described accurately without hallucinated data.
*   **Low Compute/Financial Cost:** Must run locally on standard developer hardware (constrained to $\le 2\,\text{GB}$ VRAM or CPU-only) or operate on a fraction-of-a-cent budget per image.
*   **High Latency Efficiency:** Generation must happen within acceptable times (e.g., $\le 1.5$ seconds per image crop) to support interactive or batch document processing.

---

## 2. Survey of Method Families: Research Ideas to Explore

Below are the three general families of approaches to investigate. You are encouraged to search for academic papers (on Google Scholar, arXiv, or ACL Web) representing these families and summarize their findings for the literature review:

### Family A: Quantized & Optimized Generalist VLMs
*   **Core Idea:** Running small general-purpose vision-language models locally using quantization and highly efficient inference engines.
*   **Things to search for:** Quantized Florence-2 (e.g. `microsoft/Florence-2-base` in ONNX/TensorRT format), Moondream2, Qwen2-VL-2B, and llama.cpp-based vision inference.
*   **Goal:** Research the baseline zero-shot accuracy of these quantized models on charts/equations, and how to optimize prompts to force concise, screen-reader-compliant outputs without model size bloat.

### Family B: Domain-Specific Fine-Tuning (Math & Charts)
*   **Core Idea:** Fine-tuning lightweight base models directly on specialized visual datasets to maximize performance on specific formats.
*   **Things to search for:** Fine-tuning BLIP/Florence-2 on ChartQA, PlotQA, or LaTeX math datasets (like PDFFormula or Mathpix clones).
*   **Goal:** Research how parameter-efficient fine-tuning (PEFT/LoRA) behaves on visual chart/math translation tasks, and whether a 2B parameter domain-tuned model can outperform a zero-shot 8B or 70B parameter model.

### Family C: Classifier-Guided routing to Specialized Micro-Models
*   **Core Idea:** Using a very small, extremely fast image classifier (e.g., a MobileNetV4 or a tiny ResNet) to determine the category of the crop (e.g., Formula vs. Graph vs. Diagram), then routing it to a micro-model custom-tuned for that specific data type.
*   **Things to search for:** Multi-expert visual systems, lightweight image categorization, and routed inference pipelines.
*   **Goal:** Evaluate the cost-to-accuracy trade-off of running a routing classifier + specialized micro-model vs. running a single multi-task VLM. Determine how fallback behaviors operate when classification is uncertain.

---

## 3. Prior Art: What Another Team Already Learned

[ASUCICREPO/PDF_Accessibility](https://github.com/ASUCICREPO/PDF_Accessibility) is an ASU and AWS remediation pipeline that generates alt text with a hosted VLM (Amazon Nova Pro, having moved off Claude 3.5 Sonnet in their V2 release). It is MIT licensed, so the prompt is readable. Two findings there are worth adopting rather than rediscovering, and one is worth treating as a warning.

### 3.1 Requirement: spoken-math needs explicit end delimiters

Their prompt requires every symbol, number and operator to be spelled out, and marks where each subscript and superscript **ends**:

| Rendered | Required alt text |
|---|---|
| `2(4y+1)=3y` | "2 open parenthesis 4 y plus 1 close parenthesis equals 3 y" |
| `Fᵢ = mᵢa²` | "F with subscript i end subscript equals m with subscript i end subscript a to the power of 2" |
| `Fₐ/ₓ^(n+1)` | "F with subscript a divided by x end subscript with superscript n plus 1 end superscript" |

The `end subscript` and `end superscript` markers are the part that matters and the part that is easy to leave out. Without them a screen reader gives no cue where the script closes, so `a^(n+1)` and `a^n + 1` are read identically. A description that is correct except for a missing delimiter is not partially useful; for an equation it is wrong.

**Requirement.** Any provider that describes formulas must emit explicit open and close markers for every level of sub- and superscript. The evaluation set must include at least one nested case, because that is where the convention earns its cost.

### 3.2 Requirement: the crop alone is not enough input

The spec above scopes input to "a pre-isolated image crop". Their V2 release notes record adding **spatial context** specifically because crop-only generation was not good enough. They pass the entire page text with the target image marked and every other image on the page marked differently:

```
... the whole page content, wherever you see "<OTHER IMAGE>" these are other
images on the page. The main image is the one with the tag "<IMAGE INTERESTED>"
```

The model is then instructed to locate the target, decide which surrounding text belongs to it, and explicitly assume that text near a *different* image is not relevant.

This is the difference between a caption match and a guess. On a page with two figures and a short paragraph between them, a provider that cannot tell which caption is which will confidently attach the wrong one, and that failure is invisible to any checker.

**Requirement.** The provider interface must carry page text with the target figure's position marked within it, not just the nearby text. `FigureContext` should be extended before anyone writes a provider against it, so that a crop-only provider is a deliberate choice rather than the only thing the interface permits.

### 3.3 Warning: they iterated hard on this and it is still wrong

Their prompt carries a feedback block written to the model, preserved here verbatim because of what it admits:

> **`<FEEDBACK>`** You tend to make mistakes when multiple images are present with small amounts of text in between. In such cases, choose the correct text for the alt text.
> **ALERT** Be careful when you are describing the subscript and superscripts in the alt text. Make sure you are describing them correctly. for subscripts you are making so many mistakes. you must firts decide if this is the part of subscript or not and then go ahead.
> **ALERT** Always mention end of superscript and subscript, you are not describing end of subscript and superscript properly.
> **`</FEEDBACK>`**

Read this as data. It is a team that changed model families, added spatial context, rewrote their math prompting across two releases, and still needed to tell the model in capital letters that it keeps getting subscripts wrong. The two failure modes they could not eliminate are exactly the two this spec cares most about: multi-figure attribution and nested script boundaries.

The consequence for this project is not that the work is hopeless. It is that **the decline path is the deliverable**, not a fallback. A provider must return `AltTextResult(text=None)` on the cases it cannot get right, and the research question that matters most is therefore not "how good is the description" but **"can the model tell when it is wrong?"** A 2B model that declines on nested subscripts and describes bar charts well is more useful here than a frontier model that answers everything with uniform confidence.

### 3.4 Suggested addition to the evaluation plan

The performance constraints in section 1 measure fidelity, cost and latency. Add selective risk, which is what the paragraph above implies:

*   **Coverage:** the fraction of figures the provider attempts.
*   **Selective accuracy:** accuracy on attempted figures only.
*   **Miss rate:** the fraction of attempted figures that were wrong, which is the number that actually harms readers.

A provider is better than the baseline only if it lowers the miss rate at equal or better coverage. Reporting accuracy without coverage hides exactly the tradeoff being made.

