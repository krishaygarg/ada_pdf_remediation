# Contributing

Thanks for looking. This project has two kinds of work: engineering, which is well defined and reviewable in small pieces, and research, which is specified under [`docs/planning/`](docs/planning/) and is where the interesting problems are.

## Getting set up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

brew install poppler tesseract                  # macOS
sudo apt install poppler-utils tesseract-ocr    # Debian and Ubuntu
```

```bash
make check   # lint, types and tests, the same gates CI runs
make demo    # remediate the bundled sample and audit the result
```

Optionally install [veraPDF](https://verapdf.org/software/) to run the conformance tests locally. They skip without it, and CI runs them either way.

## The one rule

**Never make a document look more conformant than it is.**

This project shipped a character map fallback that filled every unresolved code with a space. Checkers were satisfied, scores hit 100, and the extracted text had its en dashes replaced with braces and its mathematical operators deleted. The document passed and could not be read.

So: if the tool cannot determine something, it reports that it cannot. Placeholder alternate text, guessed characters, and figures hidden behind artifact tags to clear a rule are all off the table. An honest failure is actionable; a false pass is not.

## Where the work is

### A. Conformance rules, the biggest and most tractable lane

The [Matterhorn Protocol 1.1](https://pdfa.org/resource/matterhorn-protocol/) defines 31 checkpoints and 136 failure conditions. 87 are determinable by software. This implements **42 across 20 checkpoints**, so roughly **45 machine-checkable conditions remain**.

Each is a small, self-contained piece of work: one function, one fixture, one test.

```python
@rule(
    RuleMetadata(
        condition="15-005",
        checkpoint_name="Tables",
        summary="A header cell does not declare its scope",
        clause="7.5",
        wcag=("1.3.1",),
    )
)
def header_cells_declare_scope(context: DocumentContext) -> Iterator[Finding]:
    for node in context.nodes_with_role("TH"):
        if not _has_scope(node):
            yield Finding(
                condition="15-005",
                message="A TH cell does not declare /Scope.",
                location=node.location(),
                remedy="Add /A << /O /Table /Scope /Row >> or /Column.",
            )
```

Drop that in a module under `remediator/audit/rules/` and it is live. The registry imports the package automatically.

Largely or wholly unimplemented checkpoints, in rough order of how often they matter:

| Checkpoint | Area | Notes |
|---|---|---|
| 15 | Tables | Header associations, `/Headers`, spans, irregular tables |
| 16 | Lists | Nesting, `/ListNumbering`, label and body pairing |
| 14 | Headings | Strong structure, `/H` versus numbered levels |
| 19 | Notes and references | Identifiers, back references |
| 18 | Page headers and footers | Pagination artifacts, running heads |
| 20 | Optional content | Configuration and naming requirements |
| 21 | Embedded files | Association and description |
| 24 | Non-interactive forms | Field labelling |
| 27 | Navigation | Outlines, page labels, destinations |
| 09 | Appropriate tags | The long tail of structure semantics |

Open an issue with the **Conformance rule** template. It asks for the condition identifier, the ISO clause and a fixture plan, which is what a reviewer needs.

### B. Human-judgement conditions, an unbuilt feature area

47 conditions require a person. No open source tool has a workflow for that, and the pieces are clear enough to build:

- a triage queue, generated from the machine report
- evidence capture, so a reviewer sees the page crop and the tag path rather than an object number
- a signoff record that travels with the document and survives a re-run

This is a genuine feature, not busywork. It is the difference between a document that passes a validator and one that has actually been checked.

### C. Automatic fixes

Detection and repair are separate. Every rule can grow an `autofix` the pipeline applies, with a round-trip test proving the fix clears the rule without breaking another. That roughly doubles the rule backlog and is a good way in if you prefer changing documents to inspecting them.

`RemediationStatus` is the vocabulary for the outcome, and it is tracked separately from severity because the two answer different questions. Severity says how bad a finding is. Status says what was done about it, and a report carrying only severity cannot tell a finding nobody tried to fix from one a fix was attempted on and failed.

| Status | Meaning |
|---|---|
| `NOT_ATTEMPTED` | The default. No repair exists, or none ran. |
| `REMEDIATED` | The problem is gone. |
| `FAILED` | A repair ran and could not clear it. `remediation_detail` is required. |
| `NEEDS_PERSON` | Automation should not decide this. Not a failure. |

An autofix returns `finding.as_remediated(...)`, `as_failed(...)` or `as_needing_a_person(...)`. A repair that cannot complete must report `FAILED` with a reason rather than returning quietly, because a fix that silently did nothing is how a tool ends up claiming to have repaired a document it did not touch.

### D. PDF/UA-2 (ISO 14289-2:2024)

An entirely separate profile, not backward compatible with UA-1, adding MathML, new structure types and comprehensive annotation requirements. veraPDF already validates `-f ua2`, so the oracle is ready. The most ambitious lane on the board and completely untouched.

### E. Research

Both tracks have written specifications. **The algorithm bodies in [`remediator/reading_order.py`](remediator/reading_order.py) are deliberately unimplemented**; please leave the scaffolding around them alone and fill those in.

**[Layout and reading order](docs/planning/layout_reading_order_proposal.md).** The harness is built and waiting:

```bash
ada-ro-bench --list-strategies
ada-ro-bench datasets/example.jsonl
```

Every strategy currently ties with the `stream-order` baseline, because the functions return their input. Phase 1 is `extract_text_blocks`, which produces the datasets the harness reads. Phase 2 is `calculate_evaluation_metrics`, after which the leaderboard means something. Phase 3 is any of the three algorithms. CI posts the leaderboard on pull requests touching that code.

To try an approach without touching the repository, register a strategy through the `ada_pdf_remediator.reading_order` entry point group from your own package.

**[Technical image alt text](docs/planning/alt_text_research_spec.md).** `remediator.alttext` defines the provider interface. Implement `describe(FigureContext) -> AltTextResult` and register through `ada_pdf_remediator.alttext`. A provider that cannot describe a figure must return `text=None` rather than inventing something.

## Standards for a change

**Tests.** New behaviour needs a test that fails without the change. Fixtures are generated in code under `tests/`, not committed as binaries, so the structure under test is visible in the diff.

**Comments explain why.** The code says what it does. A comment earns its place by recording the reasoning, the specification clause, or the failure that motivated the shape of something.

**Report gaps rather than filling them.** See the one rule above.

**Evidence for conformance claims.** If a change affects produced documents, paste the veraPDF verdict before and after. The local auditor alone is not sufficient; it has been wrong before.

## Pull requests

Branch from `main`, keep commits focused, and write messages that explain the reasoning rather than restating the diff. The pull request template asks which standard is affected and how you verified it.

CI runs formatting, lint, type checking, tests on Python 3.10 through 3.14, veraPDF conformance, a differential check between the two audit engines, container build and scan, CodeQL, and an accessibility check of this project's own web interface. All of it has to pass.

## Reporting something

Bugs go through the issue templates. Security issues go through a [private advisory](https://github.com/krishaygarg/ada_pdf_remediation/security/advisories/new), not a public issue. See [SECURITY.md](SECURITY.md).

If you have a document this tool handles badly, that is the most useful thing you can send. Attach the smallest file that reproduces it.
