"""Object permissions for animals (docs/07 §7.6 and §7.7).

Every view that works with an animal resolves it through :func:`get_animal_for`.
The rules:

* the owner may do everything except confirming the target weight (a vet's task);
* a user in the ``vet`` group with an active share of the animal may view it, add a
  measurement (stored as assessed by a vet) and confirm the target weight;
* nobody else learns that the animal exists: they get HTTP 404, not 403.
"""

import enum
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from django.core.exceptions import PermissionDenied
from django.http import Http404

from accounts.roles import Role

from .models import Animal, AnimalShare


class Action(enum.Enum):
    VIEW = "VIEW"
    EDIT = "EDIT"
    DELETE = "DELETE"
    ADD_MEASUREMENT = "ADD_MEASUREMENT"
    CONFIRM_TARGET_WEIGHT = "CONFIRM_TARGET_WEIGHT"
    MANAGE_CONDITIONS = "MANAGE_CONDITIONS"
    MANAGE_SHARES = "MANAGE_SHARES"


class Relation(enum.Enum):
    OWNER = "OWNER"
    SHARED_VET = "SHARED_VET"


ALLOWED_ACTIONS: Final = MappingProxyType(
    {
        Relation.OWNER: frozenset(Action) - {Action.CONFIRM_TARGET_WEIGHT},
        Relation.SHARED_VET: frozenset(
            {Action.VIEW, Action.ADD_MEASUREMENT, Action.CONFIRM_TARGET_WEIGHT}
        ),
    }
)


@dataclass(frozen=True)
class AnimalAccess:
    """An animal together with the request user's relation to it."""

    animal: Animal
    relation: Relation
    can: MappingProxyType = field(init=False, repr=False)

    def __post_init__(self) -> None:
        allowed = ALLOWED_ACTIONS[self.relation]
        # ``{% if access.can.EDIT %}`` in templates.
        object.__setattr__(
            self, "can", MappingProxyType({action.name: action in allowed for action in Action})
        )

    @property
    def is_owner(self) -> bool:
        return self.relation is Relation.OWNER

    def allows(self, action: Action) -> bool:
        return action in ALLOWED_ACTIONS[self.relation]


def relation_to(user: Any, animal: Animal) -> Relation | None:
    """Return how ``user`` relates to ``animal``, or ``None`` if they may not see it.

    Inputs: any user (anonymous users get ``None``) and an animal. A vet needs both
    the ``vet`` group and an active share; a revoked share or a removed role ends access.
    """
    if not getattr(user, "is_authenticated", False):
        return None
    if animal.owner_id == user.pk:
        return Relation.OWNER
    if (
        user.has_role(Role.VET)
        and AnimalShare.objects.active().filter(animal=animal, vet=user).exists()
    ):
        return Relation.SHARED_VET
    return None


def get_animal_for(user: Any, animal_uuid: uuid.UUID | str, action: Action) -> AnimalAccess:
    """Resolve the animal ``animal_uuid`` for ``user`` and check ``action``.

    Output: :class:`AnimalAccess` with the animal and the relation.

    Raises:
        Http404: the animal does not exist or ``user`` may not see it at all
            (anonymous, another owner, a vet without an active share).
        PermissionDenied: ``user`` may see the animal but not perform ``action``.
    """
    animal = (
        Animal.objects.select_related("owner", "target_weight_confirmed_by")
        .filter(uuid=animal_uuid)
        .first()
    )
    relation = relation_to(user, animal) if animal is not None else None
    if animal is None or relation is None:
        raise Http404("Zvíře nenalezeno.")
    access = AnimalAccess(animal, relation)
    if not access.allows(action):
        raise PermissionDenied("K této akci nemáte oprávnění.")
    return access
