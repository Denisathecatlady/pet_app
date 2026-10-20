"""Permission matrix of the animals views (docs/07 §7.7: tests for every endpoint).

Roles: owner, vet with an active share, vet whose share was revoked, vet without a
share, another owner and an anonymous visitor. Expected: 200/302 where allowed, 403
for visible but forbidden actions, 404 for animals the user may not see, 302 to the
login page for anonymous visitors and 405 for wrong HTTP methods.
"""

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.forms.models import model_to_dict
from django.http import Http404
from django.test import Client
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
from animals.permissions import ALLOWED_ACTIONS, Action, Relation, get_animal_for

pytestmark = pytest.mark.django_db

ROLES = ("owner", "shared_vet", "revoked_vet", "unshared_vet", "other_owner", "anonymous")
HIDDEN = ("revoked_vet", "unshared_vet", "other_owner")


@pytest.fixture
def world(make_user, make_animal, make_measurement):
    owner = make_user("owner@example.cz")
    users = {
        "owner": owner,
        "shared_vet": make_user("vet@example.cz", roles=(Role.VET,)),
        "revoked_vet": make_user("revoked@example.cz", roles=(Role.VET,)),
        "unshared_vet": make_user("lone@example.cz", roles=(Role.VET,)),
        "other_owner": make_user("other@example.cz"),
        "anonymous": None,
    }
    animal = make_animal(owner, target_weight_kg=Decimal("20"))
    measurement = make_measurement(animal)
    item = AnimalHealthCondition.objects.create(
        animal=animal, condition=HealthCondition.objects.get(code="FOOD_ALLERGY")
    )
    share = AnimalShare.objects.create(animal=animal, vet=users["shared_vet"], granted_by=owner)
    AnimalShare.objects.create(
        animal=animal, vet=users["revoked_vet"], granted_by=owner, revoked_at=timezone.now()
    )
    return SimpleNamespace(
        users=users, animal=animal, measurement=measurement, item=item, share=share
    )


def client_for(world, role) -> Client:
    client = Client()
    if world.users[role] is not None:
        client.force_login(world.users[role])
    return client


@dataclass(frozen=True)
class Endpoint:
    name: str
    get: dict  # expected GET status per role (missing = 404)
    post: dict  # expected POST status per role (missing = 404)

    def url(self, world) -> str:
        a = world.animal.uuid
        kwargs = {
            "detail": {"animal_uuid": a},
            "edit": {"animal_uuid": a},
            "delete": {"animal_uuid": a},
            "measurement_add": {"animal_uuid": a},
            "measurement_delete": {"animal_uuid": a, "measurement_uuid": world.measurement.uuid},
            "condition_add": {"animal_uuid": a},
            "condition_edit": {"animal_uuid": a, "code": "FOOD_ALLERGY"},
            "condition_remove": {"animal_uuid": a, "code": "FOOD_ALLERGY"},
            "share_add": {"animal_uuid": a},
            "share_revoke": {"animal_uuid": a, "share_uuid": world.share.uuid},
            "target_weight_confirm": {"animal_uuid": a},
        }[self.name]
        return reverse(f"animals:{self.name}", kwargs=kwargs)


def post_data(name: str) -> dict:
    today = timezone.localdate().isoformat()
    return {
        "detail": {},
        # Every field differs from the ``world`` animal, so a leaked edit is visible.
        "edit": {
            "name": "Změněno",
            "species": "DOG",
            "sex": "MALE",
            "neutered": "on",
            "physiological_state": "MAINTENANCE",
            "activity_level": "LOW",
            "target_weight_kg": "25",
            "notes": "cizí zásah",
        },
        "delete": {},
        "measurement_add": {"measured_on": today, "weight_kg": "21,5", "bcs": "5"},
        "measurement_delete": {},
        "condition_add": {"condition": HealthCondition.objects.get(code="CKD").pk},
        "condition_edit": {"diagnosed_by_vet": "on", "note": "upraveno"},
        "condition_remove": {},
        "share_add": {"email": "lone@example.cz"},
        "share_revoke": {},
        "target_weight_confirm": {"target_weight_kg": "20"},
    }[name]


OWNER_ONLY = {"owner": 200, "shared_vet": 403}
OWNER_ONLY_POST = {"owner": 302, "shared_vet": 403}
ENDPOINTS = [
    Endpoint("detail", {"owner": 200, "shared_vet": 200}, {r: 405 for r in ROLES[:-1]}),
    Endpoint("edit", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint("delete", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint(
        "measurement_add", {"owner": 200, "shared_vet": 200}, {"owner": 302, "shared_vet": 302}
    ),
    Endpoint("measurement_delete", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint("condition_add", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint("condition_edit", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint("condition_remove", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint("share_add", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint("share_revoke", OWNER_ONLY, OWNER_ONLY_POST),
    Endpoint(
        "target_weight_confirm",
        {r: 405 for r in ROLES[:-1]},
        {"owner": 403, "shared_vet": 302},
    ),
]


def expected_status(table: dict, role: str) -> int:
    return 302 if role == "anonymous" else table.get(role, 404)


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.name)
@pytest.mark.parametrize("role", ROLES)
def test_get_matrix(world, endpoint, role):
    response = client_for(world, role).get(endpoint.url(world))
    expected = expected_status(endpoint.get, role)
    assert response.status_code == expected
    if role == "anonymous":
        assert response["Location"].startswith(reverse("accounts:login"))


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.name)
@pytest.mark.parametrize("role", ROLES)
def test_post_matrix(world, endpoint, role):
    url = endpoint.url(world)
    response = client_for(world, role).post(url, post_data(endpoint.name))
    expected = expected_status(endpoint.post, role)
    assert response.status_code == expected, response.content.decode()[:500]
    if role == "anonymous":
        assert response["Location"].startswith(reverse("accounts:login"))


def snapshot():
    """Every stored row of the animals app, compared before and after forbidden requests."""
    return {
        model.__name__: sorted(
            (model_to_dict(obj, exclude=["allergies"]) for obj in model.objects.all()),
            key=lambda row: row["id"],
        )
        for model in (Animal, BodyMeasurement, AnimalHealthCondition, AnimalShare)
    }


@pytest.mark.parametrize("role", ["shared_vet", *HIDDEN, "anonymous"])
def test_forbidden_posts_change_nothing(world, role):
    before = snapshot()
    client = client_for(world, role)
    for endpoint in ENDPOINTS:
        if endpoint.name not in ("measurement_add", "target_weight_confirm"):
            client.post(endpoint.url(world), post_data(endpoint.name))

    assert snapshot() == before


@pytest.mark.parametrize("role", ["shared_vet", *HIDDEN, "anonymous"])
def test_forbidden_edit_leaves_every_field(world, role):
    """Guard of the guard: the edit data would change every field if it got through."""
    before = model_to_dict(Animal.objects.get(pk=world.animal.pk))
    client_for(world, role).post(
        reverse("animals:edit", args=[world.animal.uuid]), post_data("edit")
    )
    assert model_to_dict(Animal.objects.get(pk=world.animal.pk)) == before

    owner = client_for(world, "owner")
    owner.post(reverse("animals:edit", args=[world.animal.uuid]), post_data("edit"))
    after = model_to_dict(Animal.objects.get(pk=world.animal.pk))
    changed = {name for name in before if before[name] != after[name]}
    assert {"name", "neutered", "activity_level", "target_weight_kg", "notes"} <= changed


@pytest.mark.parametrize("role", [*HIDDEN, "anonymous"])
def test_hidden_users_cannot_add_measurements_or_confirm(world, role):
    client = client_for(world, role)
    for name in ("measurement_add", "target_weight_confirm"):
        endpoint = next(e for e in ENDPOINTS if e.name == name)
        client.post(endpoint.url(world), post_data(name))

    assert BodyMeasurement.objects.count() == 1
    assert Animal.objects.get().target_weight_status == TargetWeightStatus.UNVERIFIED


@pytest.mark.parametrize("role", ROLES)
def test_create_matrix(world, role):
    client = client_for(world, role)
    url = reverse("animals:create")
    get_status = client.get(url).status_code
    response = client.post(url, {**post_data("edit"), "name": "Nový"})

    if role == "anonymous":
        assert get_status == 302 and response.status_code == 302
        assert not Animal.objects.filter(name="Nový").exists()
    else:
        assert get_status == 200 and response.status_code == 302
        assert Animal.objects.get(name="Nový").owner == world.users[role]


def test_unknown_animal_is_404_even_for_signed_in_owner(world):
    client = client_for(world, "owner")
    url = reverse("animals:detail", kwargs={"animal_uuid": "00000000-0000-0000-0000-000000000000"})
    assert client.get(url).status_code == 404


def test_vet_who_lost_the_role_loses_access(world):
    vet = world.users["shared_vet"]
    vet.groups.clear()
    client = client_for(world, "shared_vet")
    assert client.get(reverse("animals:detail", args=[world.animal.uuid])).status_code == 404


def test_child_objects_of_another_animal_are_404(world, make_animal, make_measurement):
    owner = world.users["owner"]
    other_animal = make_animal(owner, name="Bobík")
    client = client_for(world, "owner")
    # Measurement and share of ``world.animal`` addressed through ``other_animal``.
    urls = [
        reverse("animals:measurement_delete", args=[other_animal.uuid, world.measurement.uuid]),
        reverse("animals:condition_edit", args=[other_animal.uuid, "FOOD_ALLERGY"]),
        reverse("animals:condition_remove", args=[other_animal.uuid, "FOOD_ALLERGY"]),
    ]
    for url in urls:
        assert client.get(url).status_code == 404
        assert client.post(url).status_code == 404
    revoke = reverse("animals:share_revoke", args=[other_animal.uuid, world.share.uuid])
    assert client.post(revoke).status_code == 404
    assert BodyMeasurement.objects.filter(pk=world.measurement.pk).exists()
    assert AnimalShare.objects.get(pk=world.share.pk).is_active


# --- POST only and CSRF -----------------------------------------------------------------------


def test_get_never_changes_state(world):
    client = client_for(world, "owner")
    for endpoint in ENDPOINTS:
        client.get(endpoint.url(world))
    vet_client = client_for(world, "shared_vet")
    vet_client.get(reverse("animals:target_weight_confirm", args=[world.animal.uuid]))

    assert Animal.objects.filter(pk=world.animal.pk).exists()
    assert BodyMeasurement.objects.filter(pk=world.measurement.pk).exists()
    assert AnimalHealthCondition.objects.filter(pk=world.item.pk).exists()
    assert AnimalShare.objects.get(pk=world.share.pk).is_active
    assert Animal.objects.get().target_weight_status == TargetWeightStatus.UNVERIFIED


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_other_methods_are_rejected(world, method):
    client = client_for(world, "owner")
    for endpoint in ENDPOINTS:
        response = getattr(client, method)(endpoint.url(world))
        assert response.status_code == 405, endpoint.name
    assert Animal.objects.filter(pk=world.animal.pk).exists()


def test_csrf_is_enforced(world):
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.users["owner"])
    url = reverse("animals:delete", args=[world.animal.uuid])

    assert client.post(url).status_code == 403
    assert Animal.objects.filter(pk=world.animal.pk).exists()

    client.get(url)  # sets the CSRF cookie
    token = client.cookies["csrftoken"].value
    assert client.post(url, {"csrfmiddlewaretoken": token}).status_code == 302
    assert not Animal.objects.filter(pk=world.animal.pk).exists()


def test_csrf_is_enforced_for_vet_confirmation(world):
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.users["shared_vet"])
    url = reverse("animals:target_weight_confirm", args=[world.animal.uuid])

    assert client.post(url, {"target_weight_kg": "20"}).status_code == 403
    assert Animal.objects.get().target_weight_status == TargetWeightStatus.UNVERIFIED


def test_forms_contain_csrf_token(world):
    client = client_for(world, "owner")
    for name in ("edit", "delete", "measurement_add", "condition_add", "share_add", "detail"):
        endpoint = next(e for e in ENDPOINTS if e.name == name)
        content = client.get(endpoint.url(world)).content.decode()
        assert 'name="csrfmiddlewaretoken"' in content, name


# --- The permission function itself -----------------------------------------------------------


def test_allowed_actions_table():
    assert ALLOWED_ACTIONS[Relation.OWNER] == frozenset(Action) - {Action.CONFIRM_TARGET_WEIGHT}
    assert ALLOWED_ACTIONS[Relation.SHARED_VET] == {
        Action.VIEW,
        Action.ADD_MEASUREMENT,
        Action.CONFIRM_TARGET_WEIGHT,
    }


@pytest.mark.parametrize("action", list(Action))
@pytest.mark.parametrize("role", ROLES)
def test_get_animal_for(world, role, action):
    from django.contrib.auth.models import AnonymousUser

    user = world.users[role] or AnonymousUser()
    allowed = {
        "owner": ALLOWED_ACTIONS[Relation.OWNER],
        "shared_vet": ALLOWED_ACTIONS[Relation.SHARED_VET],
    }
    if role in allowed and action in allowed[role]:
        access = get_animal_for(user, world.animal.uuid, action)
        assert access.animal == world.animal
        assert access.is_owner is (role == "owner")
        assert access.can[action.name] is True
    elif role in allowed:
        with pytest.raises(PermissionDenied):
            get_animal_for(user, world.animal.uuid, action)
    else:
        with pytest.raises(Http404):
            get_animal_for(user, world.animal.uuid, action)


def test_vet_measurement_is_stored_as_vet_assessment(world):
    client = client_for(world, "shared_vet")
    client.post(
        reverse("animals:measurement_add", args=[world.animal.uuid]), post_data("measurement_add")
    )
    measurement = BodyMeasurement.objects.get(weight_kg=Decimal("21.5"))
    assert measurement.assessed_by == Assessor.VET
    assert measurement.created_by == world.users["shared_vet"]
