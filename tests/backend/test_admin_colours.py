"""Contrast of the status colours of the administration (static/css/admin.css).

WCAG 2.1 AA: 4.5:1 for the text of a badge on its background (1.4.3) and 3:1 for its border
against the page (1.4.11). The tokens are read from the stylesheet for the light scheme
(``:root``) and both dark ones (the media query and ``data-theme="dark"``), so a changed colour
is checked. Django's own page backgrounds are #fff (light) and #121212 (dark)."""

import re

import pytest

from config.settings.base import BASE_DIR
from tests.backend.test_chart_colours import contrast

CSS = (BASE_DIR / "static" / "css" / "admin.css").read_text("utf-8")
PAGE = {"light": "#ffffff", "dark": "#121212"}
TONES = ["success", "info", "warning", "danger"]


def tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--barf-[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def block_after(marker: str) -> str:
    start = CSS.index(marker)
    return CSS[start : CSS.index("\n}", start)]


SCHEMES = {
    "light": tokens(block_after(":root {")),
    "dark (media query)": tokens(block_after(':root:not([data-theme="light"]) {')),
    "dark (switch)": tokens(block_after('html[data-theme="dark"] {')),
}


def page(scheme: str) -> str:
    return PAGE["light" if scheme == "light" else "dark"]


def test_every_scheme_defines_every_token():
    expected = {f"--barf-{tone}-{part}" for tone in TONES for part in ("fg", "bg", "border")}

    for scheme, colours in SCHEMES.items():
        assert set(colours) == expected, scheme


def test_the_two_dark_schemes_are_the_same():
    assert SCHEMES["dark (media query)"] == SCHEMES["dark (switch)"]


@pytest.mark.parametrize("tone", TONES)
@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_text_of_a_badge_has_4_5_to_1_on_its_background(scheme, tone):
    colours = SCHEMES[scheme]

    assert contrast(colours[f"--barf-{tone}-fg"], colours[f"--barf-{tone}-bg"]) >= 4.5


@pytest.mark.parametrize("tone", TONES)
@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_border_of_a_badge_has_3_to_1_against_the_page(scheme, tone):
    colours = SCHEMES[scheme]

    assert contrast(colours[f"--barf-{tone}-border"], page(scheme)) >= 3.0


@pytest.mark.parametrize("tone", TONES)
@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_text_of_a_badge_is_readable_on_the_page_too(scheme, tone):
    """In forced colours or if the background is not painted, the text stays legible."""
    colours = SCHEMES[scheme]

    assert contrast(colours[f"--barf-{tone}-fg"], page(scheme)) >= 4.5


def test_the_stylesheet_has_no_external_asset_and_no_important():
    assert "url(" not in CSS and "@import" not in CSS and "http" not in CSS
    assert "!important" not in CSS


def test_forced_colours_keep_the_border_so_the_state_is_not_colour_alone():
    assert "@media (forced-colors: active)" in CSS
