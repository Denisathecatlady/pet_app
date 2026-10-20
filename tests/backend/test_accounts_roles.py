"""Role groups created by the data migration ``accounts.0002_create_roles``."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import Group

from accounts.roles import ROLE_LABELS, Role

pytestmark = pytest.mark.django_db

migration = importlib.import_module("accounts.migrations.0002_create_roles")


def test_migration_created_all_role_groups():
    names = set(Group.objects.values_list("name", flat=True))
    assert {role.value for role in Role} <= names


def test_migration_names_match_role_constants():
    assert set(migration.ROLE_NAMES) == {role.value for role in Role}


def test_every_role_has_a_czech_label():
    assert set(ROLE_LABELS) == {role.value for role in Role}
    assert ROLE_LABELS["owner"] == "Majitel zvířat"
    assert ROLE_LABELS["vet"] == "Veterinární lékař"
    assert all(label.strip() for label in ROLE_LABELS.values())


def test_migration_is_idempotent_and_reversible():
    migration.create_roles(apps, None)
    assert Group.objects.filter(name__in=migration.ROLE_NAMES).count() == 4

    migration.delete_roles(apps, None)
    assert not Group.objects.filter(name__in=migration.ROLE_NAMES).exists()

    migration.create_roles(apps, None)
    assert Group.objects.filter(name__in=migration.ROLE_NAMES).count() == 4
