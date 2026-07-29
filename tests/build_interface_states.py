#!/usr/bin/env python3
"""Render each state of the interface as a static page for accessibility testing.

An automated checker only sees what is in the DOM and visible. Pointing one at
the interface therefore tests the upload form and nothing else, because the
progress and report sections are hidden until a document is processed. Those
are the states that carry the actual information, so they are the ones most
worth checking.

This writes the same markup with each state revealed and populated with
representative content, so axe can see all of it. The output is a test artifact
and is never served.

Usage:
    python tests/build_interface_states.py [output directory]
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

FINDINGS = [
    (
        "error",
        "Error",
        "13-004",
        "A Figure element has neither /Alt nor /ActualText.",
        "Describe what the figure conveys. If it is decorative, mark it as an "
        "artifact instead of tagging it as a figure.",
        "Page 3",
    ),
    (
        "error",
        "Error",
        "31-001",
        "The font program for NimbusRoman is not embedded.",
        "Embed the font, or regenerate the source document with font embedding enabled.",
        "",
    ),
    (
        "warning",
        "Warning",
        "13-005",
        "A Figure is described only as 'image', which conveys nothing.",
        "Describe the content or purpose of the figure.",
        "Page 5",
    ),
    (
        "review",
        "Review",
        "04-003",
        "Text passes WCAG 2 at 4.61:1 but reaches only APCA Lc +58, short of "
        "the Lc 60 suggested for this size.",
        "Increase the lightness difference, or use a heavier weight at this size.",
        "Page 1",
    ),
]


def _finding(
    severity: str, label: str, condition: str, message: str, remedy: str, where: str
) -> str:
    location = f"<span>{html.escape(where)}</span>" if where else ""
    return f"""
        <li class="finding" data-severity="{severity}">
          <span class="finding__severity">{label}</span>
          <div class="finding__body">
            <p class="finding__message">{html.escape(message)}</p>
            <p class="finding__remedy">{html.escape(remedy)}</p>
            <p class="finding__meta">
              <span class="finding__condition">Matterhorn {condition}</span>
              {location}
            </p>
          </div>
        </li>"""


def _report_body() -> str:
    groups: dict[str, list[tuple[str, ...]]] = {}
    for entry in FINDINGS:
        groups.setdefault(entry[2].split("-")[0], []).append(entry)

    sections = []
    for checkpoint, entries in sorted(groups.items()):
        items = "".join(_finding(*entry) for entry in entries)
        plural = "" if len(entries) == 1 else "s"
        sections.append(
            f"""
      <section class="checkpoint">
        <h3>Checkpoint {checkpoint} · {len(entries)} finding{plural}</h3>
        <ul>{items}
        </ul>
      </section>"""
        )
    return "".join(sections)


def _tally() -> str:
    cells = [("Errors", 2, "error"), ("Warnings", 1, "warning"), ("Rules run", 31, "neutral")]
    return "".join(
        f'<div data-tone="{tone}"><dd>{value}</dd><dt>{label}</dt></div>'
        for label, value, tone in cells
    )


def _stages(current: str = "recovering-fonts") -> str:
    stages = [
        ("opening", "Reading"),
        ("analysing-page", "Analysing pages"),
        ("tagging-figures", "Figures"),
        ("recognising-text", "Recognising text"),
        ("recovering-fonts", "Character maps"),
        ("building-structure", "Structure"),
        ("writing", "Writing"),
        ("auditing", "Auditing"),
    ]
    index = [key for key, _ in stages].index(current)
    return "".join(
        f'<li data-stage="{key}" data-done="{str(position <= index).lower()}"'
        f' data-current="{str(position == index).lower()}">{label}</li>'
        for position, (key, label) in enumerate(stages)
    )


def _reveal(markup: str, element_id: str) -> str:
    return re.sub(rf'(id="{element_id}"[^>]*?)\s+hidden', r"\1", markup)


def _hide(markup: str, element_id: str) -> str:
    if re.search(rf'id="{element_id}"[^>]*\shidden', markup):
        return markup
    return re.sub(rf'(id="{element_id}")', r"\1 hidden", markup, count=1)


def build(output: Path) -> list[Path]:
    source = (WEB / "index.html").read_text(encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    for asset in ("styles.css", "app.js", "favicon.svg"):
        (output / asset).write_bytes((WEB / asset).read_bytes())

    written: list[Path] = []

    idle = output / "idle.html"
    idle.write_text(source, encoding="utf-8")
    written.append(idle)

    running = source
    running = _reveal(running, "run")
    running = running.replace(
        '<ol class="stages" id="stages" aria-hidden="true"></ol>',
        f'<ol class="stages" id="stages" aria-hidden="true">{_stages()}</ol>',
    )
    running = running.replace(
        '<span id="run-filename"></span>', '<span id="run-filename">lecture-notes-week-3.pdf</span>'
    )
    running = running.replace(
        '<div class="log" id="log" role="log" aria-label="Progress detail" tabindex="0"></div>',
        '<div class="log" id="log" role="log" aria-label="Progress detail" tabindex="0">'
        "<p><time>14:22:31</time>Opening lecture-notes-week-3.pdf</p>"
        "<p><time>14:22:31</time>Analysing page 3 of 12</p>"
        "<p><time>14:22:33</time>NimbusRoman: 214 codes mapped (214 from embedded font program)</p>"
        "</div>",
    )
    running_path = output / "running.html"
    running_path.write_text(running, encoding="utf-8")
    written.append(running_path)

    report = source
    report = _hide(report, "dropzone")
    report = _reveal(report, "report")
    report = report.replace(
        '<p class="report__verdict" id="report-verdict"></p>',
        '<p class="report__verdict" id="report-verdict">2 conformance errors remain. '
        "They are listed below with the clause behind each one.</p>",
    )
    report = report.replace(
        '<dl class="tally" id="tally"></dl>', f'<dl class="tally" id="tally">{_tally()}</dl>'
    )
    report = report.replace(
        '<div class="findings" id="findings"></div>',
        f'<div class="findings" id="findings">{_report_body()}\n    </div>',
    )
    report_path = output / "report.html"
    report_path.write_text(report, encoding="utf-8")
    written.append(report_path)

    return written


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tmp/interface-states")
    for path in build(target):
        print(path)
