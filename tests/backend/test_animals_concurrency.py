"""Target-weight confirmation and an owner's edit running at the same time (docs/05 §5.3).

A vet must never confirm a number they have not seen, and a confirmation must not be
lost by an owner's edit that started earlier. Both requests work on the animal row
locked with ``SELECT … FOR UPDATE``. These tests run the two requests in two threads
with their own database connections, so the lock is real. They use real transactions;
``serialized_rollback`` restores the catalog seeded by migrations afterwards.
"""

import threading
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.urls import reverse

from animals import services
from animals.forms import AnimalForm
from animals.models import Animal, AnimalShare, TargetWeightStatus

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)

TIMEOUT = 10  # seconds; only reached when the code under test is broken


def edit_data(**changes):
    data = {
        "name": "Rex",
        "species": "DOG",
        "sex": "MALE",
        "physiological_state": "MAINTENANCE",
        "activity_level": "MODERATE",
        "target_weight_kg": "20",
    }
    return {**data, **changes}


def start(target):
    """Run ``target`` in a thread with its own connection; return the thread and errors."""
    errors: list[BaseException] = []

    def run():
        try:
            target()
        except BaseException as error:  # noqa: BLE001  (reported to the test)
            errors.append(error)
        finally:
            connection.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread, errors


@pytest.fixture
def paused_edit(user, vet_user, make_animal, monkeypatch):
    """An owner's edit request that stops in form validation until ``release`` is set."""
    animal = make_animal(user, target_weight_kg=Decimal("20"))
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    validating, release = threading.Event(), threading.Event()
    clean = AnimalForm.clean

    def paused_clean(form):
        validating.set()
        release.wait(TIMEOUT)
        return clean(form)

    monkeypatch.setattr(AnimalForm, "clean", paused_clean)
    owner = Client()
    owner.force_login(user)

    def begin(**changes):
        url = reverse("animals:edit", args=[animal.uuid])
        thread, errors = start(lambda: owner.post(url, edit_data(**changes)))
        assert validating.wait(TIMEOUT)
        return thread, errors

    return animal, begin, release


def confirm_in_thread(animal, vet):
    stale = Animal.objects.get(pk=animal.pk)  # what the vet's page showed: 20 kg
    thread, errors = start(lambda: services.confirm_target_weight(stale, vet, Decimal("20")))
    thread.join(timeout=1)
    assert thread.is_alive(), "the confirmation must wait for the owner's edit in progress"
    return thread, errors


def test_confirmation_during_an_edit_is_not_lost(paused_edit, vet_user):
    animal, begin, release = paused_edit
    edit, edit_errors = begin(notes="nová poznámka")  # target weight unchanged
    confirmation, confirm_errors = confirm_in_thread(animal, vet_user)

    release.set()
    edit.join(TIMEOUT)
    confirmation.join(TIMEOUT)

    assert edit_errors == [] and confirm_errors == []
    animal.refresh_from_db()
    assert animal.notes == "nová poznámka"
    assert animal.target_weight_status == TargetWeightStatus.VET_CONFIRMED
    assert animal.target_weight_confirmed_by == vet_user


def test_vet_cannot_confirm_a_value_changed_during_the_confirmation(paused_edit, vet_user):
    animal, begin, release = paused_edit
    edit, edit_errors = begin(target_weight_kg="25")
    confirmation, confirm_errors = confirm_in_thread(animal, vet_user)

    release.set()
    edit.join(TIMEOUT)
    confirmation.join(TIMEOUT)

    assert edit_errors == []
    assert len(confirm_errors) == 1 and isinstance(confirm_errors[0], ValidationError)
    assert confirm_errors[0].code == "changed"
    animal.refresh_from_db()
    assert animal.target_weight_kg == Decimal("25")
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
