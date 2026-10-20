"""Admin of the animals app: every model registered, with history pages."""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.urls import reverse
from simple_history.admin import SimpleHistoryAdmin

from accounts.models import User
from animals.models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    BodyMeasurement,
    HealthCondition,
)
from tests.backend.helpers import PASSWORD

pytestmark = pytest.mark.django_db

MODELS = [Animal, BodyMeasurement, HealthCondition, AnimalHealthCondition, AnimalShare]


@pytest.fixture
def admin_client(client):
    client.force_login(User.objects.create_superuser("admin@example.cz", PASSWORD))
    return client


@pytest.fixture
def objects(user, make_animal, make_measurement, vet_user):
    animal = make_animal(user, target_weight_kg=Decimal("20"))
    return {
        Animal: animal,
        BodyMeasurement: make_measurement(animal),
        HealthCondition: HealthCondition.objects.get(code="CKD"),
        AnimalHealthCondition: AnimalHealthCondition.objects.create(
            animal=animal, condition=HealthCondition.objects.get(code="CKD")
        ),
        AnimalShare: AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user),
    }


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_models_use_history_admin(model):
    assert isinstance(admin.site._registry[model], SimpleHistoryAdmin)


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_admin_pages_load(admin_client, objects, model):
    name = model._meta.model_name
    obj = objects[model]
    for url in (
        reverse(f"admin:animals_{name}_changelist"),
        reverse(f"admin:animals_{name}_add"),
        reverse(f"admin:animals_{name}_change", args=[obj.pk]),
        reverse(f"admin:animals_{name}_history", args=[obj.pk]),
    ):
        assert admin_client.get(url).status_code == 200, url


def admin_animal_data(animal, **changes):
    data = {
        "owner": animal.owner_id,
        "name": animal.name,
        "species": "DOG",
        "sex": "MALE",
        "activity_level": "MODERATE",
        "physiological_state": "MAINTENANCE",
        "target_weight_kg": str(animal.target_weight_kg),
        "allergies": "[]",
    }
    return {**data, **changes}


def confirm(animal, vet):
    from animals.services import confirm_target_weight

    confirm_target_weight(animal, vet, animal.target_weight_kg)


def test_admin_cannot_set_a_confirmation(admin_client, objects, user):
    """Only a vet with a share confirms (docs/05 §5.3): the fields are read-only."""
    animal = objects[Animal]
    url = reverse("admin:animals_animal_change", args=[animal.pk])
    content = admin_client.get(url).content.decode()
    assert 'name="target_weight_status"' not in content
    assert 'name="target_weight_confirmed_by"' not in content

    data = admin_animal_data(
        animal, target_weight_status="VET_CONFIRMED", target_weight_confirmed_by=user.pk
    )
    assert admin_client.post(url, data).status_code == 302
    animal.refresh_from_db()
    assert animal.target_weight_status == "UNVERIFIED"
    assert animal.target_weight_confirmed_by is None


@pytest.mark.parametrize(
    "change",
    [
        {"target_weight_kg": "35"},
        {"species": "CAT", "target_weight_kg": "10"},
        {"physiological_state": "GROWTH"},
    ],
    ids=["target_weight", "species", "state"],
)
def test_admin_change_of_the_basis_cancels_confirmation(admin_client, objects, vet_user, change):
    animal = objects[Animal]
    if "species" in change:
        BodyMeasurement.objects.all().delete()  # a 20 kg measurement does not fit a cat
        animal.target_weight_kg = Decimal("10")
        animal.save()
    confirm(animal, vet_user)
    url = reverse("admin:animals_animal_change", args=[animal.pk])

    response = admin_client.post(url, admin_animal_data(animal, **change))

    assert response.status_code == 302, response.content.decode()[:2000]
    animal.refresh_from_db()
    assert animal.target_weight_status == "UNVERIFIED"
    assert animal.target_weight_confirmed_by is None and animal.target_weight_confirmed_at is None


def test_admin_edit_of_other_fields_keeps_confirmation(admin_client, objects, vet_user):
    animal = objects[Animal]
    confirm(animal, vet_user)
    url = reverse("admin:animals_animal_change", args=[animal.pk])

    data = admin_animal_data(animal, name="Rexík", target_weight_kg="20.0")
    response = admin_client.post(url, data)

    assert response.status_code == 302
    animal.refresh_from_db()
    assert animal.name == "Rexík"
    assert animal.target_weight_status == "VET_CONFIRMED"
    assert animal.target_weight_confirmed_by == vet_user


def test_non_staff_cannot_open_admin(logged_in_client):
    response = logged_in_client.get(reverse("admin:animals_animal_changelist"))
    assert response.status_code == 302
