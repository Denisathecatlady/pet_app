"""Role groups created by the data migrations ``accounts.0002_create_roles`` and
``accounts.0003_support_admin_and_derived_staff``."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import Group

from accounts.roles import ROLE_LABELS, STAFF_ROLES, Role

pytestmark = pytest.mark.django_db

first = importlib.import_module("accounts.migrations.0002_create_roles")
second = importlib.import_module("accounts.migrations.0003_support_admin_and_derived_staff")


def test_migrations_created_all_role_groups():
    names = set(Group.objects.values_list("name", flat=True))
    assert {role.value for role in Role} <= names


def test_migration_names_match_role_constants():
    assert set(first.ROLE_NAMES) | {second.SUPPORT_ADMIN} == {role.value for role in Role}
    assert set(second.STAFF_ROLE_NAMES) == set(STAFF_ROLES)


def test_staff_roles_are_exactly_the_three_administration_roles():
    assert {"data_curator", "nutrition_reviewer", "support_admin"} == STAFF_ROLES
    assert not {Role.OWNER.value, Role.VET.value} & STAFF_ROLES


def test_every_role_has_a_czech_label():
    assert set(ROLE_LABELS) == {role.value for role in Role}
    assert ROLE_LABELS["owner"] == "Majitel zvířat"
    assert ROLE_LABELS["vet"] == "Veterinární lékař"
    assert ROLE_LABELS["support_admin"] == "Správce uživatelů"
    assert all(label.strip() for label in ROLE_LABELS.values())


def test_first_migration_is_idempotent_and_reversible():
    first.create_roles(apps, None)
    assert Group.objects.filter(name__in=first.ROLE_NAMES).count() == 4

    first.delete_roles(apps, None)
    assert not Group.objects.filter(name__in=first.ROLE_NAMES).exists()

    first.create_roles(apps, None)
    assert Group.objects.filter(name__in=first.ROLE_NAMES).count() == 4


def test_second_migration_creates_the_group_and_derives_staff_idempotently(make_user):
    Group.objects.filter(name=second.SUPPORT_ADMIN).delete()
    curator = make_user("curator@example.cz", roles=(Role.DATA_CURATOR,))
    owner = make_user("owner@example.cz")
    superuser = make_user("root@example.cz", roles=(), is_superuser=True)
    # State before the migration: the flags are as an old installation left them.
    type(curator).objects.filter(pk=curator.pk).update(is_staff=False)
    type(owner).objects.filter(pk=owner.pk).update(is_staff=True)  # set by hand, no role
    type(superuser).objects.filter(pk=superuser.pk).update(is_staff=False)

    for _ in range(2):  # the second run changes nothing
        second.create_support_admin_and_derive_staff(apps, None)
        flags = dict(type(curator).objects.values_list("email", "is_staff"))
        assert flags == {
            "curator@example.cz": True,
            "owner@example.cz": False,
            "root@example.cz": True,
        }
        assert Group.objects.filter(name=second.SUPPORT_ADMIN).count() == 1

    second.delete_support_admin(apps, None)
    assert not Group.objects.filter(name=second.SUPPORT_ADMIN).exists()
