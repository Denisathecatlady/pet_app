"""Views of the animals app: create, detail, edit, delete, measurements, conditions,
sharing with a vet and target weight confirmation (behaviour and content)."""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from animals.models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    Assessor,
    BodyMeasurement,
    HealthCondition,
    TargetWeightStatus,
)
from animals.services import NOT_A_VET_MESSAGE

pytestmark = pytest.mark.django_db

ANIMAL_DATA = {
    "name": "Bára",
    "species": "DOG",
    "sex": "FEMALE",
    "neutered": "on",
    "birth_date": "2020-03-01",
    "breed": "kříženec",
    "size_category": "MEDIUM",
    "physiological_state": "MAINTENANCE",
    "activity_level": "MODERATE_HIGH_IMPACT",
    "expected_adult_weight_kg": "",
    "target_weight_kg": "18,5",
    "current_feeding": "granule",
    "allergies": "Kuřecí, kuřecí ,  Hovězí maso",
    "notes": "",
}


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def detail_url(animal):
    return reverse("animals:detail", args=[animal.uuid])


@pytest.fixture
def owner_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def vet_client(client, vet_user):
    client.force_login(vet_user)
    return client


@pytest.fixture
def shared(user, make_animal, vet_user):
    animal = make_animal(user, target_weight_kg=Decimal("18.5"))
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    return animal


# --- Create, edit, delete ---------------------------------------------------------------------


def test_create_animal(owner_client, user):
    response = owner_client.post(reverse("animals:create"), ANIMAL_DATA)

    animal = Animal.objects.get()
    assert response.status_code == 302
    assert response["Location"] == detail_url(animal)
    assert animal.owner == user
    assert animal.target_weight_kg == Decimal("18.5")
    assert animal.allergies == ["kuřecí", "hovězí maso"]
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert "Zvíře Bára bylo přidáno." in messages_of(response)
    history = animal.history.get()
    assert history.history_type == "+" and history.history_user == user


def test_create_form_shows_czech_errors(owner_client):
    data = {**ANIMAL_DATA, "species": "CAT", "sex": "MALE", "physiological_state": "LACTATION"}
    data["target_weight_kg"] = "40"
    data["birth_date"] = (timezone.localdate() + timedelta(days=2)).isoformat()

    response = owner_client.post(reverse("animals:create"), data)

    content = response.content.decode()
    assert response.status_code == 200
    assert "Formulář obsahuje chyby." in content
    assert "Velikostní kategorie se zadává jen u psů." in content
    assert "Březost a laktaci lze zadat jen u samice." in content
    assert "Datum narození nemůže být v budoucnosti." in content
    assert "Hmotnost kočky zadejte v kilogramech v rozmezí 0,5–15 kg." in content
    assert not Animal.objects.exists()


def test_create_form_has_accessible_fields(owner_client):
    content = owner_client.get(reverse("animals:create")).content.decode()
    assert '<label for="id_name" class="required">' in content
    assert 'type="date"' in content
    assert 'inputmode="decimal"' in content
    for label in ("Nízká –", "Střední –", "Střední s vysokou zátěží", "Vysoká –"):
        assert label in content
    assert "kcal" not in content.lower()


def test_edit_animal_records_history(owner_client, user, make_animal):
    animal = make_animal(user)
    data = {**ANIMAL_DATA, "name": "Rexík", "sex": "MALE"}

    response = owner_client.post(reverse("animals:edit", args=[animal.uuid]), data)

    assert response.status_code == 302
    animal.refresh_from_db()
    assert animal.name == "Rexík"
    latest = animal.history.latest("history_date")
    assert latest.history_type == "~" and latest.history_user == user


def test_edit_form_shows_allergies_as_text(owner_client, user, make_animal):
    animal = make_animal(user, allergies=["kuřecí", "ryby"])
    content = owner_client.get(reverse("animals:edit", args=[animal.uuid])).content.decode()
    assert 'value="kuřecí, ryby"' in content


def test_delete_confirmation_page_and_delete(owner_client, user, make_animal, make_measurement):
    animal = make_animal(user)
    make_measurement(animal)
    url = reverse("animals:delete", args=[animal.uuid])

    page = owner_client.get(url).content.decode()
    assert "Smazat zvíře Rex?" in page and "1 měření" in page and "nevratné" in page
    assert Animal.objects.filter(pk=animal.pk).exists()

    response = owner_client.post(url)
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")
    assert not Animal.objects.exists()
    assert not BodyMeasurement.objects.exists()


# --- Target weight ----------------------------------------------------------------------------


def confirm(client, animal, value="18.5"):
    return client.post(
        reverse("animals:target_weight_confirm", args=[animal.uuid]), {"target_weight_kg": value}
    )


def test_vet_confirms_target_weight(vet_client, vet_user, shared):
    response = confirm(vet_client, shared)

    shared.refresh_from_db()
    assert response.status_code == 302
    assert shared.target_weight_status == TargetWeightStatus.VET_CONFIRMED
    assert shared.target_weight_confirmed_by == vet_user
    assert shared.target_weight_confirmed_at is not None
    assert "Cílová hmotnost je potvrzená." in messages_of(response)
    assert shared.history.latest("history_date").history_user == vet_user


def test_detail_shows_target_weight_status_labels(client, user, vet_user, shared):
    client.force_login(user)
    content = client.get(detail_url(shared)).content.decode()
    assert "18,5\xa0kg" in content
    assert "orientační" in content
    assert "Ideální hmotnost by měl potvrdit veterinář podle BCS." in content
    assert "Potvrdit cílovou hmotnost" not in content  # owners cannot confirm

    client.force_login(vet_user)
    vet_page = client.get(detail_url(shared)).content.decode()
    assert "Potvrdit cílovou hmotnost 18,5\xa0kg" in vet_page
    assert 'name="target_weight_kg" value="18.500"' in vet_page
    confirm(client, shared)

    client.force_login(user)
    content = client.get(detail_url(shared)).content.decode()
    assert "potvrzeno veterinářem" in content
    assert "vet@example.cz" in content


def test_confirmation_refuses_a_changed_value(vet_client, shared):
    response = confirm(vet_client, shared, value="20")
    shared.refresh_from_db()
    assert shared.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert any("se mezitím změnila" in m for m in messages_of(response))


def test_confirmation_checks_the_stored_row_not_a_stale_instance(vet_user, shared):
    """The vet's page showed 18,5 kg; the owner saved 25 kg before the confirmation ran."""
    from django.core.exceptions import ValidationError

    from animals.services import confirm_target_weight

    stale = Animal.objects.get(pk=shared.pk)
    Animal.objects.filter(pk=shared.pk).update(target_weight_kg=Decimal("25"))

    with pytest.raises(ValidationError) as error:
        confirm_target_weight(stale, vet_user, Decimal("18.5"))

    assert error.value.code == "changed"
    shared.refresh_from_db()
    assert shared.target_weight_kg == Decimal("25")
    assert shared.target_weight_status == TargetWeightStatus.UNVERIFIED


def test_confirmation_without_target_weight(vet_client, shared):
    Animal.objects.filter(pk=shared.pk).update(target_weight_kg=None)
    response = confirm(vet_client, shared)
    assert "Majitel zatím nezadal cílovou hmotnost." in messages_of(response)


def test_confirmation_twice(vet_client, shared):
    confirm(vet_client, shared)
    response = confirm(vet_client, shared)
    assert "Cílová hmotnost už je potvrzená." in messages_of(response)


def test_confirmation_with_malformed_value(vet_client, shared):
    response = confirm(vet_client, shared, value="abc")
    shared.refresh_from_db()
    assert shared.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert any("Potvrzení se nepodařilo" in m for m in messages_of(response))


def test_owner_change_of_target_weight_resets_confirmation(client, user, vet_user, shared):
    client.force_login(vet_user)
    confirm(client, shared)
    client.force_login(user)
    url = reverse("animals:edit", args=[shared.uuid])
    data = {**ANIMAL_DATA, "name": "Rex", "sex": "MALE", "target_weight_kg": "18.5"}

    assert "Pokud ji změníte, potvrzení se zruší" in client.get(url).content.decode()

    # Same value written differently: the confirmation stays.
    client.post(url, {**data, "target_weight_kg": "18,500", "notes": "jiná poznámka"})
    shared.refresh_from_db()
    assert shared.target_weight_status == TargetWeightStatus.VET_CONFIRMED
    assert shared.notes == "jiná poznámka"

    client.post(url, {**data, "target_weight_kg": "17"})
    shared.refresh_from_db()
    assert shared.target_weight_kg == Decimal("17")
    assert shared.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert shared.target_weight_confirmed_by is None
    assert shared.target_weight_confirmed_at is None


def test_owner_removing_confirmed_target_weight(client, user, vet_user, shared):
    client.force_login(vet_user)
    confirm(client, shared)
    client.force_login(user)
    data = {**ANIMAL_DATA, "sex": "MALE", "target_weight_kg": ""}

    response = client.post(reverse("animals:edit", args=[shared.uuid]), data)

    assert response.status_code == 302
    shared.refresh_from_db()
    assert shared.target_weight_kg is None
    assert shared.target_weight_status == TargetWeightStatus.UNVERIFIED


# --- Measurements -----------------------------------------------------------------------------


def test_owner_adds_measurement(owner_client, user, make_animal):
    animal = make_animal(user)
    today = timezone.localdate().isoformat()

    response = owner_client.post(
        reverse("animals:measurement_add", args=[animal.uuid]),
        {
            "measured_on": today,
            "weight_kg": "21,25",
            "bcs": "6",
            "mcs": "MILD_LOSS",
            "note": "po zimě",
        },
    )

    assert response.status_code == 302
    measurement = animal.measurements.get()
    assert measurement.weight_kg == Decimal("21.25")
    assert measurement.bcs == 6
    assert measurement.assessed_by == Assessor.OWNER
    assert measurement.created_by == user


def test_measurement_form_errors(owner_client, user, make_animal):
    animal = make_animal(user)
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()

    response = owner_client.post(
        reverse("animals:measurement_add", args=[animal.uuid]),
        {"measured_on": tomorrow, "weight_kg": "250", "bcs": "10"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Datum měření nemůže být v budoucnosti." in content
    assert "Hmotnost psa zadejte v kilogramech v rozmezí 0,5–120 kg." in content
    assert not BodyMeasurement.objects.exists()


def test_measurement_form_shows_assessor(client, user, vet_user, shared):
    url = reverse("animals:measurement_add", args=[shared.uuid])
    client.force_login(vet_user)
    content = client.get(url).content.decode()
    assert "Měření se uloží jako posouzené <strong>veterinárním lékařem</strong>." in content
    client.force_login(user)
    content = client.get(url).content.decode()
    assert "Měření se uloží jako posouzené <strong>majitelem</strong>." in content


def test_measurements_table_newest_first(owner_client, user, make_animal, make_measurement):
    animal = make_animal(user)
    today = timezone.localdate()
    make_measurement(animal, measured_on=today - timedelta(days=20), weight_kg=Decimal("19"))
    make_measurement(animal, measured_on=today, weight_kg=Decimal("21"), bcs=5)
    make_measurement(animal, measured_on=today - timedelta(days=5), weight_kg=Decimal("20"))

    content = owner_client.get(detail_url(animal)).content.decode()

    positions = [content.index(f"{w}\xa0kg</td>") for w in ("21", "20", "19")]
    assert positions == sorted(positions)
    assert '<th scope="col">Hmotnost</th>' in content
    assert "5/9" in content


def test_delete_measurement(owner_client, user, make_animal, make_measurement):
    animal = make_animal(user)
    measurement = make_measurement(animal)
    url = reverse("animals:measurement_delete", args=[animal.uuid, measurement.uuid])

    assert "Smazat měření?" in owner_client.get(url).content.decode()
    response = owner_client.post(url)

    assert response.status_code == 302
    assert not BodyMeasurement.objects.exists()
    assert not BodyMeasurement.history.model.objects.exists()


def test_vet_sees_measurement_author(owner_client, user, vet_user, shared, make_measurement):
    make_measurement(shared, assessed_by=Assessor.VET, created_by=vet_user)
    content = owner_client.get(detail_url(shared)).content.decode()
    assert "veterinární lékař (vet@example.cz)" in content


# --- Conditions -------------------------------------------------------------------------------


def test_add_edit_remove_condition(owner_client, user, make_animal):
    animal = make_animal(user)
    ckd = HealthCondition.objects.get(code="CKD")
    add_url = reverse("animals:condition_add", args=[animal.uuid])

    response = owner_client.post(
        add_url,
        {
            "condition": ckd.pk,
            "diagnosed_by_vet": "on",
            "since": "2025-05-01",
            "vet_diet_restrictions": "<b>Omezit fosfor</b> podle ošetřujícího lékaře",
        },
    )
    assert response.status_code == 302
    item = animal.conditions.get()
    assert item.diagnosed_by_vet and item.since.isoformat() == "2025-05-01"

    detail = owner_client.get(detail_url(animal)).content.decode()
    assert "Chronické onemocnění ledvin (CKD)" in detail
    assert "Automatický výpočet nelze doporučit" in detail
    assert "&lt;b&gt;Omezit fosfor&lt;/b&gt; podle ošetřujícího lékaře" in detail
    assert "Aplikace text jen zobrazuje, nevyhodnocuje ho." in detail

    # Already recorded conditions are not offered again.
    add_page = owner_client.get(add_url).content.decode()
    assert "Chronické onemocnění ledvin" not in add_page
    duplicate = owner_client.post(add_url, {"condition": ckd.pk})
    assert duplicate.status_code == 200
    assert animal.conditions.count() == 1

    edit_url = reverse("animals:condition_edit", args=[animal.uuid, "CKD"])
    owner_client.post(edit_url, {"note": "kontrola v březnu"})
    item.refresh_from_db()
    assert item.note == "kontrola v březnu" and not item.diagnosed_by_vet
    assert item.condition == ckd

    remove_url = reverse("animals:condition_remove", args=[animal.uuid, "CKD"])
    assert "Odebrat zdravotní stav" in owner_client.get(remove_url).content.decode()
    owner_client.post(remove_url)
    assert not AnimalHealthCondition.objects.exists()


def test_condition_add_when_all_recorded(owner_client, user, make_animal):
    animal = make_animal(user)
    for condition in HealthCondition.objects.all():
        AnimalHealthCondition.objects.create(animal=animal, condition=condition)
    content = owner_client.get(
        reverse("animals:condition_add", args=[animal.uuid])
    ).content.decode()
    assert "zadané všechny zdravotní stavy" in content


def test_unknown_condition_code_is_404(owner_client, user, make_animal):
    animal = make_animal(user)
    url = reverse("animals:condition_edit", args=[animal.uuid, "NOPE"])
    assert owner_client.get(url).status_code == 404


# --- Sharing ----------------------------------------------------------------------------------


def share(client, animal, email):
    return client.post(reverse("animals:share_add", args=[animal.uuid]), {"email": email})


def test_share_with_vet(owner_client, user, make_animal, vet_user):
    animal = make_animal(user)

    response = share(owner_client, animal, " VET@example.cz ")

    assert response.status_code == 302
    created = AnimalShare.objects.get()
    assert (created.vet, created.granted_by, created.is_active) == (vet_user, user, True)
    detail = owner_client.get(detail_url(animal)).content.decode()
    assert "vet@example.cz, sdíleno od" in detail
    assert "Zrušit sdílení" in detail


@pytest.mark.parametrize("case", ["missing", "owner_role", "inactive_vet"])
def test_share_requires_a_vet_account(owner_client, user, make_animal, make_user, case):
    animal = make_animal(user)
    if case == "owner_role":
        make_user("soused@example.cz")
    elif case == "inactive_vet":
        make_user("soused@example.cz", roles=(Role.VET,), is_active=False)

    response = share(owner_client, animal, "soused@example.cz")

    assert response.status_code == 200
    assert NOT_A_VET_MESSAGE in response.content.decode()
    assert not AnimalShare.objects.exists()


def test_share_with_own_account_or_twice(owner_client, user, make_animal, vet_user):
    user.groups.add(*vet_user.groups.all())  # the owner is a vet too
    animal = make_animal(user)
    assert (
        "nelze sdílet se svým vlastním účtem"
        in share(owner_client, animal, user.email).content.decode()
    )
    share(owner_client, animal, vet_user.email)
    response = share(owner_client, animal, vet_user.email)
    assert "S tímto veterinářem už zvíře sdílíte." in response.content.decode()
    assert AnimalShare.objects.count() == 1


def test_revoke_share_and_share_again(client, user, vet_user, shared):
    item = AnimalShare.objects.get()
    client.force_login(vet_user)
    assert client.get(detail_url(shared)).status_code == 200

    client.force_login(user)
    response = client.post(reverse("animals:share_revoke", args=[shared.uuid, item.uuid]))
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.revoked_at is not None
    assert "Sdílení s vet@example.cz bylo zrušeno." in messages_of(response)
    # Revoking twice: the share is no longer active.
    assert (
        client.post(reverse("animals:share_revoke", args=[shared.uuid, item.uuid])).status_code
        == 404
    )

    client.force_login(vet_user)
    assert client.get(detail_url(shared)).status_code == 404

    client.force_login(user)
    share(client, shared, vet_user.email)
    assert AnimalShare.objects.active().count() == 1
    assert AnimalShare.objects.count() == 2


# --- Detail page for owner and vet ------------------------------------------------------------


def test_detail_for_owner(owner_client, user, make_animal, make_measurement):
    animal = make_animal(
        user, allergies=["ryby"], birth_date=timezone.localdate() - timedelta(days=800)
    )
    make_measurement(animal, bcs=8)
    content = owner_client.get(detail_url(animal)).content.decode()

    assert "<h1>Rex</h1>" in content
    assert "Vyžaduje odborné posouzení" in content
    assert "Poslední zadané BCS je 8/9" in content
    assert "Co dělat dál:" in content
    assert "Pro veterinárního lékaře:" not in content
    assert "nenahrazuje veterinární vyšetření" in content
    assert "ryby" in content
    assert "věk: 2 roky" in content
    for name in ("edit", "delete", "measurement_add", "condition_add", "share_add"):
        assert reverse(f"animals:{name}", args=[animal.uuid]) in content
    assert "Sdílení s veterinárním lékařem" in content
    assert "Velikostní kategorie" in content
    assert "no-store" in owner_client.get(detail_url(animal))["Cache-Control"]


def test_detail_for_shared_vet(vet_client, shared, make_measurement):
    make_measurement(shared, bcs=5)
    content = vet_client.get(detail_url(shared)).content.decode()

    assert "Zvíře s vámi sdílí: jana@example.cz." in content
    # The target weight section speaks to the vet who can confirm it.
    assert "Cílovou hmotnost zadal majitel; zatím je jen orientační." in content
    assert reverse("animals:measurement_add", args=[shared.uuid]) in content
    for name in ("edit", "delete", "condition_add", "share_add"):
        assert reverse(f"animals:{name}", args=[shared.uuid]) not in content
    assert "Zrušit sdílení" not in content
    assert "/smazat/" not in content


def test_detail_ok_level_does_not_promise_health(owner_client, user, make_animal, make_measurement):
    animal = make_animal(user)
    make_measurement(animal, bcs=5)
    content = owner_client.get(detail_url(animal)).content.decode()
    assert "Bez upozornění v evidenci" in content
    assert "Neznamená to, že je" in content
    assert "status--ok" in content


def test_badges_have_icon_text_and_class(owner_client, user, make_animal):
    animal = make_animal(user)
    content = owner_client.get(detail_url(animal)).content.decode()
    badge = re.search(r'<span class="status status--info">.*?</span></span>', content)
    assert badge, content
    assert 'aria-hidden="true">ⓘ' in badge.group(0)
    assert "Informativní doporučení" in badge.group(0)


def test_forms_show_czech_empty_choices_and_trimmed_weights(owner_client, user, make_animal):
    animal = make_animal(user, target_weight_kg=Decimal("18.500"), expected_adult_weight_kg=20)
    content = owner_client.get(reverse("animals:edit", args=[animal.uuid])).content.decode()
    assert 'name="target_weight_kg" value="18,5"' in content
    assert 'name="expected_adult_weight_kg" value="20"' in content
    assert "— vyberte —" in content and "---------" not in content


def test_measurement_form_defaults_to_today(owner_client, user, make_animal):
    animal = make_animal(user)
    content = owner_client.get(
        reverse("animals:measurement_add", args=[animal.uuid])
    ).content.decode()
    assert f'value="{timezone.localdate().isoformat()}"' in content


def test_detail_names_the_owner_for_a_vet(client, make_user, vet_user, make_animal):
    owner = make_user("owner@example.cz", first_name="Jana", last_name="Nováková")
    animal = make_animal(owner)
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=owner)
    client.force_login(vet_user)
    content = client.get(detail_url(animal)).content.decode()
    assert "Zvíře s vámi sdílí: Jana Nováková (owner@example.cz)." in content
    assert "majitel Jana" not in content


def test_attention_advice_is_written_for_the_viewer(client, vet_user, shared, make_measurement):
    make_measurement(shared, bcs=8)
    client.force_login(vet_user)
    vet_page = client.get(detail_url(shared)).content.decode()
    assert "Pro veterinárního lékaře:" in vet_page
    assert "Co dělat dál:" not in vet_page


# --- Data minimisation for vets (docs/12 §12.6) -------------------------------------------------


def test_vet_does_not_see_another_vets_email(
    client, user, make_user, make_animal, make_measurement
):
    first = make_user("v1@example.cz", roles=(Role.VET,))
    second = make_user("v2@example.cz", roles=(Role.VET,))
    animal = make_animal(user, target_weight_kg=Decimal("20"))
    for vet in (first, second):
        AnimalShare.objects.create(animal=animal, vet=vet, granted_by=user)
    make_measurement(animal, assessed_by=Assessor.VET, created_by=second)
    client.force_login(second)
    confirm(client, animal, value="20")

    client.force_login(first)
    other_vet_page = client.get(detail_url(animal)).content.decode()
    assert "v2@example.cz" not in other_vet_page
    assert "Potvrdil(a) veterinární lékař dne" in other_vet_page

    client.force_login(second)
    own_page = client.get(detail_url(animal)).content.decode()
    assert "veterinární lékař (v2@example.cz)" in own_page
    assert "Potvrdil(a) v2@example.cz dne" in own_page

    client.force_login(user)
    owner_page = client.get(detail_url(animal)).content.decode()
    assert "veterinární lékař (v2@example.cz)" in owner_page
    assert "Potvrdil(a) v2@example.cz dne" in owner_page


def test_share_form_lists_what_the_vet_will_see(owner_client, user, make_animal):
    content = owner_client.get(
        reverse("animals:share_add", args=[make_animal(user).uuid])
    ).content.decode()
    assert "vaše jméno (pokud ho máte v profilu vyplněné) a e-mail" in content
    assert "E-maily jiných veterinárních lékařů" in content


# --- Delete confirmation wording ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "text"),
    [(0, "0 zdravotních stavů"), (1, "1 zdravotní stav,"), (2, "2 zdravotní stavy"),
     (5, "5 zdravotních stavů")],
)
def test_delete_confirmation_uses_czech_plural(owner_client, user, make_animal, count, text):
    animal = make_animal(user)
    for condition in HealthCondition.objects.order_by("code")[:count]:
        AnimalHealthCondition.objects.create(animal=animal, condition=condition)
    page = owner_client.get(reverse("animals:delete", args=[animal.uuid])).content.decode()
    assert text in page


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "stavů"), (1, "stav"), (2, "stavy"), (4, "stavy"), (5, "stavů"), (11, "stavů")],
)
def test_plural_helper(count, expected):
    from animals.services import plural

    assert plural(count, "stav", "stavy", "stavů") == expected


# --- Revoking a share --------------------------------------------------------------------------


def test_revoke_share_has_a_confirmation_page(owner_client, shared):
    item = AnimalShare.objects.get()
    url = reverse("animals:share_revoke", args=[shared.uuid, item.uuid])
    detail = owner_client.get(detail_url(shared)).content.decode()
    assert f'href="{url}"' in detail  # a link to the confirmation, not a one-click form

    page = owner_client.get(url).content.decode()
    assert "Zrušit sdílení s vet@example.cz?" in page
    assert "ihned ztratí přístup" in page
    assert "Ponechat sdílení" in page
    assert AnimalShare.objects.get().is_active  # GET changes nothing

    owner_client.post(url)
    assert not AnimalShare.objects.get().is_active


# --- Profile facts and hints ---------------------------------------------------------------------


def test_allergies_without_food_allergy_condition_show_a_hint(owner_client, user, make_animal):
    animal = make_animal(user, allergies=["kuřecí maso"])
    hint = "zadejte také jako zdravotní stav „Potravní alergie“"
    assert hint in owner_client.get(detail_url(animal)).content.decode()

    AnimalHealthCondition.objects.create(
        animal=animal, condition=HealthCondition.objects.get(code="FOOD_ALLERGY")
    )
    assert hint not in owner_client.get(detail_url(animal)).content.decode()


def test_allergy_hint_is_not_shown_to_a_vet(vet_client, shared):
    Animal.objects.filter(pk=shared.pk).update(allergies=["kuřecí maso"])
    content = vet_client.get(detail_url(shared)).content.decode()
    assert "kuřecí maso" in content
    assert "Potravní alergie“ (" not in content


def test_new_animal_has_no_preselected_physiological_state(owner_client):
    """A puppy must not end up as an adult by leaving a default (docs/09 §9.2)."""
    content = owner_client.get(reverse("animals:create")).content.decode()
    select = re.search(r'<select name="physiological_state".*?</select>', content, re.S).group(0)
    assert 'value="" selected' in select
    assert 'value="MAINTENANCE" selected' not in select

    data = {**ANIMAL_DATA, "physiological_state": ""}
    response = owner_client.post(reverse("animals:create"), data)
    assert response.status_code == 200
    assert not Animal.objects.exists()


def test_edit_form_keeps_the_stored_physiological_state(owner_client, user, make_animal):
    animal = make_animal(user)
    content = owner_client.get(reverse("animals:edit", args=[animal.uuid])).content.decode()
    assert 'value="MAINTENANCE" selected' in content


@pytest.mark.parametrize(
    "change",
    [{"species": "CAT", "size_category": "", "target_weight_kg": "10"},
     {"sex": "FEMALE", "physiological_state": "GESTATION"}],
    ids=["species", "state"],
)
def test_owner_change_of_species_or_state_resets_confirmation(client, user, vet_user, make_animal,
                                                              change):
    animal = make_animal(user, target_weight_kg=Decimal("10"))
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    client.force_login(vet_user)
    confirm(client, animal, value="10")
    client.force_login(user)
    data = {**ANIMAL_DATA, "name": "Rex", "sex": "MALE", "target_weight_kg": "10", **change}

    response = client.post(reverse("animals:edit", args=[animal.uuid]), data)

    assert response.status_code == 302
    animal.refresh_from_db()
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert animal.target_weight_confirmed_by is None


def test_removing_the_vet_role_cancels_that_vets_confirmations(client, user, vet_user, shared):
    client.force_login(vet_user)
    confirm(client, shared)
    shared.refresh_from_db()
    assert shared.target_weight_confirmed

    vet_user.groups.clear()

    shared.refresh_from_db()
    assert shared.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert shared.target_weight_confirmed_by is None


def test_removing_a_user_from_the_vet_group_side(client, user, vet_user, shared):
    from django.contrib.auth.models import Group

    client.force_login(vet_user)
    confirm(client, shared)
    Group.objects.get(name=Role.VET).user_set.remove(vet_user)
    shared.refresh_from_db()
    assert shared.target_weight_status == TargetWeightStatus.UNVERIFIED


def test_other_role_changes_keep_confirmations(client, user, vet_user, shared):
    from django.contrib.auth.models import Group

    client.force_login(vet_user)
    confirm(client, shared)
    vet_user.groups.remove(Group.objects.get_or_create(name=Role.DATA_CURATOR)[0])
    vet_user.groups.add(Group.objects.get_or_create(name=Role.OWNER)[0])
    shared.refresh_from_db()
    assert shared.target_weight_status == TargetWeightStatus.VET_CONFIRMED


def test_attention_panel_shows_each_level_once(owner_client, user, make_animal, make_measurement):
    """docs/08 §8.6 label once per level, then the reasons, so screen readers do not repeat it."""
    from animals.models import PhysiologicalState, Sex

    animal = make_animal(
        user, sex=Sex.FEMALE, physiological_state=PhysiologicalState.LACTATION
    )
    make_measurement(animal, bcs=2)
    AnimalHealthCondition.objects.create(
        animal=animal, condition=HealthCondition.objects.get(code="FOOD_ALLERGY")
    )
    content = owner_client.get(detail_url(animal)).content.decode()
    panel = content[content.index('id="attention-title"') : content.index("notice__footnote")]

    assert panel.count("Automatický výpočet nelze doporučit") == 1
    assert panel.count("Vyžaduje odborné posouzení") == 1
    reasons = re.findall(r"<li>(.*?)</li>", panel, re.S)
    assert len(reasons) == 3
    assert not any("nelze doporučit" in reason for reason in reasons)
    assert panel.index("Automatický výpočet") < panel.index("Laktace:")
    assert panel.index("Laktace:") < panel.index("Vyžaduje odborné posouzení")
    assert "nutriční kalkulačka zatím není k dispozici" in " ".join(panel.split())
