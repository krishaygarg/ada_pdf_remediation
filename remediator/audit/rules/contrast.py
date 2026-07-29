"""Matterhorn checkpoint 04, Colour and Contrast.

The protocol classifies these conditions as requiring human judgement, because
at the time it was written no tool could determine what sits behind a piece of
text. Rendering the page and measuring the pixels answers that, so the
conditions are reported here as software determinable while still being marked
with their protocol classification.

The rules are opt-in. Rendering every page is far more expensive than the rest
of the audit, so they are skipped unless the caller asks for checkpoint 04.
"""

from __future__ import annotations

from collections.abc import Iterator

from ...contrast import Verdict, analyse_document
from ..context import DocumentContext
from ..model import Determination, Finding, Location, RuleMetadata, Severity
from ..registry import rule

#: Reported per page rather than per run once a page is this bad, so a document
#: with a light grey body face produces a usable report instead of thousands of
#: near-identical findings.
_PER_PAGE_LIMIT = 12


@rule(
    RuleMetadata(
        condition="04-001",
        checkpoint_name="Colour and contrast",
        summary="Text does not meet the minimum contrast ratio",
        clause="7.1",
        wcag=("1.4.3",),
        determination=Determination.HUMAN,
        default_severity=Severity.ERROR,
    )
)
def text_meets_minimum_contrast(context: DocumentContext) -> Iterator[Finding]:
    """WCAG 1.4.3 requires 4.5:1 for body text and 3:1 for large text."""
    findings = analyse_document(context.path)

    per_page: dict[int, int] = {}
    suppressed: dict[int, int] = {}

    for measurement in findings:
        if measurement.verdict is not Verdict.FAIL_AA:
            continue
        page = measurement.run.page_index
        per_page[page] = per_page.get(page, 0) + 1
        if per_page[page] > _PER_PAGE_LIMIT:
            suppressed[page] = suppressed.get(page, 0) + 1
            continue

        yield Finding(
            condition="04-001",
            message=measurement.describe(),
            location=Location(page=page, bbox=measurement.run.bbox),
            remedy=(
                f"Darken the text or lighten the background until the ratio "
                f"reaches {measurement.required_ratio}:1. APCA suggests aiming "
                f"for Lc {measurement.apca_target:.0f}."
            ),
            context={
                "ratio": round(measurement.ratio or 0.0, 2),
                "apca": round(measurement.apca or 0.0, 1),
                "foreground": measurement.run.color.to_hex(),
                "background": measurement.background.to_hex() if measurement.background else None,
                "pointSize": round(measurement.run.size, 1),
                "largeText": measurement.run.is_large,
            },
        )

    for page, count in sorted(suppressed.items()):
        # Saying how many were withheld keeps the report honest about its own
        # truncation, rather than implying the page had only a dozen problems.
        yield Finding(
            condition="04-001",
            message=(
                f"A further {count} text run(s) on page {page + 1} fall below the "
                "minimum contrast ratio and are not listed individually."
            ),
            location=Location(page=page),
            remedy="Review the colour scheme for this page as a whole.",
            context={"suppressed": count},
        )


@rule(
    RuleMetadata(
        condition="04-002",
        checkpoint_name="Colour and contrast",
        summary="Text is drawn in the same colour as its background",
        clause="7.1",
        wcag=("1.4.3",),
        determination=Determination.HUMAN,
        default_severity=Severity.ERROR,
    )
)
def text_is_distinguishable_from_its_background(context: DocumentContext) -> Iterator[Finding]:
    """Text the same colour as what is behind it is present but unreadable.

    This is distinct from low contrast. It happens when a colour is applied to
    the wrong element, when white text lands on a white ground after a template
    change, and when text is deliberately hidden.
    """
    for measurement in analyse_document(context.path):
        if measurement.verdict is not Verdict.INVISIBLE:
            continue
        yield Finding(
            condition="04-002",
            message=measurement.describe(),
            location=Location(page=measurement.run.page_index, bbox=measurement.run.bbox),
            remedy=(
                "Give the text a colour that differs from its background, or "
                "remove it if it is not meant to be seen."
            ),
            context={"foreground": measurement.run.color.to_hex()},
        )


@rule(
    RuleMetadata(
        condition="04-003",
        checkpoint_name="Colour and contrast",
        summary="Text meets WCAG 2 but falls short of the APCA guidance",
        clause="7.1",
        wcag=("1.4.3", "1.4.6"),
        determination=Determination.HUMAN,
        default_severity=Severity.WARNING,
    )
)
def text_meets_perceptual_contrast_guidance(context: DocumentContext) -> Iterator[Finding]:
    """Where the two metrics disagree, and why that is worth knowing.

    The WCAG 2 ratio is symmetric, so it scores light text on a dark ground the
    same as the reverse at equal luminance separation. APCA models polarity and
    generally judges light-on-dark more harshly. A run that clears 4.5:1 while
    sitting well under its APCA target is a case where conformance and
    readability part company, which is worth surfacing without failing the
    document for it.
    """
    reported = 0
    for measurement in analyse_document(context.path):
        if measurement.verdict not in (Verdict.PASS_AA, Verdict.PASS_AAA):
            continue
        if measurement.apca is None:
            continue
        if abs(measurement.apca) >= measurement.apca_target:
            continue
        reported += 1
        if reported > _PER_PAGE_LIMIT:
            break
        yield Finding(
            condition="04-003",
            message=(
                f"Text {measurement.run.text[:40]!r} passes WCAG 2 at "
                f"{measurement.ratio:.2f}:1 but reaches only APCA Lc "
                f"{measurement.apca:+.0f}, short of the Lc "
                f"{measurement.apca_target:.0f} suggested for this size."
            ),
            severity=Severity.WARNING,
            location=Location(page=measurement.run.page_index, bbox=measurement.run.bbox),
            remedy="Increase the lightness difference, or use a heavier weight at this size.",
            context={
                "ratio": round(measurement.ratio or 0.0, 2),
                "apca": round(measurement.apca, 1),
            },
        )
