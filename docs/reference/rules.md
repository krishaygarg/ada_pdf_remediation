# Conformance rules

Generated from the rule registry by `scripts/generate_rule_catalogue.py`.
Do not edit by hand.

## Coverage

The Matterhorn Protocol 1.1 defines **31 checkpoints** and **136 failure conditions** for PDF/UA-1. Of those, **87** can be determined by software, 47 need human judgement, and 2 have no defined test.

This project implements **34 conditions** across **17 of 31** checkpoints.

Everything not listed below is unimplemented. See [CONTRIBUTING](../../CONTRIBUTING.md) for the backlog.

## Checkpoint 01 Real content

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `01-003` | The document has no logical structure | 7.1 | 1.3.1 | software |

## Checkpoint 02 Role mapping

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `02-001` | A non-standard structure type is not mapped to a standard one | 7.1 | 1.3.1 | software |
| `02-003` | The role map contains a circular mapping | 7.1 | 1.3.1 | software |

## Checkpoint 04 Colour and contrast

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `04-001` | Text does not meet the minimum contrast ratio | 7.1 | 1.4.3 | human, automated here |
| `04-002` | Text is drawn in the same colour as its background | 7.1 | 1.4.3 | human, automated here |
| `04-003` | Text meets WCAG 2 but falls short of the APCA guidance | 7.1 | 1.4.3, 1.4.6 | human, automated here |

## Checkpoint 06 Metadata

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `06-001` | The document catalogue has no XMP metadata stream | 7.1 | 1.3.1 | software |
| `06-002` | The XMP metadata does not declare a document title | 7.1 | 2.4.2 | software |
| `06-003` | The viewer is not told to display the document title | 7.1 | 2.4.2 | software |
| `06-004` | The PDF/UA identifier is missing or uses the wrong namespace | 5 | 4.1.2 | software |

## Checkpoint 07 Dictionary

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `07-001` | The document is not declared as tagged | 7.1 | 1.3.1 | software |
| `07-002` | The tagging is flagged as unreliable through /Suspects | 7.1 | 1.3.1 | software |

## Checkpoint 09 Appropriate tags

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `09-004` | A structure element that must contain content is empty | 7.1 | 1.3.1 | software |

## Checkpoint 10 Character mappings

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `10-001` | A font provides no mapping from character codes to Unicode | 7.21.7 | 1.1.1 | software |
| `10-003` | A character mapping resolves codes to meaningless values | 7.21.7 | 1.1.1 | software |

## Checkpoint 11 Declared natural language

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `11-001` | The document does not declare a default language | 7.2 | 3.1.1 | software |
| `11-006` | A declared language is not a well formed language tag | 7.2 | 3.1.1, 3.1.2 | software |

## Checkpoint 13 Graphics

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `13-004` | A figure has no alternate description | 7.3 | 1.1.1 | software |
| `13-005` | A figure's alternate description carries no information | 7.3 | 1.1.1 | human, automated here |
| `13-008` | A figure does not declare a bounding box | 7.3 | 1.3.1 | software |

## Checkpoint 14 Headings

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `14-002` | A heading level is skipped | 7.4 | 1.3.1, 2.4.6 | software |
| `14-003` | The first heading in the document is not level one | 7.4 | 1.3.1 | software |

## Checkpoint 15 Tables

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `15-003` | A table has no header cells | 7.5 | 1.3.1 | software |
| `15-005` | A header cell does not declare its scope | 7.5 | 1.3.1 | software |
| `15-006` | Table rows and cells are nested incorrectly | 7.5 | 1.3.1 | software |

## Checkpoint 16 Lists

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `16-001` | List items and their parts are nested incorrectly | 7.6 | 1.3.1 | software |

## Checkpoint 17 Mathematical expressions

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `17-002` | A formula has no alternate description | 7.9 | 1.1.1 | software |

## Checkpoint 19 Notes and references

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `19-003` | A note has no identifier | 7.9 | 1.3.1 | software |

## Checkpoint 28 Annotations

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `28-004` | An annotation has no alternate description | 7.18.1 | 1.1.1, 4.1.2 | software |
| `28-005` | An annotation is not reachable from the structure tree | 7.18.1 | 1.3.1 | software |
| `28-006` | An annotation does not declare a structure parent key | 7.18.1 | 1.3.1 | software |
| `28-011` | A link annotation has no alternate description | 7.18.5 | 2.4.4 | software |

## Checkpoint 30 XObjects

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `30-002` | A page does not declare structural tab order | 7.18.3 | 2.4.3 | software |

## Checkpoint 31 Fonts

| Condition | What it reports | ISO 14289-1 | WCAG | Determination |
|---|---|---|---|---|
| `31-001` | A font program is not embedded | 7.21.4.1 | 1.4.5 | software |

## Severity

| Level | Meaning |
|---|---|
| Error | The document does not conform. |
| Warning | It conforms, but a reader is likely to be obstructed. A figure described only as `image` is the usual case. |
| Review | Software cannot settle it; a person has to look. |

A rule that raises is recorded rather than swallowed, and makes the report non-conformant. A check that failed to run must never look like a check that found nothing.
