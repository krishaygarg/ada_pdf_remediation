# ADA PDF Remediator

**Most PDFs are unreadable to a screen reader. This fixes what it can, and refuses to lie about the rest.**

A screen reader follows a tag tree stored inside the file. Most PDFs do not have one, so the text arrives in whatever order the producer wrote it, with nothing marking what is a heading, a caption, or decoration.

This rebuilds that structure, then audits its own work.

```bash
pip install -e .
remediate-pdf lecture-notes.pdf accessible.pdf
check-compliance accessible.pdf
```

## Contents

| | |
|---|---|
| [Architecture](architecture.md) | How a document moves through the pipeline, and the two orderings people confuse |
| [Honesty](honesty.md) | The principle the design follows, and the incident it came from |
| [Conformance rules](reference/rules.md) | Every check with its ISO clause and WCAG mapping. Generated from the code. |
| [Command line](reference/cli.md) | `remediate-pdf`, `check-compliance`, `ada-ro-bench` |
| [HTTP API](reference/api.md) | Endpoints, job lifecycle, operational notes |
| [Research](planning/) | The two active tracks and their specifications |

## The claim this project will not make

It will not tell you a document is accessible. It can tell you nothing automatable is wrong with it, which is a smaller and more defensible claim.

The Matterhorn Protocol defines 136 failure conditions for PDF/UA-1 and only 87 can be determined by software. Reading order, heading structure, and whether a description actually conveys what a figure shows all still need a person.
