"""Shared fixtures of the Django tests (pytest-django, PostgreSQL, config.settings.test).

Log in with ``client.force_login`` in tests: django-axes requires a request in
``authenticate``, which ``client.login`` does not pass. Tests of the login form
itself post to the login view.
"""

from collections.abc import Callable

import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache

from accounts.models import User
from accounts.roles import Role
from tests.backend.helpers import PASSWORD


@pytest.fixture(autouse=True)
def _clear_cache():
    """The e-mail throttle lives in the cache; every test starts without it."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def make_user(db) -> Callable[..., User]:
    """Create an active user with ``PASSWORD``; keyword arguments override model fields."""

    def factory(email: str = "jana@example.cz", *, roles=(Role.OWNER,), **fields) -> User:
        password = fields.pop("password", PASSWORD)
        user = User.objects.create_user(email=email, password=password, **fields)
        for role in roles:
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    return factory


@pytest.fixture
def user(make_user) -> User:
    return make_user()


@pytest.fixture
def logged_in_client(client, user):
    client.force_login(user)
    return client


# --- Animals ----------------------------------------------------------------------------------


@pytest.fixture
def make_animal(db):
    """Create a validated animal of ``owner``; keyword arguments override the defaults."""
    from animals.models import ActivityLevel, Animal, Sex, Species

    def factory(owner: User, **fields) -> Animal:
        values = {
            "name": "Rex",
            "species": Species.DOG,
            "sex": Sex.MALE,
            "activity_level": ActivityLevel.MODERATE,
            **fields,
        }
        animal = Animal(owner=owner, **values)
        animal.full_clean()
        animal.save()
        return animal

    return factory


@pytest.fixture
def make_measurement(db):
    """Create a validated measurement; defaults: yesterday, 20 kg, assessed by the owner."""
    from datetime import timedelta
    from decimal import Decimal

    from django.utils import timezone

    from animals.models import Assessor, BodyMeasurement

    def factory(animal, **fields) -> BodyMeasurement:
        values = {
            "measured_on": timezone.localdate() - timedelta(days=1),
            "weight_kg": Decimal("20"),
            "assessed_by": Assessor.OWNER,
            "created_by": animal.owner,
            **fields,
        }
        measurement = BodyMeasurement(animal=animal, **values)
        measurement.full_clean()
        measurement.save()
        return measurement

    return factory


@pytest.fixture
def vet_user(make_user) -> User:
    return make_user("vet@example.cz", roles=(Role.VET,))


# --- Library of sources -----------------------------------------------------------------------


@pytest.fixture
def make_source(db):
    """Create a validated source; keyword arguments override the defaults.

    The defaults are an unverified original study about dogs. The migration has already
    loaded the real library into the test database; tests that need a known set of
    sources use ``empty_library`` first.
    """
    from itertools import count

    from catalog.models import (
        EvidenceLevel,
        ScientificSource,
        SourceType,
        SpeciesScope,
        VerificationLevel,
    )

    numbers = count(1)

    def factory(**fields) -> ScientificSource:
        number = next(numbers)
        values = {
            "citation_key": f"Test{number}",
            "title": f"Testovací zdroj {number}",
            "authors_or_org": "Novák J, Svoboda P",
            "year": 2020,
            "source_type": SourceType.ORIGINAL_STUDY,
            "evidence_level": EvidenceLevel.L3,
            "species_scope": SpeciesScope.DOG,
            "verification_level": VerificationLevel.NONE,
            **fields,
        }
        source = ScientificSource(**values)
        source.full_clean()
        source.save()
        return source

    return factory


@pytest.fixture
def empty_library(db):
    """Remove the sources the migration loaded, and their history (inside the test's
    transaction only)."""
    from catalog.models import ScientificSource

    ScientificSource.objects.all().delete()
    ScientificSource.history.all().delete()
