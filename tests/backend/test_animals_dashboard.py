"""Dashboard (docs/08 §8.3): own animals and, for vets, the section "Sdílená zvířata"."""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from animals import services
from animals.models import AnimalHealthCondition, AnimalShare, HealthCondition, Species
from animals.services import short_date

pytestmark = pytest.mark.django_db

DASHBOARD = reverse("core:dashboard")


def test_signed_in_user_reaches_dashboard_from_root(logged_in_client):
    response = logged_in_client.get("/", follow=True)
    assert response.redirect_chain == [(DASHBOARD, 302)]
    assert "<h1>Přehled</h1>" in response.content.decode()


def test_empty_dashboard(logged_in_client):
    content = logged_in_client.get(DASHBOARD).content.decode()
    assert "Moje zvířata" in content
    assert "Zatím jste nepřidali žádné zvíře." in content
    assert reverse("animals:create") in content
    assert "Sdílená zvířata" not in content  # not a vet


def test_cards_of_own_animals(logged_in_client, user, make_user, make_animal, make_measurement):
    today = timezone.localdate()
    # Dates relative to today: the dashboard computes the age from the real date.
    rex = make_animal(user, birth_date=today - timedelta(days=5 * 365 + 60))  # 5 years, 2 months
    older, newer = today - timedelta(days=50), today - timedelta(days=17)
    make_measurement(rex, measured_on=older, weight_kg=Decimal("21.4"), bcs=6)
    make_measurement(rex, measured_on=newer, weight_kg=Decimal("21"))
    micka = make_animal(user, name="Micka", species=Species.CAT)
    AnimalHealthCondition.objects.create(
        animal=micka, condition=HealthCondition.objects.get(code="CKD")
    )
    make_animal(make_user("other@example.cz"), name="Cizák")

    content = logged_in_client.get(DASHBOARD).content.decode()

    assert rex.get_absolute_url() in content and micka.get_absolute_url() in content
    assert "Cizák" not in content
    assert "pes" in content and "kočka" in content
    assert "5 let" in content  # age of Rex
    assert f"21\xa0kg ({short_date(newer)})" in content  # latest weight with its date
    assert f"6/9 ({short_date(older)})" in content  # latest BCS with its date
    assert "Vyžaduje odborné posouzení" in content  # Rex: BCS 6
    assert "Automatický výpočet nelze doporučit" in content  # Micka: CKD
    assert "nezadáno" in content  # Micka has no measurement
    assert "Majitel" not in content


def test_vet_sees_shared_animals(client, make_user, make_animal, vet_user):
    owner = make_user("owner@example.cz")
    shared = make_animal(owner, name="Sdílený")
    revoked = make_animal(owner, name="Odvolaný")
    make_animal(owner, name="Nesdílený")
    AnimalShare.objects.create(animal=shared, vet=vet_user, granted_by=owner)
    AnimalShare.objects.create(
        animal=revoked, vet=vet_user, granted_by=owner, revoked_at=timezone.now()
    )
    make_animal(vet_user, name="Vlastní pes veterináře")
    client.force_login(vet_user)

    content = client.get(DASHBOARD).content.decode()

    # A vet's dashboard starts with the animals shared with them.
    assert content.index("Sdílená zvířata") < content.index("Moje zvířata")
    shared_part, own_part = content.split("Moje zvířata", 1)
    assert "Vlastní pes veterináře" in own_part
    assert "Sdílený" in shared_part and "owner@example.cz" in shared_part
    assert "Odvolaný" not in content and "Nesdílený" not in content


def test_vet_without_shares(client, vet_user):
    client.force_login(vet_user)
    content = client.get(DASHBOARD).content.decode()
    assert "Zatím s vámi žádný majitel nesdílí zvíře." in content
    assert vet_user.email in content


def test_shares_to_a_user_without_vet_role_are_not_shown(client, make_user, make_animal):
    owner = make_user("owner@example.cz")
    former_vet = make_user("former@example.cz", roles=(Role.OWNER,))
    AnimalShare.objects.create(animal=make_animal(owner), vet=former_vet, granted_by=owner)
    client.force_login(former_vet)
    content = client.get(DASHBOARD).content.decode()
    assert "Sdílená zvířata" not in content and "Rex" not in content


def test_greeting_does_not_decline_the_name(client, make_user):
    """Czech address needs the vocative; the page shows the account instead of a greeting."""
    jana = make_user("jana.novakova@example.cz", first_name="Jana", last_name="Nováková")
    client.force_login(jana)
    content = client.get(DASHBOARD).content.decode()
    assert "Dobrý den, Jana" not in content
    assert "Přihlášený účet: Jana Nováková (jana.novakova@example.cz)." in content


def test_dashboard_is_not_cached(logged_in_client):
    cache_control = logged_in_client.get(DASHBOARD)["Cache-Control"]
    assert "no-store" in cache_control and "private" in cache_control


@pytest.fixture
def dashboard_queries(client, make_user, make_animal, make_measurement):
    """Return ``count(role, n)``: queries of one dashboard request with ``n`` cards."""

    def count(role: str, n: int) -> int:
        viewer = make_user(f"{role}{n}@example.cz", roles=(Role.VET,) if role == "vet" else ())
        owner = make_user(f"owner-of-{role}{n}@example.cz") if role == "vet" else viewer
        for index in range(n):
            animal = make_animal(owner, name=f"Zvíře {index}")
            make_measurement(animal, bcs=5)
            AnimalHealthCondition.objects.create(
                animal=animal, condition=HealthCondition.objects.get(code="FOOD_ALLERGY")
            )
            if role == "vet":
                AnimalShare.objects.create(animal=animal, vet=viewer, granted_by=owner)
        client.force_login(viewer)
        with CaptureQueriesContext(connection) as queries:
            response = client.get(DASHBOARD)
        assert response.status_code == 200
        assert response.content.decode().count('class="card"') == n
        return len(queries)

    return count


@pytest.mark.parametrize("role", ["owner", "vet"])
def test_dashboard_query_count_does_not_grow_with_animals(dashboard_queries, role):
    """Owner cards and the vet's "Sdílená zvířata" cards (with the owner's e-mail)."""
    assert dashboard_queries(role, 1) == dashboard_queries(role, 8)


# --- Weight sparkline and link to the tracking page (docs/08 §8.3) --------------------------------

NBSP = "\xa0"


def sparkline_svgs(content: str) -> list[str]:
    return re.findall(r'<svg class="sparkline__svg".*?</svg>', content, flags=re.DOTALL)


def test_card_shows_a_hidden_sparkline_with_a_text_alternative(
    logged_in_client, user, make_animal, make_measurement
):
    today = timezone.localdate()
    rex = make_animal(user)
    make_measurement(rex, measured_on=today - timedelta(days=33), weight_kg=Decimal("21.4"))
    make_measurement(rex, measured_on=today - timedelta(days=10), weight_kg=Decimal("21.1"))
    make_measurement(rex, measured_on=today - timedelta(days=1), weight_kg=Decimal("21"))

    content = logged_in_client.get(DASHBOARD).content.decode()

    (svg,) = sparkline_svgs(content)
    assert 'aria-hidden="true"' in svg and 'focusable="false"' in svg
    assert "<title" not in svg and "<desc" not in svg and "role=" not in svg
    assert re.search(r'<polyline class="sparkline__line" points="[\d. ,-]+"', svg)
    assert "," not in re.search(r'cx="([^"]*)"', svg).group(1)  # decimal point, not comma
    text = f"poslední hmotnost 21{NBSP}kg, změna \N{MINUS SIGN}0,4{NBSP}kg za 32 dní"
    assert f'<span class="sparkline__text">Vývoj: {text}.</span>' in content


def test_card_without_two_measurements_has_no_sparkline(
    logged_in_client, user, make_animal, make_measurement
):
    make_measurement(make_animal(user, name="Jedno"))
    make_animal(user, name="Žádné")
    content = logged_in_client.get(DASHBOARD).content.decode()
    assert "sparkline" not in content
    assert "poslední hmotnost" not in content.replace("Poslední hmotnost", "")


def test_sparkline_uses_only_the_newest_measurements(
    logged_in_client, user, make_animal, make_measurement
):
    today = timezone.localdate()
    animal = make_animal(user)
    make_measurement(animal, measured_on=today - timedelta(days=300), weight_kg=Decimal("30"))
    for index in range(services.SPARKLINE_MEASUREMENTS):  # the newest twelve, one per day
        make_measurement(
            animal, measured_on=today - timedelta(days=11 - index), weight_kg=Decimal(index + 20)
        )
    content = logged_in_client.get(DASHBOARD).content.decode()
    assert f"změna +11{NBSP}kg za 11 dní" in content  # 20 → 31 kg; the old 30 kg is not used
    (svg,) = sparkline_svgs(content)
    assert len(re.search(r'points="([^"]*)"', svg).group(1).split()) == 12


def test_card_links_to_the_tracking_page(logged_in_client, user, make_animal):
    rex = make_animal(user)
    content = logged_in_client.get(DASHBOARD).content.decode()
    link = reverse("animals:tracking", args=[rex.uuid])
    assert (
        f'<a href="{link}">Sledování hmotnosti a kondice<span class="visually-hidden"> – Rex</span>'
        "</a>" in content
    )


def test_vet_sees_the_sparkline_on_shared_cards(
    client, make_user, make_animal, make_measurement, vet_user
):
    owner = make_user("owner@example.cz")
    animal = make_animal(owner, name="Sdílený")
    make_measurement(animal, measured_on=timezone.localdate() - timedelta(days=5))
    make_measurement(animal, measured_on=timezone.localdate() - timedelta(days=1))
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=owner)
    client.force_login(vet_user)
    assert len(sparkline_svgs(client.get(DASHBOARD).content.decode())) == 1


def test_dashboard_with_sparklines_runs_a_constant_number_of_queries(
    client, make_user, make_animal, make_measurement, django_assert_max_num_queries
):
    """Cards with sparklines (several measurements each) add no query per animal."""
    today = timezone.localdate()
    user = make_user("many@example.cz")

    def add_animals(count: int, offset: int) -> None:
        for index in range(count):
            animal = make_animal(user, name=f"Zvíře {offset + index}")
            for days in (30, 20, 10, 1):
                make_measurement(animal, measured_on=today - timedelta(days=days), bcs=5)
            AnimalHealthCondition.objects.create(
                animal=animal, condition=HealthCondition.objects.get(code="FOOD_ALLERGY")
            )

    client.force_login(user)
    add_animals(1, 0)
    with CaptureQueriesContext(connection) as baseline:
        assert client.get(DASHBOARD).status_code == 200
    add_animals(9, 1)

    with django_assert_max_num_queries(len(baseline)):
        response = client.get(DASHBOARD)
    content = response.content.decode()
    assert content.count('class="card"') == 10
    assert len(sparkline_svgs(content)) == 10


# --- The rows read do not grow with the history ------------------------------------------------


def test_dashboard_loads_only_the_newest_measurements_of_each_animal(
    user, make_animal, make_measurement
):
    """It used to prefetch every measurement of every animal and slice twelve of them in
    Python; the work grew with the lifetime history of all animals."""
    today = timezone.localdate()
    animals = [make_animal(user, name=f"Zvíře {number}") for number in range(3)]
    for animal in animals:
        for days in range(60, 0, -1):
            make_measurement(animal, measured_on=today - timedelta(days=days), bcs=5)

    with CaptureQueriesContext(connection) as queries:
        summaries = services.summarize(services.owned_animals(user))

    assert len(summaries) == 3
    for summary in summaries:
        newest = summary.animal.newest_measurements
        assert len(newest) == services.SPARKLINE_MEASUREMENTS == 12
        assert [m.measured_on for m in newest] == sorted(
            (m.measured_on for m in newest), reverse=True
        )
        assert summary.latest_weight.measured_on == today - timedelta(days=1)
        assert len(summary.animal.latest_bcs_rows) == 1
        assert summary.trend is not None and summary.trend.days == 11
    # Five queries (animals, three kinds of measurements, conditions), whatever the history.
    assert len(queries) == 5
    assert sum(1 for q in queries if "ROW_NUMBER()" in q["sql"]) == 3


def test_latest_scores_come_from_old_rows_outside_the_newest_twelve(
    user, make_animal, make_measurement
):
    """The attention level needs the latest BCS and MCS however long ago they were written:
    a score from 40 measurements ago must still count (BCS 7 = overweight)."""
    today = timezone.localdate()
    animal = make_animal(user)
    make_measurement(animal, measured_on=today - timedelta(days=100), bcs=7, mcs="MILD_LOSS")
    for days in range(60, 0, -1):
        make_measurement(animal, measured_on=today - timedelta(days=days))  # no BCS, no MCS

    (summary,) = services.summarize(services.owned_animals(user))

    assert summary.latest_bcs.bcs == 7 and summary.latest_bcs.measured_on == today - timedelta(
        days=100
    )
    assert summary.attention.level == services.EXPERT_REQUIRED
    texts = " ".join(reason.text for reason in summary.attention.reasons)
    assert "Poslední zadané BCS je 7/9" in texts
    assert "ztráta svalové hmoty" in texts
    assert summary.latest_weight.measured_on == today - timedelta(days=1)


def test_summary_is_the_same_with_and_without_the_prefetch(user, make_animal, make_measurement):
    """The detail page asks for the attention level of one animal without the prefetch (all
    measurements are read); the dashboard reads the prefetched rows. Same answer."""
    today = timezone.localdate()
    animal = make_animal(user)
    for days, bcs in [(90, 3), (50, None), (20, 6), (10, None), (3, None)]:
        make_measurement(animal, measured_on=today - timedelta(days=days), bcs=bcs)
    make_measurement(animal, measured_on=today - timedelta(days=3), bcs=None)  # same day: a tie

    (prefetched,) = services.summarize(services.owned_animals(user))
    plain = services.summarize([type(animal).objects.get(pk=animal.pk)])[0]

    assert prefetched.attention == plain.attention
    assert (
        prefetched.latest_bcs == plain.latest_bcs
        and prefetched.latest_weight == plain.latest_weight
    )
    assert prefetched.trend == plain.trend
    assert prefetched.latest_bcs.bcs == 6


def test_the_newest_measurement_of_a_day_wins_a_tie_like_the_model_ordering(
    user, make_animal, make_measurement
):
    today = timezone.localdate()
    animal = make_animal(user)
    first = make_measurement(animal, measured_on=today - timedelta(days=2), weight_kg=Decimal("20"))
    second = make_measurement(
        animal, measured_on=today - timedelta(days=2), weight_kg=Decimal("21")
    )

    (summary,) = services.summarize(services.owned_animals(user))

    assert summary.latest_weight == second != first
    assert [m.pk for m in summary.animal.newest_measurements] == [second.pk, first.pk]
