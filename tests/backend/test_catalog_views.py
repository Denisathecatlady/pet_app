"""Public library of sources: list, filters, search, pagination, detail, legend, banner,
escaping and the number of database queries."""

import html
import re
from datetime import date
from itertools import pairwise

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.html import strip_tags

from catalog.display import EVIDENCE_NAMES, VERIFICATION_STYLES, evidence_name, verification_style
from catalog.models import EvidenceLevel, ScientificSource, VerificationLevel
from catalog.services import PAGE_SIZE, SourceQuery, parse_query, search_sources

pytestmark = pytest.mark.django_db

LIST = reverse("catalog:source_list")
BANNER = "Zdroj v knihovně není automaticky ověřený v originále."


def detail(key: str) -> str:
    return reverse("catalog:source_detail", args=[key])


def flat(response) -> str:
    """The HTML of a response with entities decoded and white space collapsed (line breaks in
    the templates must not matter to a test that looks for a sentence)."""
    return " ".join(html.unescape(response.content.decode()).split())


def keys_on(response) -> list[str]:
    """Citation keys of the list items, in page order."""
    return re.findall(r'<code class="source-key">([^<]+)</code> [^<]', response.content.decode())


@pytest.fixture
def library(empty_library, make_source):
    """A small, known library: five sources that differ in every filterable field."""
    return {
        "guide": make_source(
            citation_key="Guide1",
            title="Standard krmiva",
            authors_or_org="FEDIAF",
            year=2025,
            source_type="GUIDELINE",
            evidence_level="L1",
            species_scope="BOTH",
            verification_level="S",
            verification_markers=["B", "S"],
            last_verified_at=date(2026, 10, 18),
        ),
        "dogs": make_source(
            citation_key="Dogs1",
            title="Energy of adult dogs",
            authors_or_org="Smith J",
            year=2014,
            source_type="META_ANALYSIS",
            evidence_level="L2",
            species_scope="DOG",
            verification_level="A",
            verification_markers=["B", "A"],
            last_verified_at=date(2026, 10, 18),
        ),
        "cats": make_source(
            citation_key="Cats1",
            title="Taurine in cats",
            authors_or_org="Novák P",
            year=1987,
            source_type="ORIGINAL_STUDY",
            evidence_level="L3",
            species_scope="CAT",
            verification_level="P",
            verification_markers=["P"],
            last_verified_at=date(2026, 10, 18),
        ),
        "food": make_source(
            citation_key="Food1",
            title="Food composition tables",
            authors_or_org="ANSES",
            year=None,
            source_type="FOOD_DATABASE",
            evidence_level="L5",
            species_scope="NOT_APPLICABLE",
        ),
        "wiki": make_source(
            citation_key="Wiki1",
            title="Wiki page",
            authors_or_org="",
            year=2023,
            source_type="SECONDARY",
            evidence_level="L6",
            species_scope="BOTH",
            verification_level="B",
            verification_markers=["B"],
            last_verified_at=date(2026, 10, 18),
        ),
    }


# --- Access and layout -------------------------------------------------------------------------


def test_list_and_detail_are_public(client):
    """No sign-in: no redirect to the login page."""
    assert client.get(LIST).status_code == 200
    assert client.get(detail("NRC2006")).status_code == 200


def test_signed_in_users_see_the_same_pages(logged_in_client):
    assert logged_in_client.get(LIST).status_code == 200
    assert logged_in_client.get(detail("NRC2006")).status_code == 200


@pytest.mark.parametrize("url", [LIST, detail("NRC2006")])
def test_pages_have_layout_security_and_one_heading(client, url):
    response = client.get(url)
    content = response.content.decode()

    assert '<html lang="cs">' in content and 'class="skip-link"' in content
    assert content.count("<h1") == 1
    assert "Aplikace nenahrazuje veterinární péči." in content
    assert "<script" not in content and " style=" not in content  # CSP: no inline code
    assert "script-src 'self'" in response["Content-Security-Policy"]
    # Headings go down one level at a time.
    levels = [int(level) for level in re.findall(r"<h([1-6])[ >]", content)]
    assert levels[0] == 1 and all(b - a <= 1 for a, b in pairwise(levels))


def test_navigation_links_to_the_library_for_everyone(client, logged_in_client):
    for visitor in (client, logged_in_client):
        content = visitor.get(reverse("core:terms")).content.decode()
        assert f'href="{LIST}"' in content and "Knihovna zdrojů" in content


def test_navigation_marks_the_current_page(client):
    assert f'<a href="{LIST}" aria-current="page">' in client.get(LIST).content.decode()
    assert (
        f'<a href="{LIST}" aria-current="true">' in client.get(detail("NRC2006")).content.decode()
    )
    assert (
        "aria-current"
        not in client.get(reverse("core:terms"))
        .content.decode()
        .split('class="site-nav"', 1)[1]
        .split("</nav>")[0]
    )


def test_home_page_mentions_the_library(client):
    assert f'href="{LIST}"' in client.get(reverse("core:home")).content.decode()


@pytest.mark.parametrize("url", [LIST, detail("NRC2006")])
def test_pages_accept_only_get(client, url):
    assert client.post(url).status_code == 405
    assert client.put(url).status_code == 405
    assert client.delete(url).status_code == 405
    assert client.head(url).status_code == 200


def test_unknown_key_is_404(client):
    for key in ("NEEXISTUJE", "nrc2006", "NRC2006x", "x" * 80):
        assert client.get(detail(key)).status_code == 404, key
    assert client.get("/zdroje/NRC 2006/").status_code == 404
    assert client.get("/zdroje/NRC2006").status_code == 301  # APPEND_SLASH


# --- Banner and legend ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [LIST, detail("NRC2006"), detail("USDA-FDC")])
def test_banner_says_a_listed_source_is_not_verified_in_the_original(client, url):
    content = client.get(url).content.decode()
    assert BANNER in content
    assert 'class="notice notice--warning" role="note"' in content
    assert 'aria-hidden="true">⚠</span>' in content  # icon + text + colour
    assert "stav ověření" in content


@pytest.mark.parametrize("url", [LIST, detail("NRC2006")])
def test_legend_explains_every_level(client, url):
    text = html.unescape(client.get(url).content.decode())

    assert 'id="legenda"' in text
    for level in EvidenceLevel:
        assert f'<span class="evidence__code">{level.value}</span>' in text
        assert f"{level.label}." in text
    for level in VerificationLevel:
        assert f"status--verif-{VERIFICATION_STYLES[level.value].css}" in text
        assert f"{level.label}." in text


def test_gaps_block_is_on_the_list_only(client):
    assert "Co zatím chybí" in client.get(LIST).content.decode()
    assert "Co zatím chybí" not in client.get(detail("NRC2006")).content.decode()


# --- Verification is icon + text + colour --------------------------------------------------------


@pytest.mark.parametrize("level", VerificationLevel.values)
def test_verification_badge_has_icon_text_and_colour_class(client, library, make_source, level):
    extra = (
        {}
        if level == "NONE"
        else {
            "verification_markers": [level],
            "last_verified_at": date(2026, 10, 18),
        }
    )
    source = make_source(citation_key="Badge1", verification_level=level, **extra)
    style = VERIFICATION_STYLES[level]

    for url in (LIST + "?q=Badge1", detail(source.citation_key)):
        content = client.get(url).content.decode()
        assert (
            f'<span class="status status--verif-{style.css}">'
            f'<span class="status__icon" aria-hidden="true">{style.icon}</span>'
            f'<span class="status__label">{html.escape(style.name)}</span></span>'
        ) in content


def test_verification_levels_differ_in_icon_text_and_class():
    styles = list(VERIFICATION_STYLES.values())
    for field in ("css", "icon", "name"):
        assert len({getattr(style, field) for style in styles}) == len(styles)
    assert set(VERIFICATION_STYLES) == set(VerificationLevel.values)
    assert set(EVIDENCE_NAMES) == set(EvidenceLevel.values)


def test_unknown_levels_never_render_as_neutral():
    with pytest.raises(ValueError):
        verification_style("X")
    with pytest.raises(ValueError):
        evidence_name("L9")


# --- Filters --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", {"Guide1", "Dogs1", "Cats1", "Food1", "Wiki1"}),
        ("uroven=L1", {"Guide1"}),
        ("uroven=L5", {"Food1"}),
        ("uroven=L4", set()),
        ("druh=BOTH", {"Guide1", "Wiki1"}),
        ("druh=DOG", {"Dogs1", "Guide1", "Wiki1"}),  # the sources about both species too
        ("druh=CAT", {"Cats1", "Guide1", "Wiki1"}),
        ("druh=NOT_APPLICABLE", {"Food1"}),
        ("typ=META_ANALYSIS", {"Dogs1"}),
        ("typ=SECONDARY", {"Wiki1"}),
        ("typ=LAB_ANALYSIS", set()),
        ("overeni=P", {"Cats1"}),
        ("overeni=NONE", {"Food1"}),
        ("overeni=B", {"Wiki1"}),
        ("druh=BOTH&overeni=S", {"Guide1"}),
        ("druh=DOG&overeni=S", {"Guide1"}),
        ("druh=CAT&overeni=A", set()),
        ("druh=BOTH&uroven=L1&typ=GUIDELINE&overeni=S&q=standard", {"Guide1"}),
        ("druh=DOG&overeni=P", set()),
    ],
)
def test_filters(client, library, query, expected):
    response = client.get(f"{LIST}?{query}")
    assert response.status_code == 200
    assert set(keys_on(response)) == expected


def test_dogs_filter_includes_the_sources_about_both_species(client):
    """?druh=DOG used to hide the main guidelines (FEDIAF, NRC, AAFCO, WSAVA) because they
    are about both species: a dog owner saw the least authoritative subset."""
    dogs = set(keys_on(client.get(LIST, {"druh": "DOG", "uroven": "L1"})))
    cats = set(keys_on(client.get(LIST, {"druh": "CAT", "uroven": "L1"})))
    both = set(keys_on(client.get(LIST, {"druh": "BOTH", "uroven": "L1"})))

    assert {"FEDIAF2025", "NRC2006", "AAFCO2014", "WSAVA2011"} <= dogs
    assert {"FEDIAF2025", "NRC2006", "AAFCO2014", "WSAVA2011"} <= cats
    assert both <= dogs and both <= cats
    assert "Pion1987" not in set(keys_on(client.get(LIST, {"druh": "DOG"})))  # a cat-only study
    assert "Bermingham2014" not in set(keys_on(client.get(LIST, {"druh": "CAT"})))  # dogs only


def test_species_filter_options_say_what_they_include(client, library):
    content = html.unescape(client.get(LIST).content.decode())

    assert '<option value="DOG">psi (i zdroje o psech i kočkách)</option>' in content
    assert '<option value="CAT">kočky (i zdroje o psech i kočkách)</option>' in content
    assert '<option value="BOTH">jen zdroje o psech i kočkách</option>' in content
    assert '<option value="NOT_APPLICABLE">druh se neuplatňuje</option>' in content
    assert "přesnou hodnotu" not in content


@pytest.mark.parametrize(
    "query",
    [
        "uroven=L9",
        "uroven=l1",
        "uroven=L1%20",
        "uroven=%3Cscript%3E",
        "uroven[]=L1",
        "druh=dog",
        "druh=DOG,CAT",
        "typ=NOPE",
        "overeni=Z",
        "overeni=none",
        "overeni=",
        "neznamy=1",
        "uroven=L1&uroven=L2",
    ],
)
def test_invalid_filter_values_are_ignored(client, library, query):
    """A value that is not allowed behaves as if it were missing (the last of repeated
    parameters counts, as for every Django view)."""
    response = client.get(f"{LIST}?{query}")
    assert response.status_code == 200
    if query == "uroven=L1&uroven=L2":
        assert set(keys_on(response)) == {"Dogs1"}
    else:
        assert len(keys_on(response)) == 5


def test_chosen_values_stay_selected_in_the_form(client, library):
    content = client.get(
        f"{LIST}?uroven=L2&druh=DOG&typ=META_ANALYSIS&overeni=A&q=energy"
    ).content.decode()
    for name, value in [
        ("uroven", "L2"),
        ("druh", "DOG"),
        ("typ", "META_ANALYSIS"),
        ("overeni", "A"),
    ]:
        assert re.search(
            rf'<select id="id_{name}" name="{name}">.*?<option value="{value}" selected>',
            content,
            re.DOTALL,
        )
    assert 'name="q" value="energy"' in content
    assert "Zrušit filtry" in content
    assert "Počet nalezených zdrojů: 1 z 5." in content


def test_form_without_filters_has_no_reset_link(client, library):
    content = client.get(LIST).content.decode()
    assert "Zrušit filtry" not in content and "Počet zdrojů v knihovně: 5." in content


def test_form_is_labelled_and_is_a_get_search_form(client, library):
    content = client.get(LIST).content.decode()
    assert 'role="search"' in content and 'method="get"' in content
    for name in ("q", "uroven", "druh", "typ", "overeni"):
        assert f'<label for="id_{name}">' in content and f'id="id_{name}"' in content
    assert 'type="search"' in content and "csrfmiddlewaretoken" not in content


def test_no_match_shows_an_explanation_and_a_way_back(client, library):
    content = client.get(f"{LIST}?uroven=L4").content.decode()
    assert "Žádný zdroj neodpovídá zadaným podmínkám." in content
    assert "Zrušit filtry a zobrazit všechny zdroje" in content
    assert "Počet nalezených zdrojů: 0 z 5." in content
    assert BANNER in content and 'id="legenda"' in content  # the page is still complete


def test_empty_library(client, empty_library):
    content = client.get(LIST).content.decode()
    assert "Počet zdrojů v knihovně: 0." in content
    assert "Žádný zdroj neodpovídá zadaným podmínkám." in content


# --- Search ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("guide1", {"Guide1"}),  # key, any letter case
        ("DOGS", {"Dogs1"}),
        ("taurine", {"Cats1"}),  # title
        ("TAURINE IN", {"Cats1"}),
        ("energy dogs", {"Dogs1"}),  # every word must be found
        ("energy cats", set()),
        ("novák", {"Cats1"}),  # authors, with diacritics
        ("Smith", {"Dogs1"}),
        ("anses tables", {"Food1"}),  # words may come from different fields
        ("  wiki   page  ", {"Wiki1"}),  # white space is collapsed
        ("%", set()),  # LIKE wildcards are literal
        ("_", set()),
        ("nic takového", set()),
        ("' OR 1=1 --", set()),
        ("\\", set()),
        ("", {"Guide1", "Dogs1", "Cats1", "Food1", "Wiki1"}),
        ("   ", {"Guide1", "Dogs1", "Cats1", "Food1", "Wiki1"}),
    ],
)
def test_text_search(client, library, q, expected):
    response = client.get(LIST, {"q": q})
    assert response.status_code == 200
    assert set(keys_on(response)) == expected


def test_search_does_not_look_in_other_fields(client, library, make_source):
    make_source(citation_key="Hidden1", title="x", key_findings="tajnétextveznaleních")
    assert keys_on(client.get(LIST, {"q": "tajnétextveznaleních"})) == []


def test_search_survives_hostile_input(client, library):
    for q in (
        "\x00",
        "a\x00b",
        "\x1f\x7f",
        "x" * 5000,
        "😀" * 300,
        "\ud800".encode("utf-8", "ignore").decode(),
    ):
        assert client.get(LIST, {"q": q}).status_code == 200


def test_long_text_is_cut_to_100_characters():
    query = parse_query({"q": "ab " + "x" * 500})
    assert len(query.text) == 100 and query.text.startswith("ab xxx")


def test_search_term_is_escaped_in_the_form(client, library):
    content = client.get(LIST, {"q": '"><script>alert(1)</script>'}).content.decode()
    assert "<script>alert(1)" not in content
    assert 'value="&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"' in content


# --- Query parameters -----------------------------------------------------------------------------


def test_parse_query_whitelists_every_parameter():
    assert parse_query({}) == SourceQuery()
    full = parse_query(
        {
            "q": " a  b ",
            "uroven": "L2",
            "druh": "CAT",
            "typ": "REVIEW",
            "overeni": "NONE",
            "strana": "3",
        }
    )
    assert full == SourceQuery("a b", "L2", "CAT", "REVIEW", "NONE", 3)
    assert full.is_filtered and not SourceQuery(page=4).is_filtered
    for bad in ("0", "-1", "abc", "1.5", "1e3", " 2", "٣", "9" * 50, "", "²"):
        assert parse_query({"strana": bad}).page == 1, bad
    assert parse_query({"q": 5, "uroven": ["L1"], "strana": 2}) == SourceQuery()  # not text


def test_query_string_keeps_filters_and_omits_page_one():
    query = SourceQuery(text="a b", evidence="L1", verification="NONE")
    assert query.query_string() == "q=a+b&uroven=L1&overeni=NONE"
    assert query.query_string(3) == "q=a+b&uroven=L1&overeni=NONE&strana=3"
    assert SourceQuery().query_string(1) == ""


# --- Pagination -----------------------------------------------------------------------------------


@pytest.fixture
def sixty(empty_library, make_source):
    """60 sources: 30 of level L1 (newest year first) and 30 of level L3."""
    for number in range(1, 61):
        old = number <= 30
        make_source(
            citation_key=f"S{number:02d}",
            title=f"Zdroj číslo {number}",
            year=1950 + number,
            source_type="GUIDELINE" if old else "ORIGINAL_STUDY",
            evidence_level="L1" if old else "L3",
            species_scope="BOTH" if number % 2 else "DOG",
        )


def test_pages_hold_25_sources_in_a_stable_order(client, sixty):
    assert PAGE_SIZE == 25
    pages = [keys_on(client.get(LIST, {"strana": number})) for number in (1, 2, 3)]

    assert [len(page) for page in pages] == [25, 25, 10]
    every = [key for page in pages for key in page]
    assert len(set(every)) == 60
    # Evidence level first (L1 before L3), then the newest year, then the key.
    assert every[:30] == [f"S{number:02d}" for number in range(30, 0, -1)]
    assert every[30:] == [f"S{number:02d}" for number in range(60, 30, -1)]


def test_pagination_links_keep_the_filters(client, sixty):
    content = client.get(LIST, {"druh": "BOTH", "q": "zdroj", "strana": 1}).content.decode()
    assert "Strana 1 z 2" in content
    assert 'rel="next" href="?q=zdroj&amp;druh=BOTH&amp;strana=2"' in content
    assert 'rel="prev"' not in content

    second = client.get(LIST, {"druh": "BOTH", "q": "zdroj", "strana": 2}).content.decode()
    assert 'rel="prev" href="?q=zdroj&amp;druh=BOTH"' in second  # page 1 has no parameter
    assert 'rel="next"' not in second
    assert "Na této stránce jsou zdroje 26–30." in second
    assert 'aria-label="Stránkování seznamu zdrojů"' in second


def test_single_page_has_no_pagination(client, library):
    content = client.get(LIST).content.decode()
    assert "Stránkování" not in content and "Strana " not in content


@pytest.mark.parametrize("page", ["0", "-3", "abc", "4", "999", "1e1", "9" * 30])
def test_invalid_or_missing_pages_show_the_first_page(client, sixty, page):
    response = client.get(LIST, {"strana": page})
    assert response.status_code == 200
    assert keys_on(response)[0] == "S30" and "Strana 1 z 3" in response.content.decode()


def test_page_beyond_the_end_after_filtering_shows_the_first_page(client, sixty):
    response = client.get(LIST, {"typ": "ORIGINAL_STUDY", "strana": 3})
    assert len(keys_on(response)) == 25 and "Strana 1 z 2" in response.content.decode()


def test_search_result_reports_the_page_actually_shown(sixty):
    result = search_sources(SourceQuery(page=99))
    assert result.query.page == 1 and (result.matched, result.total) == (60, 60)


def test_list_does_not_claim_that_the_application_relies_on_the_sources(client, library):
    """Nothing in the application uses a source yet (docs/15-zdroje-v-aplikaci.md §15.7)."""
    text = " ".join(html.unescape(strip_tags(client.get(LIST).content.decode())).split())

    assert "na které se aplikace odvolává" not in text
    assert "Zdroje zatím nejsou v aplikaci k ničemu použité" in text
    assert "neznamená, že z něj aplikace vychází" in text


def test_the_level_is_called_what_the_registry_calls_it(client, library):
    list_page = client.get(LIST).content.decode()
    detail_page = client.get(library["guide"].get_absolute_url()).content.decode()

    assert "Úroveň odbornosti zdroje" in list_page
    assert "<dt>Úroveň odbornosti zdroje</dt>" in detail_page
    assert "Legenda: úroveň odbornosti zdroje a stav ověření" in list_page
    for page in (list_page, detail_page):
        assert "Úroveň důkazů" not in page and "úrovně důkazů" not in page.lower()


def test_list_item_shows_the_type_note_of_the_registry(client, empty_library, make_source):
    make_source(
        citation_key="Noted1",
        source_type="GUIDELINE",
        evidence_level="L1",
        type_note="Průmyslová doporučení, právně nezávazná",
    )
    make_source(citation_key="Plain1")

    content = client.get(LIST).content.decode()

    assert (
        "Typ: doporučení, standard nebo regulační profil (Průmyslová doporučení, právně" in content
    )
    assert "Typ: původní studie · Druh zvířat" in content  # no empty parentheses


# --- Detail ---------------------------------------------------------------------------------------


def test_detail_shows_every_field(client, empty_library, make_source, user):
    source = make_source(
        citation_key="Full1",
        title="Úplný zdroj",
        authors_or_org="Autor A, Autorka B",
        year=2021,
        publication_details="J Test. 2021;1(2):3–4.",
        doi="10.1000/full.1",
        url="https://example.org/full",
        source_type="ORIGINAL_STUDY",
        type_note="Validační studie",
        evidence_level="L3",
        species_scope="CAT",
        life_stages=["ADULT", "GROWTH"],
        units_and_conditions="Na 100 g sušiny.",
        edition_version="2. vydání",
        verification_level="A",
        verification_markers=["B", "A"],
        verification_note="B (částečně), A",
        last_verified_at=date(2026, 10, 18),
        verified_by=user,
        limitations="Jen malý vzorek.",
        key_findings="Zjištění č. 1.",
    )

    response = client.get(source.get_absolute_url())
    text = html.unescape(response.content.decode())

    assert "<h1>Úplný zdroj</h1>" in text
    for expected in (
        "Full1",
        "Autor A, Autorka B",
        "2021",
        "J Test. 2021;1(2):3–4.",
        "2. vydání",
        'href="https://doi.org/10.1000/full.1"',
        "10.1000/full.1",
        'href="https://example.org/full"',
        'rel="noopener noreferrer external"',
        "původní studie (Validační studie)",
        "kočky",
        "dospělí, růst",
        "Na 100 g sušiny.",
        "L3",
        "Původní recenzovaná studie (experimentální, observační).",
        "Bibliografické údaje (autoři, rok, časopis, ročník, strany) ověřeny.",
        "Ověřen obsah abstraktu nebo souhrnu (hlavní zjištění).",
        "Poznámka k ověření v registru",
        "B (částečně), A",
        "18. 10. 2026",
        "Jen malý vzorek.",
        "Zjištění č. 1.",
        "ne doporučení pro krmení",
        "Zdroj v knihovně není automaticky ověřený v originále.",
    ):
        assert expected in text, expected


def test_detail_never_shows_who_verified(client, empty_library, make_source, user):
    source = make_source(
        verification_level="B",
        verification_markers=["B"],
        last_verified_at=date(2026, 10, 18),
        verified_by=user,
    )
    content = client.get(source.get_absolute_url()).content.decode()
    assert user.email not in content and user.email.split("@")[0] not in content
    assert "kurátor aplikace (jméno se veřejně nezobrazuje)" in content


def test_detail_names_missing_values(client, empty_library, make_source):
    source = make_source(authors_or_org="", year=None)
    content = client.get(source.get_absolute_url()).content.decode()
    for text in (
        "neuvedeno",
        "neuveden",
        "Registr u tohoto zdroje hlavní zjištění neuvádí.",
        "Registr u tohoto zdroje omezení neuvádí.",
        "Registr u tohoto zdroje nepřiřazuje žádnou ze značek B, A, P, S.",
    ):
        assert text in content, text
    assert "None" not in content


def test_detail_without_links_has_no_empty_anchor(client, empty_library, make_source):
    content = client.get(make_source().get_absolute_url()).content.decode()
    assert 'href=""' not in content and "doi.org" not in content


def test_real_library_detail_pages_render(client):
    """Every source loaded from the shipped file has a working page."""
    for key in ScientificSource.objects.values_list("citation_key", flat=True):
        response = client.get(detail(key))
        assert response.status_code == 200, key
        assert (
            f"<h1>{html.escape(ScientificSource.objects.get(citation_key=key).title)}</h1>"
            in response.content.decode()
        )


def test_unverified_real_sources_say_so(client):
    content = client.get(detail("USDA-FDC")).content.decode()
    assert "Neověřeno. Uvedeno z odborné znalosti. Před použitím je nutné to ověřit." in content
    assert "status--verif-none" in content
    assert "Licence (předpoklad CC0 / public domain) neověřena." in content


def test_a_year_the_registry_doubts_is_not_shown_as_certain(client):
    content = client.get(detail("PuppyIntake2019")).content.decode()
    listed = client.get(LIST, {"q": "PuppyIntake2019"}).content.decode()

    assert "<dt>Rok</dt><dd>neuveden</dd>" in content
    assert "Rok vydání je v registru uveden s otazníkem" in html.unescape(content)
    assert ", 2019" not in listed  # the list item shows no year


@pytest.mark.parametrize("key", ["NRC2006", "vanBree2018"])
def test_a_doi_the_registry_could_not_verify_is_marked(client, key):
    content = client.get(detail(key)).content.decode()
    assert "(DOI je podle registru neověřený)" in content


def test_a_verified_doi_is_not_marked(client):
    content = client.get(detail("Stockman2013")).content.decode()
    assert "doi.org/10.2460/javma.242.11.1500" in content
    assert "DOI je podle registru neověřený" not in content


def test_the_doi_mark_follows_the_note_of_the_registry(empty_library, make_source):
    marked = make_source(
        citation_key="Doi1", doi="10.1000/x", verification_note="B. DOI zatím neověřen."
    )
    other = make_source(citation_key="Doi2", doi="10.1000/y", verification_note="B.")
    no_doi = make_source(citation_key="Doi3", verification_note="DOI neověřen.")

    assert (marked.doi_unverified, other.doi_unverified, no_doi.doi_unverified) == (
        True,
        False,
        False,
    )


def test_detail_does_not_call_registry_notes_verified_facts(client):
    """The note is the registry's text, which also holds open tasks ("autory doplnit")."""
    content = flat(client.get(detail("Morris2002")))

    assert "Poznámka k ověření v registru" in content
    assert "Co přesně bylo ověřeno" not in content
    assert "Slova „doplnit“ a „ověřit“ jsou otevřené úkoly registru" in content
    assert "A (název a ročník ověřit)" in content


def test_unverified_source_without_a_mark_is_not_called_known_from_expertise(client):
    """The registry says "Existence ověřena" for SciRep2025 and gives no mark: the page must
    neither claim that the source was verified nor leave the contradiction unexplained."""
    content = flat(client.get(detail("SciRep2025")))

    assert "Zdroj proto považujeme za neověřený." in content
    assert "co registr o zdroji ví (například že existuje)" in content
    assert "Existence ověřena" in content


def test_numbers_of_unverified_sources_carry_a_warning(client):
    scirep = flat(client.get(detail("SciRep2025")))
    fediaf = flat(client.get(detail("FEDIAF2025")))
    mdpi = flat(client.get(detail("MDPI2025")))

    assert "Ca 1,25 g a P 1,00 g / 1 000 kcal" in scirep
    assert scirep.index("Zdroj je neověřený. Čísla a zjištění") < scirep.index("Ca 1,25 g") + 400
    assert "Obsah byl ověřen jen přes sekundární zdroj" in fediaf
    assert "95 nebo 110 kcal ME" in fediaf
    assert "Obsah byl ověřen jen přes sekundární zdroj" in mdpi


def test_legend_speaks_to_readers_and_marks_the_order_of_marks_as_provisional(client):
    text = " ".join(html.unescape(strip_tags(client.get(LIST).content.decode())).split())

    assert "Síťová politika" not in text and "vývojového prostředí" not in text
    assert "Štítek ukazuje nejvyšší dosaženou značku" in text
    assert "je pracovní a potvrdí ho veterinární nutriční specialista" in text
    assert "O textech u zdrojů" in text
    assert "věty v první osobě pocházejí od vývojářů registru" in text


def test_legend_lists_the_verification_levels_from_strongest_to_weakest(client):
    content = client.get(LIST).content.decode()
    legend = content.split('id="legend-verification"', 1)[1]
    shown = re.findall(r"status--verif-(\w+)", legend)

    assert shown[:5] == ["p", "a", "s", "b", "none"]


# --- Escaping -------------------------------------------------------------------------------------

HOSTILE = "<script>alert('x')</script><img src=x onerror=alert(1)>"


def test_texts_are_escaped_everywhere(client, empty_library, make_source):
    source = make_source(
        citation_key="Xss1",
        title=HOSTILE + " titul",
        authors_or_org=HOSTILE,
        publication_details=HOSTILE,
        type_note=HOSTILE,
        units_and_conditions=HOSTILE,
        edition_version=HOSTILE,
        verification_note=HOSTILE,
        limitations=HOSTILE,
        key_findings=HOSTILE,
    )
    for url in (LIST, source.get_absolute_url()):
        content = client.get(url).content.decode()
        assert "<script>alert" not in content and "<img src=x" not in content
        assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in content


def test_quote_in_url_cannot_break_the_attribute(client, empty_library, make_source):
    source = make_source(url='https://example.org/a"onmouseover="alert(1)')
    content = client.get(source.get_absolute_url()).content.decode()
    assert 'onmouseover="alert' not in content
    assert "&quot;onmouseover=" in content


# --- Number of queries ----------------------------------------------------------------------------


def count_queries(client, url: str, **params) -> int:
    with CaptureQueriesContext(connection) as queries:
        assert client.get(url, params).status_code == 200
    return len(queries)


def test_list_query_count_does_not_depend_on_the_number_of_sources(
    client, empty_library, make_source
):
    for number in range(3):
        make_source(citation_key=f"A{number}")
    few = count_queries(client, LIST)
    for number in range(60):
        make_source(citation_key=f"B{number:02d}", verification_level="NONE")
    many_first = count_queries(client, LIST)
    many_filtered = count_queries(client, LIST, uroven="L3", q="Testovací", strana=2)

    assert few == many_first == many_filtered == 3  # matches, the page, all sources


def test_detail_query_count_is_constant(client, empty_library, make_source, user):
    plain = make_source(citation_key="Plain1")
    full = make_source(
        citation_key="Full1",
        verification_level="B",
        verification_markers=["B"],
        last_verified_at=date(2026, 10, 18),
        verified_by=user,
        life_stages=["ADULT", "GROWTH"],
    )
    assert count_queries(client, plain.get_absolute_url()) == 1
    assert count_queries(client, full.get_absolute_url()) == 1


def test_signed_in_users_cost_a_constant_extra(logged_in_client, empty_library, make_source):
    make_source(citation_key="A1")
    small = count_queries(logged_in_client, LIST)
    for number in range(40):
        make_source(citation_key=f"M{number:02d}")
    assert count_queries(logged_in_client, LIST) == small
