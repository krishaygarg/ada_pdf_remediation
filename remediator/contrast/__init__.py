"""Text contrast analysis against WCAG 2.x and APCA.

Matterhorn checkpoint 04, Colour and Contrast, is classified in the protocol as
needing human judgement, and no open source PDF tool appears to attempt it.
This package makes it machine determinable by rendering the page and measuring
what a reader would actually see.
"""

from __future__ import annotations

from .analysis import (
    AA_LARGE,
    AA_NORMAL,
    AAA_LARGE,
    AAA_NORMAL,
    APCA_BODY,
    APCA_LARGE,
    ContrastFinding,
    TextRun,
    Verdict,
    analyse_document,
    analyse_page,
    clear_analysis_cache,
    estimate_background,
    iter_text_runs,
    summarise,
)
from .color import Rgb, apca_contrast, contrast_ratio, delta_e, relative_luminance

__all__ = [
    "AAA_LARGE",
    "AAA_NORMAL",
    "AA_LARGE",
    "AA_NORMAL",
    "APCA_BODY",
    "APCA_LARGE",
    "ContrastFinding",
    "Rgb",
    "TextRun",
    "Verdict",
    "analyse_document",
    "analyse_page",
    "apca_contrast",
    "clear_analysis_cache",
    "contrast_ratio",
    "delta_e",
    "estimate_background",
    "iter_text_runs",
    "relative_luminance",
    "summarise",
]
