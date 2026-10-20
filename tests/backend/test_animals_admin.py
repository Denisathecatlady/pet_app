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


def test_admin_rejects_invalid_confirmation(admin_client, objects):
    """Constraint messages reach the admin form instead of a database error."""
    animal = objects[Animal]
    url = reverse("admin:animals_animal_change", args=[animal.pk])
    data = {
        "owner": animal.owner_id,
        "name": animal.name,
        "species": "DOG",
        "sex": "MALE",
        "activity_level": "MODERATE",
        "physiological_state": "MAINTENANCE",
        "target_weight_kg": "20",
        "target_weight_status": "VET_CONFIRMED",
        "allergies": "[]",
    }
    response = admin_client.post(url, data)
    assert response.status_code == 200
    assert "Potvrzená cílová hmotnost musí mít" in response.content.decode()
    animal.refresh_from_db()
    assert animal.target_weight_status == "UNVERIFIED"


def test_non_staff_cannot_open_admin(logged_in_client):
    response = logged_in_client.get(reverse("admin:animals_animal_changelist"))
    assert response.status_code == 302
