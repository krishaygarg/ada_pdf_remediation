"""Colour models and contrast metrics.

Two metrics are computed for every text run, because they disagree and the
disagreement is informative.

WCAG 2.x contrast ratio is what conformance is currently assessed against. It
takes relative luminance through a piecewise sRGB transfer curve and forms
``(L_lighter + 0.05) / (L_darker + 0.05)``.

APCA, the candidate for WCAG 3, models perceived lightness contrast instead and
accounts for polarity: dark text on light ground and light text on dark ground
are not equally readable at the same luminance ratio, which the WCAG 2 ratio
cannot express because it is symmetric. Reporting both means a document that
scrapes past 4.5:1 while being hard to read is visible as such.

Background estimation works in CIELAB because a median taken in sRGB is not a
perceptually meaningful average, and an anti-aliased glyph edge would drag it.
"""

from __future__ import annotations

import math
from typing import NamedTuple

# --- sRGB ------------------------------------------------------------------


class Rgb(NamedTuple):
    """A colour with components in 0..1."""

    r: float
    g: float
    b: float

    @classmethod
    def from_bytes(cls, r: int, g: int, b: int) -> Rgb:
        return cls(r / 255.0, g / 255.0, b / 255.0)

    @classmethod
    def from_int(cls, packed: int) -> Rgb:
        """Decode a 24 bit 0xRRGGBB value, the form PyMuPDF reports."""
        return cls.from_bytes((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)

    def to_bytes(self) -> tuple[int, int, int]:
        return (
            max(0, min(255, round(self.r * 255))),
            max(0, min(255, round(self.g * 255))),
            max(0, min(255, round(self.b * 255))),
        )

    def to_hex(self) -> str:
        return "#{:02X}{:02X}{:02X}".format(*self.to_bytes())


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


# --- WCAG 2.x --------------------------------------------------------------

#: Luminance coefficients from WCAG 2.1, matching Rec. 709.
_WCAG_COEFFICIENTS = (0.2126, 0.7152, 0.0722)

#: Break point of the sRGB piecewise transfer function as WCAG 2.1 states it.
#: The precise value is 0.04045; WCAG carries 0.03928 from an earlier draft.
#: The figure below is the one the success criterion is defined with, so it is
#: the one used, and the difference is far smaller than any threshold.
_WCAG_LINEAR_BREAK = 0.03928


def _wcag_linearise(channel: float) -> float:
    channel = _clamp01(channel)
    if channel <= _WCAG_LINEAR_BREAK:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: Rgb) -> float:
    """Relative luminance as defined by WCAG 2.1, in 0..1."""
    return sum(
        coefficient * _wcag_linearise(channel)
        for coefficient, channel in zip(_WCAG_COEFFICIENTS, color, strict=True)
    )


def contrast_ratio(first: Rgb, second: Rgb) -> float:
    """WCAG 2.x contrast ratio, between 1.0 and 21.0.

    Symmetric: swapping the arguments gives the same answer. That symmetry is
    the property APCA exists to correct, since polarity affects readability.
    """
    a = relative_luminance(first)
    b = relative_luminance(second)
    lighter, darker = (a, b) if a >= b else (b, a)
    return (lighter + 0.05) / (darker + 0.05)


# --- APCA ------------------------------------------------------------------
#
# Constants are from APCA-W3 0.1.9, the version referenced by the WCAG 3 draft.

_APCA_TRC = 2.4
_APCA_COEFFICIENTS = (0.2126729, 0.7151522, 0.0721750)
_APCA_BLACK_THRESHOLD = 0.022
_APCA_BLACK_CLAMP = 1.414
_APCA_NORM_BG = 0.56
_APCA_NORM_TEXT = 0.57
_APCA_REVERSE_BG = 0.65
_APCA_REVERSE_TEXT = 0.62
_APCA_SCALE = 1.14
_APCA_OFFSET = 0.027
_APCA_LOW_CLIP = 0.1
#: Below this luminance difference the result is noise rather than contrast.
_APCA_DELTA_Y_MIN = 0.0005


def apca_screen_luminance(color: Rgb) -> float:
    """APCA's estimate of screen luminance.

    Note this is a simple power curve, not the piecewise function WCAG uses.
    Substituting one for the other is a common error and shifts every result.
    """
    return sum(
        coefficient * (_clamp01(channel) ** _APCA_TRC)
        for coefficient, channel in zip(_APCA_COEFFICIENTS, color, strict=True)
    )


def _soft_clamp_black(luminance: float) -> float:
    """Lift very dark values, which APCA does to model flare near black."""
    if luminance >= _APCA_BLACK_THRESHOLD:
        return luminance
    return luminance + (_APCA_BLACK_THRESHOLD - luminance) ** _APCA_BLACK_CLAMP


def apca_contrast(text: Rgb, background: Rgb) -> float:
    """APCA lightness contrast, ``Lc``, for text drawn on a background.

    Positive values mean dark text on a light background, negative values the
    reverse. The magnitude is what thresholds are stated against; roughly, Lc 60
    is comparable to WCAG 4.5:1 for body text, and Lc 75 to 7:1.

    Deliberately asymmetric in its arguments, unlike :func:`contrast_ratio`.
    """
    text_y = _soft_clamp_black(apca_screen_luminance(text))
    background_y = _soft_clamp_black(apca_screen_luminance(background))

    if abs(background_y - text_y) < _APCA_DELTA_Y_MIN:
        return 0.0

    if background_y > text_y:
        contrast = (background_y**_APCA_NORM_BG - text_y**_APCA_NORM_TEXT) * _APCA_SCALE
        return 0.0 if contrast < _APCA_LOW_CLIP else (contrast - _APCA_OFFSET) * 100.0

    contrast = (background_y**_APCA_REVERSE_BG - text_y**_APCA_REVERSE_TEXT) * _APCA_SCALE
    return 0.0 if contrast > -_APCA_LOW_CLIP else (contrast + _APCA_OFFSET) * 100.0


# --- CIELAB ----------------------------------------------------------------

#: D65 white point, the reference illuminant sRGB is defined against.
_D65 = (0.95047, 1.00000, 1.08883)


def _srgb_to_linear(channel: float) -> float:
    channel = _clamp01(channel)
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def to_xyz(color: Rgb) -> tuple[float, float, float]:
    """Convert sRGB to CIE XYZ under the D65 illuminant."""
    r, g, b = (_srgb_to_linear(channel) for channel in color)
    return (
        r * 0.4124564 + g * 0.3575761 + b * 0.1804375,
        r * 0.2126729 + g * 0.7151522 + b * 0.0721750,
        r * 0.0193339 + g * 0.1191920 + b * 0.9503041,
    )


def _lab_f(value: float) -> float:
    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    if value > epsilon:
        return value ** (1.0 / 3.0)
    return (kappa * value + 16.0) / 116.0


def to_lab(color: Rgb) -> tuple[float, float, float]:
    """Convert sRGB to CIELAB, where a Euclidean distance is roughly perceptual."""
    x, y, z = to_xyz(color)
    fx, fy, fz = (
        _lab_f(x / _D65[0]),
        _lab_f(y / _D65[1]),
        _lab_f(z / _D65[2]),
    )
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def delta_e(first: Rgb, second: Rgb) -> float:
    """CIE76 colour difference.

    Adequate for the job here, which is separating glyph pixels from background
    pixels. A difference of roughly 2.3 is the threshold of perceptibility, and
    the separations being measured are far larger than that.
    """
    a = to_lab(first)
    b = to_lab(second)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


__all__ = [
    "Rgb",
    "apca_contrast",
    "apca_screen_luminance",
    "contrast_ratio",
    "delta_e",
    "relative_luminance",
    "to_lab",
    "to_xyz",
]
