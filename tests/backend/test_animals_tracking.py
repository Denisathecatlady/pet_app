"""Tracking page /zvirata/<uuid>/hmotnost/: permissions, periods, SVG charts, data table.

docs/08 §8.3 (Sledování hmotnosti a kondice), docs/12 §12.11.
"""

import ast
import re
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from animals import services
from animals.models import AnimalShare, Assessor, MuscleCondition
from config.settings.base import BASE_DIR

pytestmark = pytest.mark.django_db

NBSP = "\xa0"
TODAY = timezone.localdate()


def url_of(animal, period: str | None = None) -> str:
    base = reverse("animals:tracking", args=[animal.uuid])
    return base if period is None else f"{base}?obdobi={period}"


def days_ago(days: int):
    return TODAY - timedelta(days=days)


def all_svgs(content: str) -> list[ET.Element]:
    """All chart SVGs of a page (``role="img"``) parsed as XML; legend icons are skipped.

    Every chart is in the page twice: the wide layout and the compact one for narrow screens
    (CSS shows one of them).
    """
    found = re.findall(r"<svg\b.*?</svg>", content, flags=re.DOTALL)
    parsed = [ET.fromstring(fragment) for fragment in found]
    return [svg for svg in parsed if svg.get("role") == "img"]


def svgs(content: str, layout: str = "wide") -> list[ET.Element]:
    """The chart SVGs of one layout (``wide`` or ``compact``): weight chart, then BCS chart."""
    return [s for s in all_svgs(content) if f"chart__svg--{layout}" in s.get("class", "")]


def flat(content: str) -> str:
    """Collapse the line breaks and indentation of the template (no-break spaces stay)."""
    return re.sub(r"[ \t\r\n]+", " ", content)


def text_of(element: ET.Element, tag: str) -> str:
    return next(element.iter(tag)).text or ""


@pytest.fixture
def animal(user, make_animal):
    return make_animal(user, name="Rex", target_weight_kg=Decimal("19"))


@pytest.fixture
def filled(animal, make_measurement):
    """Measurements 5, 50, 200 and 500 days ago, the 50-day one assessed by a vet."""
    for days, weight, bcs in [(500, "23", 7), (200, "22", None), (50, "21", 5), (5, "20.4", 5)]:
        make_measurement(
            animal,
            measured_on=days_ago(days),
            weight_kg=Decimal(weight),
            bcs=bcs,
            assessed_by=Assessor.VET if days == 50 else Assessor.OWNER,
            note=f"poznámka {days}",
        )
    return animal


# --- Permissions ------------------------------------------------------------------------------


def test_owner_sees_the_page(client, user, filled):
    client.force_login(user)
    response = client.get(url_of(filled))
    assert response.status_code == 200
    content = response.content.decode()
    assert "<h1>Sledování hmotnosti a kondice</h1>" in content
    assert "Rex" in content


def test_vet_with_an_active_share_sees_the_page(client, vet_user, user, filled):
    AnimalShare.objects.create(animal=filled, vet=vet_user, granted_by=user)
    client.force_login(vet_user)
    assert client.get(url_of(filled)).status_code == 200


def test_vet_with_a_revoked_share_gets_404(client, vet_user, user, filled):
    AnimalShare.objects.create(
        animal=filled, vet=vet_user, granted_by=user, revoked_at=timezone.now()
    )
    client.force_login(vet_user)
    assert client.get(url_of(filled)).status_code == 404


def test_vet_without_a_share_gets_404(client, vet_user, filled):
    client.force_login(vet_user)
    assert client.get(url_of(filled)).status_code == 404


def test_vet_who_lost_the_role_gets_404(client, vet_user, user, filled):
    AnimalShare.objects.create(animal=filled, vet=vet_user, granted_by=user)
    vet_user.groups.clear()
    client.force_login(vet_user)
    assert client.get(url_of(filled)).status_code == 404


def test_another_owner_gets_404(client, make_user, filled):
    client.force_login(make_user("other@example.cz"))
    response = client.get(url_of(filled))
    assert response.status_code == 404
    assert "Rex" not in response.content.decode()


def test_anonymous_is_redirected_to_login(client, filled):
    response = client.get(url_of(filled))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:login"))


def test_unknown_animal_gets_404(client, user):
    client.force_login(user)
    unknown = reverse("animals:tracking", args=["00000000-0000-0000-0000-000000000000"])
    assert client.get(unknown).status_code == 404


def test_page_is_not_cached_and_only_reads(client, user, filled):
    client.force_login(user)
    response = client.get(url_of(filled))
    assert "no-store" in response["Cache-Control"]
    assert client.post(url_of(filled)).status_code == 405


# --- Period -----------------------------------------------------------------------------------


def current_links(content: str) -> list[str]:
    return re.findall(r'<a href="\?obdobi=([^"]*)" aria-current="([^"]*)">', content)


@pytest.mark.parametrize("param", ["30", "90", "365", "vse"])
def test_period_switcher_marks_the_chosen_period(client, user, filled, param):
    client.force_login(user)
    content = client.get(url_of(filled, param)).content.decode()
    assert current_links(content) == [(param, "true")]
    for other in {"30", "90", "365", "vse"} - {param}:
        assert f'<a href="?obdobi={other}">' in content  # a link, not current
    assert '<nav aria-label="Zobrazené období"' in content


@pytest.mark.parametrize("param", [None, "", "7", "abc", "-30", "VSE", "30%00", "<script>", "9999"])
def test_invalid_period_falls_back_to_90_days_without_an_error(client, user, filled, param):
    client.force_login(user)
    response = client.get(url_of(filled) + ("" if param is None else f"?obdobi={param}"))
    assert response.status_code == 200
    assert current_links(response.content.decode()) == [("90", "true")]
    assert "<script>" not in response.content.decode()


@pytest.mark.parametrize(
    ("param", "days"),
    [("30", [5]), ("90", [5, 50]), ("365", [5, 50, 200]), ("vse", [5, 50, 200, 500])],
)
def test_period_selects_the_measurements_of_chart_and_table(client, user, filled, param, days):
    client.force_login(user)
    content = client.get(url_of(filled, param)).content.decode()
    rows = re.findall(r'<tr>\s*<td class="date">(\d+\. \d+\. \d+)</td>', content)
    assert rows == [services.short_date(days_ago(d)) for d in days]  # newest first
    charts_found = svgs(content)
    if len(days) >= 2:
        marks = [e for e in charts_found[0].iter() if "chart__point" in (e.get("class") or "")]
        assert len(marks) == len(days)  # the chart draws what the table lists
    else:
        assert not charts_found  # one measurement: empty state instead of a chart


def test_table_notes_measurements_outside_the_period(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled, "30")).content.decode()
    assert "Mimo zobrazené období jsou další 3 měření" in content
    assert '<a href="?obdobi=vse">zobrazit vše</a>' in content
    assert "další" not in client.get(url_of(filled, "vse")).content.decode()


# --- SVG and ARIA -------------------------------------------------------------------------------


def test_weight_chart_svg_is_an_image_with_title_and_description(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled, "365")).content.decode()
    weight, bcs = svgs(content)

    assert weight.get("role") == "img"
    # The name is the short title only; the long summary is the description, read once.
    assert weight.get("aria-labelledby") == "weight-svg-title-wide"
    assert weight.get("aria-describedby") == "weight-svg-desc-wide"
    assert weight.get("focusable") == "false"
    title, desc = weight.find("title"), weight.find("desc")
    assert (title.get("id"), desc.get("id")) == ("weight-svg-title-wide", "weight-svg-desc-wide")
    assert title.text == "Graf hmotnosti zvířete Rex za poslední rok"
    # The description tells the story in words: period, count, first and last, change.
    assert "3 měření" in desc.text
    assert f"První hmotnost 22{NBSP}kg dne {services.short_date(days_ago(200))}" in desc.text
    assert f"poslední 20,4{NBSP}kg dne {services.short_date(days_ago(5))}" in desc.text
    assert f"Změna hmotnosti za zvolené období: \N{MINUS SIGN}1,6{NBSP}kg" in desc.text
    assert "Zda je změna žádoucí, posoudí veterinární lékař." in desc.text
    assert "kosočtverce značí měření zapsaná veterinárním lékařem" in desc.text

    assert bcs.get("aria-labelledby") == "bcs-svg-title-wide"
    assert bcs.get("aria-describedby") == "bcs-svg-desc-wide"
    assert text_of(bcs, "title") == "Graf BCS zvířete Rex za poslední rok"
    assert "pásmo 4–5 z 9" in text_of(bcs, "desc")


def test_charts_are_in_figures_and_need_no_scrolling(client, user, filled):
    """The chart always fits the screen (wide or compact layout), so there is no scrolling
    region around it (it used to hide the newest measurements on a phone)."""
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()
    assert content.count('<figure class="chart">') == 2
    assert content.count("<figcaption") == 2
    for heading in ("weight-title", "bcs-title"):
        assert f'<h2 id="{heading}">' in content
    assert "chart__scroll" not in content
    assert 'role="region"' not in content.split("<figure", 1)[1].split("</figure>", 1)[0]


def test_every_chart_is_in_the_page_in_two_layouts_with_unique_ids(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()

    assert [s.get("class").split()[-1] for s in all_svgs(content)] == [
        "chart__svg--wide",
        "chart__svg--compact",
        "chart__svg--wide",
        "chart__svg--compact",
    ]
    ids = re.findall(r'\bid="([^"]+)"', content)
    assert len(ids) == len(set(ids)), "an id appears twice"
    assert {"weight-svg-title-compact", "bcs-svg-desc-compact"} <= set(ids)


def test_compact_layout_fits_a_phone(client, user, filled):
    """A 360 unit wide viewBox, drawn in full: every coordinate inside the viewBox, the value
    of the last point and the band label right-aligned in the margin, at most 3 date ticks."""
    client.force_login(user)
    weight, bcs = svgs(client.get(url_of(filled, "vse")).content.decode(), "compact")

    assert weight.get("viewBox") == "0 0 360 300" and bcs.get("viewBox") == "0 0 360 260"
    for svg in (weight, bcs):
        width = float(svg.get("viewBox").split()[2])
        for element in svg.iter():
            for name in ("x", "x1", "x2", "cx"):
                if element.get(name) is not None:
                    assert 0 <= float(element.get(name)) <= width, (element.tag, name)
            for vertex in (element.get("points") or "").split():
                assert 0 <= float(vertex.split(",")[0]) <= width
        ticks = [
            e
            for e in svg.iter("text")
            if e.get("class") == "chart__tick" and e.get("text-anchor") == "middle"
        ]
        assert 1 <= len(ticks) <= 3
    end = [e for e in weight.iter("text") if e.get("class") == "chart__label"]
    assert [e.get("text-anchor") for e in end] == ["end"]
    assert float(end[0].get("x")) <= 360
    band = [e.text for e in bcs.iter("text") if "chart__label--band" in e.get("class", "")]
    assert band == ["pásmo", "4–5 z 9"]  # two lines, the margin holds seven characters


def test_stylesheet_never_hides_a_chart_behind_a_scrollbar():
    css = (BASE_DIR / "static" / "css" / "app.css").read_text("utf-8")

    assert "chart__scroll" not in css
    block = re.search(r"\.chart__svg \{.*?\}", css, flags=re.DOTALL).group(0)
    assert "min-width" not in block
    assert re.search(r"\.chart__svg--wide \{\s*display: none;", css)
    assert re.search(
        r"@media \(min-width: 40rem\) \{\s*\.chart__svg--compact \{\s*display: none;", css
    )


def test_heading_order_is_h1_h2_h3(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()
    levels = [int(level) for level in re.findall(r"<h([1-6])\b", content)]
    assert levels[0] == 1 and levels.count(1) == 1
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False))


def test_svg_numbers_use_a_decimal_point_not_the_czech_comma(client, user, filled):
    """The page is Czech, Django would localise floats: coordinates must not be."""
    client.force_login(user)
    content = client.get(url_of(filled, "vse")).content.decode()
    number = re.compile(r"-?\d+(\.\d+)?")
    numeric = ("x", "y", "cx", "cy", "x1", "x2", "y1", "y2", "width", "height", "r", "dy")
    checked = 0
    for svg in svgs(content):
        for element in svg.iter():
            for name in numeric:
                value = element.get(name)
                if value is not None and not value.endswith("em"):
                    assert number.fullmatch(value), (element.tag, name, value)
                    checked += 1
            for vertex in (element.get("points") or "").split():
                assert re.fullmatch(r"-?\d+(\.\d+)?,-?\d+(\.\d+)?", vertex), vertex
            if element.get("viewBox"):
                assert re.fullmatch(r"0 0 \d+ \d+", element.get("viewBox"))
            if element.get("transform"):
                assert re.fullmatch(
                    r"translate\(\d+(\.\d+)? \d+(\.\d+)?\) rotate\(-90\)", element.get("transform")
                )
    assert checked > 50


def test_polyline_and_points_have_one_vertex_per_measurement(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled, "vse")).content.decode()
    weight, bcs = svgs(content)
    compact = svgs(content, "compact")[0]
    vertices = next(weight.iter("polyline")).get("points").split()
    assert len(vertices) == 4 == len(next(compact.iter("polyline")).get("points").split())
    marks = [e for e in weight.iter() if "chart__point" in (e.get("class") or "")]
    assert len(marks) == 4
    # BCS: 3 of the 4 measurements have a score; points only, no connecting line.
    assert len([e for e in bcs.iter() if "chart__point" in (e.get("class") or "")]) == 3
    assert not list(bcs.iter("polyline"))


def test_no_inline_style_and_no_script(client, user, filled):
    """The content security policy forbids both (style-src 'self', script-src 'self')."""
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()
    assert "style=" not in content
    assert "<script" not in content.lower()
    assert "http://" not in content and "https://" not in content


# --- Marker shapes: who recorded the measurement ----------------------------------------------


def test_circle_is_the_owner_and_diamond_the_vet(client, user, filled):
    client.force_login(user)
    weight, bcs = svgs(client.get(url_of(filled, "vse")).content.decode())
    circles = list(weight.iter("circle"))
    diamonds = list(weight.iter("polygon"))
    assert len(circles) == 3 and len(diamonds) == 1
    assert all(c.get("class") == "chart__point chart__point--owner" for c in circles)
    assert diamonds[0].get("class") == "chart__point chart__point--vet"
    assert len(diamonds[0].get("points").split()) == 4
    assert "posoudil: veterinární lékař" in text_of(diamonds[0], "title")
    assert all("posoudil: majitel" in text_of(c, "title") for c in circles)
    # The same shapes in the BCS chart (the vet's measurement has a score).
    assert len(list(bcs.iter("polygon"))) == 1 and len(list(bcs.iter("circle"))) == 2


def test_legend_names_the_shapes_in_words(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled, "vse")).content.decode()
    assert content.count("kolečko: měření zapsané majitelem") == 2
    assert content.count("kosočtverec: měření zapsané veterinárním lékařem") == 2
    assert "čárkovaná čára: cílová hmotnost (orientační)" in content
    assert "podklad: pásmo 4–5 z 9" in content


def test_legend_omits_shapes_that_are_not_drawn(client, user, animal, make_measurement):
    make_measurement(animal, measured_on=days_ago(9))
    make_measurement(animal, measured_on=days_ago(2))
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()
    assert "kolečko: měření zapsané majitelem" in content
    assert "kosočtverec" not in content


# --- Target weight ---------------------------------------------------------------------------


def test_unverified_target_is_labelled_orientacni(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()
    weight = svgs(content)[0]
    labels = [e.text for e in weight.iter("text") if "chart__label--target" in e.get("class", "")]
    assert labels == [f"cílová hmotnost (orientační) 19{NBSP}kg"]
    dashed = [e for e in weight.iter("line") if e.get("class") == "chart__target"]
    assert len(dashed) == 1
    assert "(potvrzeno veterinářem)" not in content
    assert f"Čárkovaná čára: cílová hmotnost (orientační) 19{NBSP}kg." in text_of(weight, "desc")


def test_confirmed_target_is_labelled_potvrzeno_veterinarem(client, user, vet_user, filled):
    AnimalShare.objects.create(animal=filled, vet=vet_user, granted_by=user)
    services.confirm_target_weight(filled, vet_user, Decimal("19"))
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()
    weight = svgs(content)[0]
    labels = [e.text for e in weight.iter("text") if "chart__label--target" in e.get("class", "")]
    assert labels == [f"cílová hmotnost (potvrzeno veterinářem) 19{NBSP}kg"]
    assert "čárkovaná čára: cílová hmotnost (potvrzeno veterinářem)" in content
    assert "(orientační)" not in content


def test_without_a_target_weight_there_is_no_line(client, user, make_animal, make_measurement):
    animal = make_animal(user, name="Bez cíle")
    make_measurement(animal, measured_on=days_ago(9))
    make_measurement(animal, measured_on=days_ago(2))
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()
    assert 'class="chart__target"' not in content and "cílová hmotnost" not in content


def test_target_is_never_called_ideal(client, user, vet_user, filled):
    AnimalShare.objects.create(animal=filled, vet=vet_user, granted_by=user)
    for status_confirmed in (False, True):
        if status_confirmed:
            services.confirm_target_weight(filled, vet_user, Decimal("19"))
        client.force_login(user)
        for period in ("30", "90", "365", "vse"):
            content = client.get(url_of(filled, period)).content.decode().lower()
            assert "ideál" not in content and "ideal" not in content


def test_target_far_outside_the_data_is_still_drawn(client, user, make_animal, make_measurement):
    animal = make_animal(user, target_weight_kg=Decimal("12"))
    make_measurement(animal, measured_on=days_ago(9), weight_kg=Decimal("25"))
    make_measurement(animal, measured_on=days_ago(2), weight_kg=Decimal("26"))
    client.force_login(user)
    weight = svgs(client.get(url_of(animal)).content.decode())[0]
    ticks = [
        float(e.text.replace(",", "."))
        for e in weight.iter("text")
        if e.get("class") == "chart__tick" and e.get("text-anchor") == "end"
    ]
    assert min(ticks) <= 12 and max(ticks) >= 26
    assert len([e for e in weight.iter("line") if e.get("class") == "chart__target"]) == 1


# --- BCS chart ---------------------------------------------------------------------------------


def test_bcs_chart_has_the_labelled_band_and_the_whole_scale(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled, "vse")).content.decode()
    bcs = svgs(content)[1]
    band_labels = [e.text for e in bcs.iter("text") if "chart__label--band" in e.get("class", "")]
    assert band_labels == ["pásmo 4–5 z 9"]
    assert len([e for e in bcs.iter("rect") if e.get("class") == "chart__band"]) == 1
    scale = [
        e.text
        for e in bcs.iter("text")
        if e.get("class") == "chart__tick" and e.get("text-anchor") == "end"
    ]
    assert scale == [str(n) for n in range(1, 10)]
    assert (
        "Pásmo 4–5 z 9 vyznačuje střed devítibodové škály. Je jen vodítko na škále, ne hodnocení "
        "zdraví zvířete ani doporučený rozsah."
    ) in flat(content)
    assert "ideál" not in content.lower()
    assert "healthy" not in content.lower()


# --- Data table: the accessible alternative ------------------------------------------------------


def test_table_has_every_column_and_every_value(client, user, make_animal, make_measurement):
    animal = make_animal(user, name="Tabulka")
    make_measurement(
        animal,
        measured_on=days_ago(8),
        weight_kg=Decimal("12.50"),
        bcs=6,
        mcs=MuscleCondition.MILD_LOSS,
        note='po "nemoci"\nbez chuti',
    )
    make_measurement(animal, measured_on=days_ago(1), weight_kg=Decimal("12"))
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()

    for column in (
        "Datum",
        "Hmotnost",
        "BCS (tělesná kondice)",
        "Svalová kondice (MCS)",
        "Posoudil",
        "Poznámka",
    ):
        assert f'<th scope="col">{column}</th>' in content
    assert '<caption class="visually-hidden">' in content
    assert f'<td class="date">{services.short_date(days_ago(8))}</td>' in content
    assert f'<td class="num">12,5{NBSP}kg</td>' in content
    assert "<td>6/9</td>" in content
    assert "<td>mírná ztráta svalové hmoty</td>" in content
    assert "po &quot;nemoci&quot;<br>bez chuti" in content
    assert "<td>majitel</td>" in content
    assert content.count("nezadáno") == 2  # BCS and MCS of the newer measurement
    # Newest first, like the table on the detail page.
    rows = re.findall(r'<tr>\s*<td class="date">(\d+\. \d+\. \d+)</td>', content)
    assert rows == [services.short_date(days_ago(1)), services.short_date(days_ago(8))]


def test_table_is_present_in_every_state(client, user, animal, make_measurement):
    client.force_login(user)
    for period in ("30", "vse"):
        content = client.get(url_of(animal, period)).content.decode()
        assert '<table class="data">' in content
        assert "V zobrazeném období není zapsané žádné měření." in content
    make_measurement(animal, measured_on=days_ago(100))
    content = client.get(url_of(animal, "30")).content.decode()
    assert '<table class="data">' in content
    assert "Mimo zobrazené období je další 1 měření" in content


def test_vet_email_in_the_table_follows_data_minimisation(
    client, user, vet_user, make_user, make_animal, make_measurement
):
    other_vet = make_user("other-vet@example.cz", roles=(Role.VET,))
    animal = make_animal(user)
    for vet in (vet_user, other_vet):
        AnimalShare.objects.create(animal=animal, vet=vet, granted_by=user)
    make_measurement(animal, measured_on=days_ago(3), assessed_by=Assessor.VET, created_by=vet_user)
    make_measurement(animal, measured_on=days_ago(1))

    def cell(viewer) -> str:
        client.force_login(viewer)
        return client.get(url_of(animal)).content.decode()

    assert "veterinární lékař (vet@example.cz)" in cell(user)  # the owner
    assert "veterinární lékař (vet@example.cz)" in cell(vet_user)  # the author
    other = cell(other_vet)
    assert "<td>veterinární lékař</td>" in other and "vet@example.cz" not in other


# --- Empty states ---------------------------------------------------------------------------


def add_link(animal) -> str:
    return f'href="{reverse("animals:measurement_add", args=[animal.uuid])}"'


def test_no_measurement_at_all(client, user, animal):
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()
    assert not all_svgs(content)
    text = flat(content)
    assert "Zatím není zapsané žádné měření." in text
    assert "Graf hmotnosti se zobrazí, jakmile budou zapsaná alespoň dvě měření." in text
    assert "není zapsané žádné hodnocení BCS" in text
    assert content.count(add_link(animal)) >= 3  # both empty states and the bottom button


def test_one_measurement_in_the_period(client, user, animal, make_measurement):
    make_measurement(animal, measured_on=days_ago(4), weight_kg=Decimal("20.5"), bcs=5)
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()
    assert not all_svgs(content)
    text = flat(content)
    day = services.short_date(days_ago(4))
    assert f"je jen jedno měření: 20,5{NBSP}kg dne {day}." in text
    assert f"je jen jedno hodnocení BCS: 5/9 dne {day}." in text
    assert "Graf potřebuje alespoň dvě měření." in text
    assert add_link(animal) in content


def test_measurements_only_outside_the_period(client, user, animal, make_measurement):
    make_measurement(animal, measured_on=days_ago(200))
    make_measurement(animal, measured_on=days_ago(180))
    client.force_login(user)
    content = client.get(url_of(animal, "30")).content.decode()
    assert not all_svgs(content)
    assert "není zapsané žádné měření. Zvolte delší období nebo zapište nové měření." in flat(
        content
    )
    # No scores: only the weight chart, in both layouts.
    assert len(all_svgs(client.get(url_of(animal, "vse")).content.decode())) == 2


def test_weight_chart_without_scores_leaves_only_the_bcs_empty_state(
    client, user, animal, make_measurement
):
    make_measurement(animal, measured_on=days_ago(9))
    make_measurement(animal, measured_on=days_ago(2))
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()
    charts_found = all_svgs(content)
    assert len(charts_found) == 2  # the weight chart in two layouts
    assert all(c.get("aria-labelledby").startswith("weight") for c in charts_found)
    assert "není zapsané žádné hodnocení BCS" in flat(content)


def test_bcs_chart_appears_with_two_scores(client, user, animal, make_measurement):
    make_measurement(animal, measured_on=days_ago(9), bcs=5)
    make_measurement(animal, measured_on=days_ago(2), bcs=6)
    client.force_login(user)
    assert len(svgs(client.get(url_of(animal)).content.decode())) == 2  # weight and BCS


def test_shared_vet_gets_the_add_measurement_link_too(client, user, vet_user, animal):
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    client.force_login(vet_user)
    assert add_link(animal) in client.get(url_of(animal)).content.decode()


# --- XSS ----------------------------------------------------------------------------------------

EVIL = "<script>alert(1)</script>\"'&"


def test_animal_name_is_escaped_everywhere_including_the_svg_title(
    client, user, make_animal, make_measurement
):
    animal = make_animal(user, name=EVIL)
    make_measurement(
        animal, measured_on=days_ago(9), note="<img src=x onerror=alert(2)>", bcs=5, weight_kg=21
    )
    make_measurement(animal, measured_on=days_ago(2), bcs=6)
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()

    assert "<script" not in content and "<img" not in content
    assert "onerror=alert" not in content.replace("&lt;img src=x onerror=alert(2)&gt;", "")
    escaped = "&lt;script&gt;alert(1)&lt;/script&gt;&quot;&#x27;&amp;"
    assert content.count(escaped) >= 5  # title tag, breadcrumb, lead and the SVG titles
    weight, bcs = svgs(content)  # the SVGs are still well-formed XML
    assert text_of(weight, "title") == f"Graf hmotnosti zvířete {EVIL} za posledních 90 dní"
    assert text_of(bcs, "title") == f"Graf BCS zvířete {EVIL} za posledních 90 dní"
    assert EVIL not in text_of(weight, "desc")  # the description never carries the name
    assert "&lt;img src=x onerror=alert(2)&gt;" in content  # the note in the table


def test_query_string_is_not_reflected(client, user, filled):
    client.force_login(user)
    content = client.get(
        url_of(filled) + "?obdobi=%3Cscript%3Ealert(1)%3C/script%3E"
    ).content.decode()
    assert "alert(1)" not in content


# --- Descriptive only ----------------------------------------------------------------------------


def test_page_does_not_judge_or_advise(client, user, filled):
    client.force_login(user)
    for period in ("30", "90", "365", "vse"):
        content = client.get(url_of(filled, period)).content.decode().lower()
        for word in ("ideál", "rychlý úbytek", "doporučujeme", "měli byste", "nebezpeč", "kcal"):
            assert word not in content, word
        assert "posoudí veterinární lékař" in content


def test_change_sentence_of_the_task_is_on_the_page(client, user, make_animal, make_measurement):
    animal = make_animal(user)
    make_measurement(animal, measured_on=days_ago(30), weight_kg=Decimal("31.5"))
    make_measurement(animal, measured_on=days_ago(0), weight_kg=Decimal("30.3"))
    client.force_login(user)
    content = client.get(url_of(animal)).content.decode()
    assert (
        f"Změna hmotnosti za zvolené období: \N{MINUS SIGN}1,2{NBSP}kg "
        f"(\N{MINUS SIGN}3,8{NBSP}%). Zda je změna žádoucí, posoudí veterinární lékař."
    ) in content
    assert f"<dt>První hmotnost</dt><dd>31,5{NBSP}kg" in content
    assert "<dt>Počet měření</dt><dd>2</dd>" in content
    assert "<dt>Rozpětí v dnech</dt><dd>30</dd>" in content


# --- Navigation ----------------------------------------------------------------------------------


def test_breadcrumbs_lead_back_to_the_animal_and_the_overview(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()
    assert f'<a href="{reverse("core:dashboard")}">Přehled</a>' in content
    assert f'<a href="{filled.get_absolute_url()}">Rex</a>' in content
    assert '<span aria-current="page">Sledování hmotnosti a kondice</span>' in content
    assert "Zpět na profil zvířete" in content


def test_detail_page_links_to_the_tracking_page(client, user, vet_user, filled):
    AnimalShare.objects.create(animal=filled, vet=vet_user, granted_by=user)
    for viewer in (user, vet_user):
        client.force_login(viewer)
        content = client.get(filled.get_absolute_url()).content.decode()
        # One link, not two controls with different words for the same page.
        assert content.count(f'href="{url_of(filled)}"') == 1
        assert ">Sledování hmotnosti a kondice</a>" in content
        assert "Graf hmotnosti a kondice" not in content and "Zobrazit grafy" not in content


def test_detail_table_still_shows_the_assessor_with_the_same_rules(
    client, user, vet_user, filled, make_measurement
):
    make_measurement(filled, measured_on=days_ago(1), assessed_by=Assessor.VET, created_by=vet_user)
    client.force_login(user)
    content = client.get(filled.get_absolute_url()).content.decode()
    assert "<td>veterinární lékař (vet@example.cz)</td>" in content
    assert "<td>majitel</td>" in content


# --- Wording guard on the sources ----------------------------------------------------------------

FORBIDDEN_WORDS = ("ideál", "zdravá", "zdravé", "zdravý", "doporučujeme", "rychlý úbytek")


def test_chart_texts_and_templates_never_use_judging_words():
    """Czech texts of the chart module and its templates only describe (docs/12 §12.11)."""
    texts = [
        node.value
        for node in ast.walk(ast.parse((BASE_DIR / "animals" / "charts.py").read_text("utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    templates = [
        BASE_DIR / "templates" / "animals" / name
        for name in (
            "tracking.html",
            "includes/weight_chart.html",
            "includes/weight_svg.html",
            "includes/bcs_chart.html",
            "includes/bcs_svg.html",
            "includes/chart_legend.html",
            "includes/sparkline.html",
        )
    ]
    texts += [path.read_text("utf-8") for path in templates]
    for text in texts:
        for word in FORBIDDEN_WORDS:
            assert word not in text.lower(), (word, text[:60])


# --- Number of queries ---------------------------------------------------------------------------


def count_queries(client, url: str) -> int:
    with CaptureQueriesContext(connection) as queries:
        assert client.get(url).status_code == 200
    return len(queries)


def test_tracking_page_queries_do_not_depend_on_the_number_of_measurements(
    client, user, vet_user, make_animal, make_measurement
):
    """The table shows the e-mail of a vet who wrote a measurement (created_by): without
    select_related that is one query per row. Nothing but this test noticed it missing."""
    animal = make_animal(user, name="Mnoho")
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    client.force_login(user)

    def add(count: int, offset: int) -> None:
        for index in range(count):
            make_measurement(
                animal,
                measured_on=days_ago(offset + index),
                assessed_by=Assessor.VET,
                created_by=vet_user,
                bcs=5,
            )

    add(1, 1)
    few = count_queries(client, url_of(animal, "vse"))
    add(20, 2)
    many = count_queries(client, url_of(animal, "vse"))

    assert few == many
    assert many <= 5  # session, user, animal, measurements (+ the share check)
    page = client.get(url_of(animal, "vse")).content.decode()
    assert page.count("veterinární lékař (vet@example.cz)") == 21  # the e-mail is in every row


# --- Czech counted noun ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("older", "sentence"),
    [
        (1, "Mimo zobrazené období je další 1 měření"),
        (2, "Mimo zobrazené období jsou další 2 měření"),
        (3, "Mimo zobrazené období jsou další 3 měření"),
        (5, "Mimo zobrazené období je dalších 5 měření"),
    ],
)
def test_outside_period_sentence_has_the_right_grammar(
    client, user, make_animal, make_measurement, older, sentence
):
    animal = make_animal(user)
    for index in range(older):
        make_measurement(animal, measured_on=days_ago(100 + index))
    make_measurement(animal, measured_on=days_ago(5))
    client.force_login(user)

    content = flat(client.get(url_of(animal, "30")).content.decode())

    assert f"{sentence}: <a href=" in content
    assert "dalších 1 měření" not in content and "dalších 3 měření" not in content


# --- Narrow screens: table hint, dates, no hidden overflow -------------------------------------


def test_table_names_its_scroll_region_and_hints_that_it_scrolls(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()

    assert 'role="region" aria-label="Tabulka měření, posuvná oblast" tabindex="0"' in content
    # The section is named "Tabulka měření"; the region inside must not carry the same name.
    assert 'role="region" aria-labelledby=' not in content
    assert (
        '<p class="hint table-hint">Tabulku lze na úzké obrazovce posouvat do stran.</p>' in content
    )
    assert content.count('<td class="date">') == 2  # the 90 days; dates stay on one line


def test_stylesheet_keeps_the_hint_and_the_dates_for_narrow_screens():
    css = (BASE_DIR / "static" / "css" / "app.css").read_text("utf-8")

    assert re.search(r"\.table-hint \{\s*display: none;", css)
    assert re.search(r"@media \(max-width: 40rem\) \{\s*\.table-hint \{\s*display: block;", css)
    assert re.search(r"table\.data td\.date \{\s*white-space: nowrap;", css)


def test_table_wrapper_contains_the_visually_hidden_texts_of_its_cells():
    """The owner's "Smazat" column has visually hidden spans (position: absolute). Without a
    positioned wrapper their containing block is the page, overflow-x of the wrapper does not
    clip them and the whole page grew 285 px wider than a 390 px phone."""
    css = (BASE_DIR / "static" / "css" / "app.css").read_text("utf-8")

    block = re.search(r"\.table-wrap \{.*?\}", css, flags=re.DOTALL).group(0)
    assert "position: relative" in block and "overflow-x: auto" in block
    assert re.search(r"\.visually-hidden \{\s*position: absolute;", css)


def test_charts_say_the_line_joins_recorded_measurements_only(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled, "vse")).content.decode()

    assert (
        '<p class="hint">Čára spojuje zapsaná měření; mezi nimi nejsou zapsaná žádná data.</p>'
        in content
    )
    assert "Čára spojuje zapsaná měření" in text_of(svgs(content)[0], "desc")


def test_the_page_uses_one_name_for_the_tracking_screen(client, user, filled):
    client.force_login(user)
    content = client.get(url_of(filled)).content.decode()

    assert "<title>Sledování hmotnosti a kondice: Rex" in content
    assert "<h1>Sledování hmotnosti a kondice</h1>" in content
    assert '<span aria-current="page">Sledování hmotnosti a kondice</span>' in content
