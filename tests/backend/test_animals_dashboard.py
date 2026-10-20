"""Dashboard (docs/08 §8.3): own animals and, for vets, the section "Sdílená zvířata"."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from animals.models import AnimalHealthCondition, AnimalShare, HealthCondition, Species

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
    rex = make_animal(user, birth_date=date(2021, 1, 1))
    make_measurement(rex, measured_on=date(2026, 9, 1), weight_kg=Decimal("21.4"), bcs=6)
    make_measurement(rex, measured_on=date(2026, 10, 3), weight_kg=Decimal("21"))
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
    assert "21\xa0kg (3. 10. 2026)" in content  # latest weight with its date
    assert "6/9 (1. 9. 2026)" in content  # latest BCS with its date
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

    assert "Sdílená zvířata" in content
    own_part, shared_part = content.split("Sdílená zvířata", 1)
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


def test_dashboard_query_count_does_not_grow_with_animals(
    logged_in_client, user, make_animal, make_measurement, django_assert_max_num_queries
):
    for index in range(6):
        animal = make_animal(user, name=f"Zvíře {index}")
        make_measurement(animal, bcs=5)
    with django_assert_max_num_queries(12):
        assert logged_in_client.get(DASHBOARD).status_code == 200
