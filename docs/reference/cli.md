# Command line

## `remediate-pdf`

```bash
remediate-pdf input.pdf output.pdf [--traceback]
```

Refuses to write over its input. Exit code 0 on success, 1 on failure.

## `check-compliance`

```bash
check-compliance document.pdf [options]
```

| Option | Effect |
|---|---|
| `-f`, `--format` | `text`, `json`, `sarif` or `junit`. SARIF annotates a GitHub pull request. |
| `-o`, `--output` | Write to a file. |
| `--only ID` | Restrict to a condition (`13-004`) or checkpoint (`13`). Repeatable. |
| `--skip ID` | Skip a condition or checkpoint. Repeatable. |
| `--contrast` | Also measure text contrast. Renders every page, so it is off by default. |
| `--warnings-as-errors` | Exit non-zero on warnings too. |
| `--list-rules` | Print the catalogue with ISO and WCAG cross-references. |
| `--remote` | Audit with check.axes4.com. Requires `--consent-upload`. |

Exit code 0 when conformant, 1 when not, 2 on a usage or input error.

Remote auditing transmits the document to a third party, which is why it needs an explicit second flag. Local auditing never leaves the machine.

## `ada-ro-bench`

```bash
ada-ro-bench datasets/example.jsonl [--strategy NAME] [--format markdown|json]
ada-ro-bench --list-strategies
```

Benchmarks reading order strategies. Every strategy currently ties with the baseline; see [the research track](https://github.com/krishaygarg/ada_pdf_remediation/blob/main/docs/planning/layout_reading_order_proposal.md).
