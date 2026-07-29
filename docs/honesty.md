# Honesty

The design principle behind most of the decisions here, stated once so the rest makes sense.

**Never make a document look more conformant than it is.**

## Where it came from

An earlier version of this project filled every unresolved character code with a space, and every printable ASCII position with the ASCII character. Computer Modern, which is what TeX produces, does not place characters at ASCII positions.

The result, on the bundled physics sample:

| | In the source | After remediation |
|---|---|---|
| En dash | 1 | 0 |
| Increment (∆) | 4 | 0 |
| Minus (−) | 1 | 0 |
| Bullets | 5 | 0 |
| Spurious `{` | 0 | 1 |

`Sept 10–11` became `Sept 10{11`. Every formula lost its operators.

The file scored **100/100** on a commercial accessibility checker and passed veraPDF, because a character map existed and every code resolved to something.

A document that passes and cannot be read is worse than one that fails honestly. Nobody returns to a document marked done.

## How it shows up in the code

**Unresolvable codes are omitted and counted.** A missing character is visible to a reader; a substituted one is not.

**No placeholder alternate text.** A figure nobody has described is reported as undescribed. Writing `Alt="Image"` satisfies a checker and tells a reader nothing, while hiding the work that remains.

**The default produces a non-conformant document when a figure has no description.** `--undescribed-images artifact` will mark them decorative and the document will conform, and the tradeoff is stated where the choice is made rather than decided silently.

**A rule that crashes makes the report non-conformant.** A check that failed to run must never be indistinguishable from a check that found nothing.

**Truncated reports say how much they withheld.** A report listing twelve contrast failures on a page with three hundred implies the page has twelve.

**The auditor is cross-checked against veraPDF.** The old checker looked for the PDF/UA identifier under the same wrong namespace the pipeline wrote, so it confirmed the defect. CI now asserts that if veraPDF rejects a document, this engine does not call it clean.

**The interface renders results rather than asserting them.** It previously displayed a hardcoded scorecard reading "100% COMPLIANT" regardless of the audit.
