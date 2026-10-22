"""Contrast of the chart colours (docs/12 §12.11), recomputed from the stylesheet tokens.

WCAG 2.1 AA: 3:1 for the lines and marks of a chart (1.4.11 non-text contrast) and 4.5:1 for
its text (1.4.3). The tokens are read from ``app.css`` for the light scheme (``:root``) and
the dark one (the ``prefers-color-scheme: dark`` block), so a changed colour is checked.

The weight colour and the vet colour are NOT told apart by lightness (the test records how
close they are): the shape of the mark (circle, diamond) carries the meaning, never the colour.
"""

import re

import pytest

from config.settings.base import BASE_DIR

CSS = (BASE_DIR / "static" / "css" / "app.css").read_text("utf-8")


def tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def light_tokens() -> dict[str, str]:
    return tokens(CSS[: CSS.index("@media (prefers-color-scheme: dark)")])


def dark_tokens() -> dict[str, str]:
    start = CSS.index("@media (prefers-color-scheme: dark)")
    return {**light_tokens(), **tokens(CSS[start : CSS.index("/* --- Base", start)])}


SCHEMES = {"light": light_tokens(), "dark": dark_tokens()}


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_function_matches_known_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)  # the AA limit
    assert contrast("#ffffff", "#ffffff") == pytest.approx(1)


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize(
    "token",
    ["--chart-weight", "--chart-vet", "--chart-axis", "--chart-target", "--chart-band-edge"],
)
def test_lines_and_marks_have_3_to_1_against_the_card(scheme, token):
    colours = SCHEMES[scheme]
    assert contrast(colours[token], colours["--color-surface"]) >= 3.0, (scheme, token)


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("token", ["--chart-weight", "--chart-vet"])
def test_marks_have_3_to_1_against_the_shaded_band(scheme, token):
    colours = SCHEMES[scheme]
    assert contrast(colours[token], colours["--chart-band"]) >= 3.0, (scheme, token)


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("token", ["--color-text", "--color-muted"])
def test_chart_text_has_4_5_to_1_on_the_card_and_on_the_band(scheme, token):
    colours = SCHEMES[scheme]
    assert contrast(colours[token], colours["--color-surface"]) >= 4.5, (scheme, token)
    assert contrast(colours[token], colours["--chart-band"]) >= 4.5, (scheme, token)


def test_the_lowest_graphic_contrast_is_the_one_the_stylesheet_and_the_docs_state():
    """The comment in app.css and docs/12 §12.11 say "the lowest measured value is 4.1:1"."""
    lowest = min(
        contrast(colours[token], colours["--color-surface"])
        for colours in SCHEMES.values()
        for token in ("--chart-weight", "--chart-vet", "--chart-axis", "--chart-target")
    )
    edge = min(
        contrast(colours["--chart-band-edge"], colours["--color-surface"])
        for colours in SCHEMES.values()
    )

    assert min(lowest, edge) >= 4.1
    assert "the lowest measured value is\n     4.1:1" in CSS


def test_weight_and_vet_colours_are_close_in_lightness_so_shape_must_carry_the_meaning():
    """Recorded on purpose: they are NOT distinguishable by lightness (1.4:1 light, 1.1:1 dark),
    so a legend or a title that relied on colour alone would be wrong."""
    for scheme, expected_at_most in (("light", 1.5), ("dark", 1.2)):
        colours = SCHEMES[scheme]
        assert contrast(colours["--chart-weight"], colours["--chart-vet"]) <= expected_at_most
    assert "SHAPE (circle,\n     diamond) is what tells them apart" in CSS
