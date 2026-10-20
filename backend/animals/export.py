"""GDPR export of the animals app (registered in ``AnimalsConfig.ready``).

Section ``animals`` of the personal data export (accounts/export.py):

* ``owned_animals``: every animal of the user with its measurements, health conditions,
  shares and the change history of each record;
* ``shares_received``: for a vet, which shares they received and when (without the
  owners' animal data, which belong to the owners).
"""

from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone

from accounts.models import User

from .models import Animal, AnimalShare, HealthCondition

_HISTORY_TYPES = {"+": "created", "~": "changed", "-": "deleted"}


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).isoformat()
    return value.isoformat()


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class _Lookups:
    """Resolve user e-mails and condition codes by id, also for deleted rows (``None``)."""

    def __init__(self) -> None:
        self._emails: dict[int, str | None] = {}
        self._codes = dict(HealthCondition.objects.values_list("id", "code"))

    def email(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if user_id not in self._emails:
            self._emails[user_id] = (
                User.objects.filter(pk=user_id).values_list("email", flat=True).first()
            )
        return self._emails[user_id]

    def code(self, condition_id: int) -> str | None:
        return self._codes.get(condition_id)


def _animal_fields(animal: Any, lookups: _Lookups) -> dict[str, Any]:
    # ``animal`` is an Animal or one of its historical records (same attribute names).
    return {
        "uuid": str(animal.uuid),
        "name": animal.name,
        "species": animal.species,
        "sex": animal.sex,
        "neutered": animal.neutered,
        "birth_date": _iso(animal.birth_date),
        "birth_date_estimated": animal.birth_date_estimated,
        "breed": animal.breed,
        "size_category": animal.size_category,
        "expected_adult_weight_kg": _decimal(animal.expected_adult_weight_kg),
        "target_weight_kg": _decimal(animal.target_weight_kg),
        "target_weight_status": animal.target_weight_status,
        "target_weight_confirmed_by": lookups.email(animal.target_weight_confirmed_by_id),
        "target_weight_confirmed_at": _iso(animal.target_weight_confirmed_at),
        "activity_level": animal.activity_level,
        "physiological_state": animal.physiological_state,
        "current_feeding": animal.current_feeding,
        "allergies": list(animal.allergies or []),
        "notes": animal.notes,
        "created_at": _iso(animal.created_at),
        "updated_at": _iso(animal.updated_at),
    }


def _measurement_fields(measurement: Any, lookups: _Lookups) -> dict[str, Any]:
    return {
        "uuid": str(measurement.uuid),
        "measured_on": _iso(measurement.measured_on),
        "weight_kg": _decimal(measurement.weight_kg),
        "bcs": measurement.bcs,
        "mcs": measurement.mcs,
        "assessed_by": measurement.assessed_by,
        "note": measurement.note,
        "created_by": lookups.email(measurement.created_by_id),
        "created_at": _iso(measurement.created_at),
    }


def _condition_fields(item: Any, lookups: _Lookups) -> dict[str, Any]:
    return {
        "condition": lookups.code(item.condition_id),
        "diagnosed_by_vet": item.diagnosed_by_vet,
        "since": _iso(item.since),
        "vet_diet_restrictions": item.vet_diet_restrictions,
        "note": item.note,
    }


def _with_history(
    obj: Any, fields: Callable[[Any, _Lookups], dict[str, Any]], lookups: _Lookups
) -> dict[str, Any]:
    history: Iterable[Any] = obj.history.order_by("history_date", "history_id")
    return {
        **fields(obj, lookups),
        "history": [
            {
                "changed_at": _iso(record.history_date),
                "change": _HISTORY_TYPES.get(record.history_type, record.history_type),
                "changed_by": lookups.email(record.history_user_id),
                "values": fields(record, lookups),
            }
            for record in history
        ],
    }


def export_animals(user: Any) -> dict[str, Any]:
    """Return the animals section of the GDPR export of ``user`` (JSON-serialisable).

    Contains only the user's own animals and the shares the user received as a vet.
    """
    lookups = _Lookups()
    animals = Animal.objects.filter(owner=user).order_by("created_at", "id")
    owned = []
    for animal in animals:
        data = _with_history(animal, _animal_fields, lookups)
        data["measurements"] = [
            _with_history(m, _measurement_fields, lookups)
            for m in animal.measurements.order_by("measured_on", "created_at", "id")
        ]
        data["health_conditions"] = [
            _with_history(c, _condition_fields, lookups) for c in animal.conditions.order_by("id")
        ]
        data["shares"] = [
            {
                "uuid": str(share.uuid),
                "vet": lookups.email(share.vet_id),
                "created_at": _iso(share.created_at),
                "revoked_at": _iso(share.revoked_at),
            }
            for share in animal.shares.order_by("created_at", "id")
        ]
        owned.append(data)
    received = AnimalShare.objects.filter(vet=user).order_by("created_at", "id")
    return {
        "owned_animals": owned,
        "shares_received": [
            {
                "uuid": str(share.uuid),
                "animal_uuid": str(share.animal.uuid),
                "created_at": _iso(share.created_at),
                "revoked_at": _iso(share.revoked_at),
            }
            for share in received.select_related("animal")
        ],
    }
