"""Who may open which page of the administration: every role against every kind of page
(docs/14 §14.3). Anonymous visitors and non-staff users are sent to sign in (302), staff without
the permission get 403, the rest 200."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import DataSubjectRequest, User, VetVerificationRequest
from accounts.roles import Role
from animals.models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    BodyMeasurement,
    HealthCondition,
)
from tests.backend.helpers import log_in_verified

pytestmark = pytest.mark.django_db

SUPPORT, CURATOR, REVIEWER = Role.SUPPORT_ADMIN.value, Role.DATA_CURATOR.value, "nutrition_reviewer"
ROLES = ["anonymous", "owner", "vet", SUPPORT, CURATOR, REVIEWER, "superuser"]
STAFF = {SUPPORT, CURATOR, REVIEWER, "superuser"}


@pytest.fixture
def world(make_user, make_animal, make_measurement, make_source, vet_user):
    """One record of every kind the administration shows."""
    ordinary = make_user("ordinary@example.cz")
    staff_member = make_user("colleague@example.cz", roles=(Role.DATA_CURATOR,))
    animal = make_animal(ordinary)
    condition = HealthCondition.objects.get(code="CKD")
    return {
        "ordinary": ordinary,
        "staff_member": staff_member,
        "animal": animal,
        "measurement": make_measurement(animal),
        "condition": condition,
        "animal_condition": AnimalHealthCondition.objects.create(
            animal=animal, condition=condition
        ),
        "share": AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=ordinary),
        "source": make_source(),
        "vet_request": VetVerificationRequest.objects.create(user=ordinary, workplace="Klinika"),
        "subject_request": DataSubjectRequest.objects.create(
            request_type="ACCESS", received_via="EMAIL", subject_label="účet č. 1", user=ordinary
        ),
    }


def attempt():
    from axes.models import AccessAttempt

    return AccessAttempt.objects.create(
        username="someone@example.cz",
        ip_address="10.0.0.9",
        user_agent="x",
        failures_since_start=5,
    )


@pytest.fixture
def clients(make_user, superuser):
    def build(role: str) -> Client:
        client = Client()
        if role == "anonymous":
            return client
        user = {
            "superuser": superuser,
            "owner": lambda: make_user("o@example.cz", roles=(Role.OWNER,)),
            "vet": lambda: make_user("v@example.cz", roles=(Role.VET,)),
        }.get(role)
        user = user() if callable(user) else user or make_user(f"{role}@example.cz", roles=(role,))
        log_in_verified(client, user)
        return client

    return build


def expected(role: str, allowed: set[str]) -> int:
    """200 for an allowed role, 403 for staff without the permission, 302 to sign in otherwise."""
    if role in allowed:
        return 200
    return 403 if role in STAFF else 302


def page(name: str, *args) -> str:
    return reverse(name, args=args)


# (label, url builder, roles that get 200). A "hidden" page answers 302 to staff as well.
ALL_STAFF = STAFF
PAGES = [
    ("index", lambda w: page("admin:index"), ALL_STAFF),
    ("users: list", lambda w: page("admin:accounts_user_changelist"), {SUPPORT, "superuser"}),
    (
        "users: change an ordinary user",
        lambda w: page("admin:accounts_user_change", w["ordinary"].pk),
        {SUPPORT, "superuser"},
    ),
    (
        "users: history is not offered",
        lambda w: page("admin:accounts_user_history", w["ordinary"].pk),
        {SUPPORT, "superuser"},
    ),
    ("users: add", lambda w: page("admin:accounts_user_add"), {"superuser"}),
    (
        "users: delete",
        lambda w: page("admin:accounts_user_delete", w["ordinary"].pk),
        {"superuser"},
    ),
    ("groups: list", lambda w: page("admin:auth_group_changelist"), {"superuser"}),
    ("animals: list", lambda w: page("admin:animals_animal_changelist"), {"superuser"}),
    (
        "animals: change",
        lambda w: page("admin:animals_animal_change", w["animal"].pk),
        {"superuser"},
    ),
    (
        "animals: history",
        lambda w: page("admin:animals_animal_history", w["animal"].pk),
        {"superuser"},
    ),
    ("animals: add", lambda w: page("admin:animals_animal_add"), {"superuser"}),
    (
        "measurements: list",
        lambda w: page("admin:animals_bodymeasurement_changelist"),
        {"superuser"},
    ),
    (
        "measurements: change",
        lambda w: page("admin:animals_bodymeasurement_change", w["measurement"].pk),
        {"superuser"},
    ),
    (
        "animal conditions: list",
        lambda w: page("admin:animals_animalhealthcondition_changelist"),
        {"superuser"},
    ),
    ("shares: list", lambda w: page("admin:animals_animalshare_changelist"), {"superuser"}),
    (
        "shares: change",
        lambda w: page("admin:animals_animalshare_change", w["share"].pk),
        {"superuser"},
    ),
    (
        "health conditions (codebook): list",
        lambda w: page("admin:animals_healthcondition_changelist"),
        {REVIEWER, "superuser"},
    ),
    (
        "health conditions (codebook): change",
        lambda w: page("admin:animals_healthcondition_change", w["condition"].pk),
        {REVIEWER, "superuser"},
    ),
    (
        "health conditions (codebook): add",
        lambda w: page("admin:animals_healthcondition_add"),
        {"superuser"},
    ),
    (
        "health conditions (codebook): delete",
        lambda w: page("admin:animals_healthcondition_delete", w["condition"].pk),
        {"superuser"},
    ),
    (
        "sources: list",
        lambda w: page("admin:catalog_scientificsource_changelist"),
        {CURATOR, REVIEWER, "superuser"},
    ),
    (
        "sources: view or change",
        lambda w: page("admin:catalog_scientificsource_change", w["source"].pk),
        {CURATOR, REVIEWER, "superuser"},
    ),
    (
        "sources: history",
        lambda w: page("admin:catalog_scientificsource_history", w["source"].pk),
        {CURATOR, REVIEWER, "superuser"},
    ),
    (
        "sources: add",
        lambda w: page("admin:catalog_scientificsource_add"),
        {CURATOR, "superuser"},
    ),
    (
        "sources: delete",
        lambda w: page("admin:catalog_scientificsource_delete", w["source"].pk),
        {"superuser"},
    ),
    (
        "failed sign-in counters: list",
        lambda w: page("admin:axes_accessattempt_changelist"),
        {SUPPORT, "superuser"},
    ),
    (
        "failed sign-in counters: view",
        lambda w: page("admin:axes_accessattempt_change", attempt().pk),
        {SUPPORT, "superuser"},
    ),
    (
        "failed sign-in counters: delete (unlock)",
        lambda w: page("admin:axes_accessattempt_delete", attempt().pk),
        {SUPPORT, "superuser"},
    ),
    (
        "vet verification requests: list",
        lambda w: page("admin:accounts_vetverificationrequest_changelist"),
        {SUPPORT, "superuser"},
    ),
    (
        "vet verification requests: view",
        lambda w: page("admin:accounts_vetverificationrequest_change", w["vet_request"].pk),
        {SUPPORT, "superuser"},
    ),
    (
        "vet verification requests: history",
        lambda w: page("admin:accounts_vetverificationrequest_history", w["vet_request"].pk),
        {SUPPORT, "superuser"},
    ),
    (
        "vet verification requests: add",
        lambda w: page("admin:accounts_vetverificationrequest_add"),
        set(),  # (nobody: requests come from the users)
    ),
    (
        "vet verification requests: delete",
        lambda w: page("admin:accounts_vetverificationrequest_delete", w["vet_request"].pk),
        {"superuser"},
    ),
    (
        "data subject requests: list",
        lambda w: page("admin:accounts_datasubjectrequest_changelist"),
        {SUPPORT, "superuser"},
    ),
    (
        "data subject requests: change",
        lambda w: page("admin:accounts_datasubjectrequest_change", w["subject_request"].pk),
        {SUPPORT, "superuser"},
    ),
    (
        "data subject requests: history",
        lambda w: page("admin:accounts_datasubjectrequest_history", w["subject_request"].pk),
        {SUPPORT, "superuser"},
    ),
    (
        "data subject requests: add",
        lambda w: page("admin:accounts_datasubjectrequest_add"),
        {SUPPORT, "superuser"},
    ),
    (
        "data subject requests: delete",
        lambda w: page("admin:accounts_datasubjectrequest_delete", w["subject_request"].pk),
        {"superuser"},
    ),
    ("sign-in log: list", lambda w: page("admin:axes_accesslog_changelist"), {"superuser"}),
    (
        "failed sign-in log: list",
        lambda w: page("admin:axes_accessfailurelog_changelist"),
        {"superuser"},
    ),
    (
        "admin access log: list",
        lambda w: page("admin:backoffice_adminaccesslog_changelist"),
        {"superuser"},
    ),
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("label", "url", "allowed"), PAGES, ids=[p[0] for p in PAGES])
def test_role_by_page_matrix(clients, world, role, label, url, allowed):
    response = clients(role).get(url(world))

    assert response.status_code == expected(role, allowed), (role, label)


@pytest.mark.parametrize("role", ROLES)
def test_a_staff_member_cannot_reach_the_change_page_of_a_staff_member(clients, world, role):
    """Staff users are invisible to everybody but superusers (redirect as for a missing record)."""
    response = clients(role).get(page("admin:accounts_user_change", world["staff_member"].pk))

    if role == "superuser":
        assert response.status_code == 200
    elif role == SUPPORT:
        assert response.status_code == 302 and response["Location"] == page("admin:index")
    else:
        assert response.status_code == expected(role, set())


@pytest.mark.parametrize("role", sorted(STAFF))
def test_the_index_lists_only_what_the_role_may_open(clients, world, role):
    content = clients(role).get(page("admin:index")).content.decode()

    for name, allowed in {
        "accounts/user/": {SUPPORT, "superuser"},
        "animals/animal/": {"superuser"},
        "animals/healthcondition/": {REVIEWER, "superuser"},
        "catalog/scientificsource/": {CURATOR, REVIEWER, "superuser"},
        "axes/accessattempt/": {SUPPORT, "superuser"},
        "accounts/vetverificationrequest/": {SUPPORT, "superuser"},
        "accounts/datasubjectrequest/": {SUPPORT, "superuser"},
        "backoffice/adminaccesslog/": {"superuser"},
    }.items():
        assert (f"/{name}" in content) == (role in allowed), (role, name)


# --- Writing: the same matrix for POST ------------------------------------------------------


def source_data(source, **changes):
    data = {
        "citation_key": source.citation_key,
        "title": source.title,
        "authors_or_org": source.authors_or_org,
        "year": source.year,
        "source_type": source.source_type,
        "evidence_level": source.evidence_level,
        "species_scope": source.species_scope,
        "verification_level": "NONE",
    }
    return {**data, **changes}


@pytest.mark.parametrize(
    ("role", "status"),
    [
        (SUPPORT, 403),
        (CURATOR, 302),
        (REVIEWER, 403),
        ("superuser", 302),
        ("owner", 302),
        ("anonymous", 302),
    ],
)
def test_changing_a_source(clients, world, role, status):
    source = world["source"]
    url = page("admin:catalog_scientificsource_change", source.pk)

    response = clients(role).post(url, source_data(source, title="Nový název"))

    assert response.status_code == status, role
    source.refresh_from_db()
    assert (source.title == "Nový název") == (status == 302 and role in {CURATOR, "superuser"})


@pytest.mark.parametrize(
    ("role", "status"),
    [(SUPPORT, 403), (CURATOR, 403), (REVIEWER, 302), ("superuser", 302)],
)
def test_changing_a_health_condition(clients, world, role, status):
    condition = world["condition"]
    url = page("admin:animals_healthcondition_change", condition.pk)
    data = {"code": condition.code, "name_cs": "Nový název", "mode": condition.mode}

    response = clients(role).post(url, data)

    assert response.status_code == status, role
    condition.refresh_from_db()
    assert (condition.name_cs == "Nový název") == (status == 302)


@pytest.mark.parametrize(
    ("role", "status"),
    [(SUPPORT, 302), (CURATOR, 403), (REVIEWER, 403), ("superuser", 302)],
)
def test_unlocking_a_sign_in(clients, world, role, status):
    counter = attempt()
    url = page("admin:axes_accessattempt_delete", counter.pk)

    response = clients(role).post(url, {"post": "yes"})

    assert response.status_code == status, role
    from axes.models import AccessAttempt

    assert AccessAttempt.objects.filter(pk=counter.pk).exists() == (status != 302)


@pytest.mark.parametrize("role", [SUPPORT, CURATOR, REVIEWER])
def test_staff_roles_cannot_delete_records_of_personal_data(clients, world, role):
    """No staff role may delete a user, animal, measurement, condition or share."""
    client = clients(role)
    for name, obj in [
        ("accounts_user", world["ordinary"]),
        ("animals_animal", world["animal"]),
        ("animals_bodymeasurement", world["measurement"]),
        ("animals_animalhealthcondition", world["animal_condition"]),
        ("animals_animalshare", world["share"]),
    ]:
        response = client.post(page(f"admin:{name}_delete", obj.pk), {"post": "yes"})
        assert response.status_code in (403, 302), (role, name)
    assert User.objects.filter(pk=world["ordinary"].pk).exists()
    assert Animal.objects.filter(pk=world["animal"].pk).exists()
    assert BodyMeasurement.objects.filter(pk=world["measurement"].pk).exists()
    assert AnimalShare.objects.filter(pk=world["share"].pk).exists()
    assert AnimalHealthCondition.objects.filter(pk=world["animal_condition"].pk).exists()
