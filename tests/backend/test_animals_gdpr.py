"""GDPR: export of animal data and deletion cascades (docs/07 §7.7)."""

import json
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.export import build_export
from accounts.services import delete_account
from animals.models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    Assessor,
    BodyMeasurement,
    HealthCondition,
    TargetWeightStatus,
)
from tests.backend.helpers import PASSWORD

pytestmark = pytest.mark.django_db

HISTORY_MODELS = [
    m.history.model for m in (Animal, BodyMeasurement, AnimalHealthCondition, AnimalShare)
]


@pytest.fixture
def records(user, make_user, make_animal, make_measurement, vet_user):
    """The owner ``user`` with one animal shared with ``vet_user``, and an unrelated owner."""
    animal = make_animal(user, name="Rex", allergies=["kuřecí"], target_weight_kg=Decimal("20"))
    make_measurement(animal, bcs=5, note="po očkování")
    make_measurement(
        animal, assessed_by=Assessor.VET, created_by=vet_user, weight_kg=Decimal("20.5")
    )
    AnimalHealthCondition.objects.create(
        animal=animal,
        condition=HealthCondition.objects.get(code="FOOD_ALLERGY"),
        vet_diet_restrictions="bez drůbeže",
    )
    share = AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    animal.target_weight_status = TargetWeightStatus.VET_CONFIRMED
    animal.target_weight_confirmed_by = vet_user
    animal.target_weight_confirmed_at = timezone.now()
    animal.save()
    other_owner = make_user("other@example.cz")
    other = make_animal(other_owner, name="Cizák", notes="tajná poznámka")
    make_measurement(other, note="cizí měření")
    return {"animal": animal, "share": share, "other": other, "other_owner": other_owner}


# --- Export -----------------------------------------------------------------------------------


def test_export_contains_own_animal_data(client, user, records, vet_user):
    client.force_login(user)
    data = json.loads(client.get(reverse("accounts:export")).content)

    section = data["data"]["animals"]
    assert section["shares_received"] == []
    (animal,) = section["owned_animals"]
    assert animal["uuid"] == str(records["animal"].uuid)
    assert animal["name"] == "Rex"
    assert animal["allergies"] == ["kuřecí"]
    assert animal["target_weight_kg"] == "20.000"
    assert animal["target_weight_status"] == "VET_CONFIRMED"
    assert animal["target_weight_confirmed_by"] == vet_user.email
    assert [m["weight_kg"] for m in animal["measurements"]] == ["20.000", "20.500"]
    assert {m["assessed_by"] for m in animal["measurements"]} == {"OWNER", "VET"}
    assert animal["health_conditions"][0]["condition"] == "FOOD_ALLERGY"
    assert animal["health_conditions"][0]["vet_diet_restrictions"] == "bez drůbeže"
    assert animal["shares"][0]["vet"] == vet_user.email
    assert animal["shares"][0]["revoked_at"] is None
    # Change history with past values.
    assert [h["change"] for h in animal["history"]] == ["created", "changed"]
    assert animal["history"][0]["values"]["target_weight_status"] == "UNVERIFIED"
    assert animal["measurements"][0]["history"][0]["change"] == "created"


def test_export_excludes_other_users_data(client, user, records):
    client.force_login(user)
    raw = client.get(reverse("accounts:export")).content.decode()
    for secret in ("Cizák", "tajná poznámka", "cizí měření", "other@example.cz"):
        assert secret not in raw
    assert str(records["other"].uuid) not in raw


def test_vet_export_lists_received_shares_without_owner_data(records, vet_user):
    data = build_export(vet_user)["data"]["animals"]

    assert data["owned_animals"] == []
    (received,) = data["shares_received"]
    assert received == {
        "uuid": str(records["share"].uuid),
        "animal_uuid": str(records["animal"].uuid),
        "created_at": received["created_at"],
        "revoked_at": None,
    }
    raw = json.dumps(data, ensure_ascii=False)
    assert "Rex" not in raw and "kuřecí" not in raw and "po očkování" not in raw


def test_export_is_json_serialisable_without_custom_encoder(user, records):
    json.dumps(build_export(user))


# --- Deletion cascades ------------------------------------------------------------------------


def test_owner_deletion_removes_animals_and_their_history(records, user, vet_user):
    animal = records["animal"]
    for model in HISTORY_MODELS:
        assert model.objects.filter(**_history_filter(model, animal)).exists(), model

    delete_account(user)

    assert not Animal.objects.filter(pk=animal.pk).exists()
    assert not BodyMeasurement.objects.filter(animal_id=animal.pk).exists()
    assert not AnimalHealthCondition.objects.filter(animal_id=animal.pk).exists()
    assert not AnimalShare.objects.filter(animal_id=animal.pk).exists()
    for model in HISTORY_MODELS:
        assert not model.objects.filter(**_history_filter(model, animal)).exists(), model
    # The other owner's data and the vet's account stay.
    assert Animal.objects.filter(pk=records["other"].pk).exists()
    assert records["other"].history.exists()
    assert type(vet_user).objects.filter(pk=vet_user.pk).exists()


def _history_filter(model, animal):
    if model is Animal.history.model:
        return {"id": animal.pk}
    return {"animal_id": animal.pk}


def test_owner_deletion_through_the_view(client, user, records):
    client.force_login(user)
    response = client.post(reverse("accounts:delete"), {"password": PASSWORD})
    assert response.status_code == 302
    assert not Animal.objects.filter(name="Rex").exists()
    assert Animal.objects.filter(name="Cizák").exists()


def test_vet_deletion_removes_shares_and_resets_confirmation(records, user, vet_user):
    animal = records["animal"]
    share_pk = records["share"].pk

    delete_account(vet_user)

    assert not AnimalShare.objects.filter(pk=share_pk).exists()
    assert not AnimalShare.history.model.objects.filter(id=share_pk).exists()
    animal.refresh_from_db()
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert animal.target_weight_confirmed_by is None
    assert animal.target_weight_confirmed_at is None
    assert animal.history.latest("history_date").target_weight_status == "UNVERIFIED"
    # The owner's records stay; the vet's measurement loses its author link only.
    vet_measurement = animal.measurements.get(weight_kg=Decimal("20.5"))
    assert vet_measurement.assessed_by == Assessor.VET
    assert vet_measurement.created_by is None
    assert animal.measurements.count() == 2


def test_deleting_a_user_who_confirmed_own_animal(user, make_animal):
    """Confirmation by the owner is impossible in the UI, but must not block deletion."""
    animal = make_animal(user)
    Animal.objects.filter(pk=animal.pk).update(
        target_weight_kg=Decimal("20"),
        target_weight_status=TargetWeightStatus.VET_CONFIRMED,
        target_weight_confirmed_by=user,
        target_weight_confirmed_at=timezone.now(),
    )
    delete_account(user)
    assert not Animal.objects.exists()
    assert not Animal.history.model.objects.exists()


def test_delete_page_explains_consequences_for_vets(client, vet_user, user):
    client.force_login(vet_user)
    assert (
        "ztratíte přístup ke všem zvířatům"
        in client.get(reverse("accounts:delete")).content.decode()
    )
    client.force_login(user)
    assert "ztratíte přístup" not in client.get(reverse("accounts:delete")).content.decode()


def test_privacy_draft_describes_sharing(client):
    content = client.get(reverse("core:privacy")).content.decode()
    assert "roli veterinárního lékaře" in content and "váš e-mail" in content
