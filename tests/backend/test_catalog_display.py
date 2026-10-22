"""The words and signs of the verification and evidence badges, pinned independently.

The badge is the central promise of the library: icon + text + colour say how far a source
was verified. The tests in ``test_catalog_views.py`` build their expectation from the very
dictionaries they guard, so swapping the names of two levels would not fail them. Here the
expected icon, class and text are typed out as literals, and the badge and the sentence printed
under it on the detail page are checked to talk about the same level.
"""

import html
import re
from datetime import date

import pytest
from django.urls import reverse

from catalog.display import (
    CONTENT_CAVEATS,
    EVIDENCE_NAMES,
    VERIFICATION_STYLES,
    content_caveat,
    verification_style,
)
from catalog.models import EvidenceLevel, VerificationLevel

# level -> (CSS suffix, icon, short name, words that the badge and the legend text share)
VERIFICATION = {
    "P": ("p", "✓", "P – ověřena hodnota nebo tabulka v primárním zdroji", ("primárním",)),
    "A": ("a", "◆", "A – ověřen abstrakt nebo souhrn", ("abstrakt", "souhrn")),
    "S": ("s", "◇", "S – ověřeno jen přes sekundární zdroj", ("sekundární", "zdroj")),
    "B": ("b", "○", "B – ověřeny jen bibliografické údaje", ("bibliografické", "údaje")),
    "NONE": ("none", "?", "Neověřeno", ("neověřeno",)),
}

# level -> (short name, words that the short name and the registry description share)
EVIDENCE = {
    "L1": ("doporučení instituce", ("doporučení", "instituce")),
    "L2": ("přehled nebo metaanalýza", ("přehled", "metaanalýza")),
    "L3": ("původní studie", ("původní", "studie")),
    "L4": ("kazuistika", ("kazuistika",)),
    "L5": ("databáze potravin", ("databáze", "potravin")),
    "L6": ("sekundární zdroj", ("sekundární", "zdroj")),
}


def test_the_tables_cover_every_level():
    assert set(VERIFICATION) == set(VerificationLevel.values) == set(VERIFICATION_STYLES)
    assert set(EVIDENCE) == set(EvidenceLevel.values) == set(EVIDENCE_NAMES)


@pytest.mark.parametrize("level", VERIFICATION)
def test_verification_badge_is_what_the_table_says(level):
    css, icon, name, _ = VERIFICATION[level]
    style = verification_style(level)

    assert (style.css, style.icon, style.name) == (css, icon, name)
    assert style.name.startswith(f"{level} – ") or level == "NONE"


@pytest.mark.parametrize("level", EVIDENCE)
def test_evidence_name_is_what_the_table_says(level):
    assert EVIDENCE_NAMES[level] == EVIDENCE[level][0]


@pytest.mark.parametrize("level", VERIFICATION)
def test_badge_and_legend_text_talk_about_the_same_level(level):
    """The short name and the exact meaning (the model label) share their key words, so a
    swap of two levels in either of them is found."""
    name = verification_style(level).name.lower()
    meaning = VerificationLevel(level).label.lower()
    for word in VERIFICATION[level][3]:
        assert word in name, (level, word)
        assert word in meaning, (level, word)


@pytest.mark.parametrize("level", EVIDENCE)
def test_evidence_name_and_registry_description_talk_about_the_same_level(level):
    name = EVIDENCE_NAMES[level].lower()
    meaning = EvidenceLevel(level).label.lower()
    for word in EVIDENCE[level][1]:
        assert word in name, (level, word)
        assert word in meaning, (level, word)


@pytest.mark.django_db
@pytest.mark.parametrize("level", VERIFICATION)
def test_detail_page_badge_is_followed_by_the_sentence_of_the_same_level(
    client, empty_library, make_source, level
):
    extra = (
        {}
        if level == "NONE"
        else {"verification_markers": [level], "last_verified_at": date(2026, 10, 18)}
    )
    source = make_source(citation_key="Badge1", verification_level=level, **extra)

    content = client.get(source.get_absolute_url()).content.decode()
    section = content.split('id="verification-title"', 1)[1].split("</section>", 1)[0]
    badge = re.search(r'<span class="status__label">([^<]+)</span>', section)
    sentence = re.search(r"</p>\s*<p>([^<]+)</p>", section)

    assert badge and sentence
    assert html.unescape(badge.group(1)) == VERIFICATION[level][2]
    for word in VERIFICATION[level][3]:
        assert word in html.unescape(badge.group(1)).lower()
        assert word in html.unescape(sentence.group(1)).lower()
    assert f"status--verif-{VERIFICATION[level][0]}" in section


@pytest.mark.django_db
@pytest.mark.parametrize("level", EVIDENCE)
def test_detail_page_evidence_badge_and_description_agree(
    client, empty_library, make_source, level
):
    kinds = {
        "L1": ("GUIDELINE", {}),
        "L2": ("REVIEW", {}),
        "L3": ("ORIGINAL_STUDY", {}),
        "L4": ("CASE_REPORT", {}),
        "L5": ("FOOD_DATABASE", {"species_scope": "NOT_APPLICABLE"}),
        "L6": ("SECONDARY", {}),
    }
    source_type, extra = kinds[level]
    source = make_source(citation_key="Ev1", evidence_level=level, source_type=source_type, **extra)

    content = client.get(source.get_absolute_url()).content.decode()
    row = re.search(r"<dt>Úroveň odbornosti zdroje</dt><dd>(.*?)</dd>", content, flags=re.DOTALL)

    assert row
    text = html.unescape(row.group(1)).lower()
    assert f'<span class="evidence__code">{level}</span>' in row.group(1)
    for word in EVIDENCE[level][1]:
        assert text.count(word) >= 2, (level, word)  # once in the badge, once in the description


# --- The warning next to numbers and findings -------------------------------------------------


def test_content_caveat_exists_exactly_for_levels_that_were_not_checked_in_the_original():
    assert {level for level in VerificationLevel.values if content_caveat(level)} == {
        "B",
        "S",
        "NONE",
    }
    assert set(CONTENT_CAVEATS) == {"B", "S", "NONE"}
    assert content_caveat("A") == "" and content_caveat("P") == ""
    with pytest.raises(ValueError):
        content_caveat("X")


def test_content_caveats_say_what_was_not_checked_and_never_advise():
    assert "bibliografické" in CONTENT_CAVEATS["B"] and "nejsou ověřená" in CONTENT_CAVEATS["B"]
    assert "sekundární zdroj" in CONTENT_CAVEATS["S"] and "orientace" in CONTENT_CAVEATS["S"]
    assert "neověřený" in CONTENT_CAVEATS["NONE"]
    for text in CONTENT_CAVEATS.values():
        assert not re.search(r"krm|dávk|množství", text.lower()), text


@pytest.mark.django_db
def test_real_sources_show_the_warning_next_to_their_numbers(client):
    """FEDIAF2025 (S) has a note and units, SciRep2025 (no mark) a note and findings, an
    abstract-level source none. Each block of text copied from the registry gets one."""

    def warnings(key: str) -> int:
        content = client.get(reverse("catalog:source_detail", args=[key])).content.decode()
        return content.count('class="notice notice--warning source-caveat"')

    assert warnings("FEDIAF2025") == 2
    assert warnings("SciRep2025") == 2
    assert warnings("Bermingham2014") == 0
