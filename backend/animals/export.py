"""GDPR export of the animals app (registered in ``AnimalsConfig.ready``).

Section ``animals`` of the personal data export (accounts/export.py):

* ``owned_animals``: every animal of the user with its measurements, health conditions,
  shares and the change history of each record;
* ``shares_received``: for a vet, which shares they received and when (without the
  owners' animal data, which belong to the owners).

Other people in the export (docs/12 §12.6): a reference to an account (who changed a
record, who wrote a measurement, who confirmed the target weight, who received a
share) is exported as an e-mail only when it is the user themself or a vet the animal
was shared with. Any other account, e.g. an administrator who edited the record in the
admin, appears only as a role (``STAFF_LABEL`` or ``OTHER_USER_LABEL``).

Every table, history tables included, is read once, so the number of queries does not
grow with the number of animals and records.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from django.db.models import Prefetch
from django.utils import timezone

from accounts.models import User

from .models import Animal, AnimalHealthCondition, AnimalShare, BodyMeasurement, HealthCondition

_HISTORY_TYPES = {"+": "created", "~": "changed", "-": "deleted"}

STAFF_LABEL: Final = "správce aplikace"
OTHER_USER_LABEL: Final = "jiný uživatel"

Person = Callable[[int | None], str | None]


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).isoformat()
    return value.isoformat()


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class _People:
    """Turn user ids into what the export may show, with one query for all of them."""

    def __init__(self, user: Any, user_ids: Iterable[int | None]) -> None:
        self.user = user
        wanted = {user_id for user_id in user_ids if user_id is not None}
        self._accounts = {
            pk: (email, is_staff)
            for pk, email, is_staff in User.objects.filter(pk__in=wanted).values_list(
                "pk", "email", "is_staff"
            )
        }

    def for_animal(self, animal: Animal) -> Person:
        """Return a resolver for records of ``animal`` (its vets may be named)."""
        vets = {share.vet_id for share in animal.shares.all()}

        def person(user_id: int | None) -> str | None:
            if user_id is None or user_id not in self._accounts:
                return None  # nobody, or a deleted account
            email, is_staff = self._accounts[user_id]
            if user_id == self.user.pk or user_id in vets:
                return email
            return STAFF_LABEL if is_staff else OTHER_USER_LABEL

        return person


def _animal_fields(animal: Any, person: Person) -> dict[str, Any]:
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
        "target_weight_confirmed_by": person(animal.target_weight_confirmed_by_id),
        "target_weight_confirmed_at": _iso(animal.target_weight_confirmed_at),
        "activity_level": animal.activity_level,
        "physiological_state": animal.physiological_state,
        "current_feeding": animal.current_feeding,
        "allergies": list(animal.allergies or []),
        "notes": animal.notes,
        "created_at": _iso(animal.created_at),
        "updated_at": _iso(animal.updated_at),
    }


def _measurement_fields(measurement: Any, person: Person) -> dict[str, Any]:
    return {
        "uuid": str(measurement.uuid),
        "measured_on": _iso(measurement.measured_on),
        "weight_kg": _decimal(measurement.weight_kg),
        "bcs": measurement.bcs,
        "mcs": measurement.mcs,
        "assessed_by": measurement.assessed_by,
        "note": measurement.note,
        "created_by": person(measurement.created_by_id),
        "created_at": _iso(measurement.created_at),
    }


def _condition_fields(codes: dict[int, str]) -> Callable[[Any, Person], dict[str, Any]]:
    def fields(item: Any, person: Person) -> dict[str, Any]:
        return {
            "condition": codes.get(item.condition_id),
            "diagnosed_by_vet": item.diagnosed_by_vet,
            "since": _iso(item.since),
            "vet_diet_restrictions": item.vet_diet_restrictions,
            "note": item.note,
        }

    return fields


def _history_by_object(records: Iterable[Any]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for record in records:
        grouped[record.id].append(record)
    return grouped


def _with_history(
    obj: Any,
    fields: Callable[[Any, Person], dict[str, Any]],
    history: dict[int, list[Any]],
    person: Person,
) -> dict[str, Any]:
    return {
        **fields(obj, person),
        "history": [
            {
                "changed_at": _iso(record.history_date),
                "change": _HISTORY_TYPES.get(record.history_type, record.history_type),
                "changed_by": person(record.history_user_id),
                "values": fields(record, person),
            }
            for record in history.get(obj.pk, [])
        ],
    }


def export_animals(user: Any) -> dict[str, Any]:
    """Return the animals section of the GDPR export of ``user`` (JSON-serialisable).

    Contains only the user's own animals and the shares the user received as a vet.
    Other accounts are named only as described in the module docstring.
    """
    animals = list(
        Animal.objects.filter(owner=user)
        .order_by("created_at", "id")
        .prefetch_related(
            Prefetch(
                "measurements",
                queryset=BodyMeasurement.objects.order_by("measured_on", "created_at", "id"),
            ),
            Prefetch("conditions", queryset=AnimalHealthCondition.objects.order_by("id")),
            Prefetch("shares", queryset=AnimalShare.objects.order_by("created_at", "id")),
        )
    )
    animal_ids = [animal.pk for animal in animals]
    order = ("history_date", "history_id")
    animal_history = _history_by_object(
        Animal.history.filter(id__in=animal_ids).order_by(*order)
    )
    measurement_history = _history_by_object(
        BodyMeasurement.history.filter(animal_id__in=animal_ids).order_by(*order)
    )
    condition_history = _history_by_object(
        AnimalHealthCondition.history.filter(animal_id__in=animal_ids).order_by(*order)
    )

    user_ids: list[int | None] = []
    for animal in animals:
        user_ids.append(animal.target_weight_confirmed_by_id)
        user_ids += [share.vet_id for share in animal.shares.all()]
        user_ids += [m.created_by_id for m in animal.measurements.all()]
    for records in animal_history.values():
        user_ids += [r.history_user_id for r in records]
        user_ids += [r.target_weight_confirmed_by_id for r in records]
    for records in measurement_history.values():
        user_ids += [r.history_user_id for r in records]
        user_ids += [r.created_by_id for r in records]
    for records in condition_history.values():
        user_ids += [r.history_user_id for r in records]
    people = _People(user, user_ids)
    condition_fields = _condition_fields(dict(HealthCondition.objects.values_list("id", "code")))

    owned = []
    for animal in animals:
        person = people.for_animal(animal)
        data = _with_history(animal, _animal_fields, animal_history, person)
        data["measurements"] = [
            _with_history(m, _measurement_fields, measurement_history, person)
            for m in animal.measurements.all()
        ]
        data["health_conditions"] = [
            _with_history(c, condition_fields, condition_history, person)
            for c in animal.conditions.all()
        ]
        data["shares"] = [
            {
                "uuid": str(share.uuid),
                "vet": person(share.vet_id),
                "created_at": _iso(share.created_at),
                "revoked_at": _iso(share.revoked_at),
            }
            for share in animal.shares.all()
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
