# Honesty

The design principle behind most of the decisions here, stated once so the rest makes sense.

**Never make a document look more conformant than it is.**

It is written down because it is not obvious. Every incentive in accessibility tooling points the other way: scores are visible, readers are not, and the cheapest way to raise a score is to stop measuring the thing that is wrong. All three of the defects below did exactly that, and all three survived because something reported success.

## Three that got through

### The identifier was in the wrong namespace

The XMP packet declared the PDF/UA identifier in `http://www.aiim.org/pdfuaid/ns/id/`. ISO 14289-1 clause 5 defines it as `http://www.aiim.org/pdfua/ns/id/`. The conventional *prefix* is `pdfuaid`; the URI path segment is `pdfua`. One repeated syllable.

**Every document this project had ever produced was therefore unidentifiable as PDF/UA by a conforming validator.**

It survived for two reasons. The packet looks correct at a glance, since it visibly contains `<pdfuaid:part>1</pdfuaid:part>`. And the local auditor searched for the same incorrect URI the writer emitted, so it confirmed its own defect and reported full compliance.

| Checker | Verdict on the same file |
|---|---|
| The project's own auditor | 100% compliant |
| axesCheck | PDF/UA 100, WCAG 100, 0 errors |
| veraPDF 1.30.2 | **Not compliant.** Fails ISO 14289-1 rule 5-1 |

Two of the three agreed with each other and were wrong. This is why the audit engine is now cross-checked against veraPDF in CI, with a directional invariant: if the reference implementation rejects a document, this engine must not call it clean.

### The character map was destroying the text

The fallback filled every unresolved character code with a space, and every printable ASCII position with the corresponding ASCII character. Computer Modern, which is what TeX produces, does not place characters at ASCII positions, and its fonts carry no `/Encoding` in the PDF at all: the mapping lives inside the embedded font program, which the fallback never read.

```
source      'Physics 7A Discussion 3 ... Sept 10–11 ... • Motion in two dimensions'
remediated  'Physics 7A Discussion 3 ... Sept 10{11 ...   Motion in two dimensions'
```

| | In the source | After remediation | Now |
|---|---|---|---|
| En dash | 1 | **0** | 1 |
| Increment, `∆` | 4 | **0** | 4 |
| Minus, `−` | 1 | **0** | 1 |
| Bullets | 5 | **0** | 5 |
| Spurious `{` | 0 | **1** | 0 |
| Similarity to source | | 98.72% | **99.49%** |

Code 123 is an en dash in Computer Modern, not an opening brace. Every formula in the document lost its operators.

The file passed veraPDF and scored 100 on axesCheck throughout, because a `/ToUnicode` map existed and every code resolved to *something*. Both checkers verify that codes are mapped; neither verifies that the mapping means anything. That gap is now condition `10-003`, which extracts the map and reports when most codes resolve to a space or a replacement character.

The remaining 0.51% is ligature decomposition, `ﬁ` becoming `fi`, which is deliberate so that searching for "office" matches.

### The headline feature did not exist

The README described detecting complex regions, flattening them into figure crops, and inserting `/Figure` elements with mandatory `/BBox` attributes and alternate text. It was the project's lead capability.

**No `/Figure` element was ever produced.** The list of complex regions was initialised empty and never filled, and the bounding box merger was imported and never called. Every image was wrapped as an artifact instead, which tells assistive technology to skip it, so images were not merely undescribed but unreachable.

The web interface reported on this with a scorecard reading `100% COMPLIANT` and six green ticks. The scorecard was static markup. The audit result came back from the API and was never read, and the progress indicator above it advanced on a timer at 500, 1800, 3200 and 4500 milliseconds, printing log lines about work that was not happening.

A document can be wrong, a checker can be wrong, and an interface can assert a result nobody computed. All three were true here at once.

## How the principle shows up in the code

**Unresolvable codes are omitted and counted.** A missing character is visible to a reader; a substituted one is not.

**No placeholder alternate text.** A figure nobody has described is reported as undescribed. Writing `Alt="Image"` satisfies a checker, tells a reader nothing, and hides the work that remains.

**The default produces a non-conformant document when a figure has no description.** `--undescribed-images artifact` will mark them decorative and the document will conform, and the tradeoff is stated where the choice is made rather than decided silently.

**A rule that crashes makes the report non-conformant.** A check that failed to run must never be indistinguishable from a check that found nothing.

**Truncated reports say how much they withheld.** A report listing twelve contrast failures on a page with three hundred implies the page has twelve.

**The auditor is cross-checked against an independent implementation.** An auditor written by the same people as the writer it audits is not evidence, as the namespace defect demonstrated.

**The interface renders results rather than asserting them.** Two tests exist purely because of what was there before: the script must contain no `setTimeout`, and the markup must contain no static tick or the string `100% compliant`.

**Coverage is stated as a fraction.** 34 conditions of the 87 that software can determine, out of 136 in the protocol. `coverage_summary()` reports the gap, and a test asserts the implemented count stays below the determinable count so the engine cannot quietly start claiming completeness.
