"""Signal receivers of the animals app."""

from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import m2m_changed, post_delete, pre_delete
from django.dispatch import receiver

from accounts.roles import Role
from core.privacy import anonymise_admin_log

from .models import Animal, AnimalHealthCondition, AnimalShare, BodyMeasurement, TargetWeightStatus

_CONFIRMATION_UPDATE = [
    "target_weight_status",
    "target_weight_confirmed_by",
    "target_weight_confirmed_at",
    "updated_at",
]


def _reset_confirmations(animals: Any) -> None:
    # Saving each animal also records the change in its history.
    for animal in animals:
        animal.reset_target_weight_confirmation()
        animal.save(update_fields=_CONFIRMATION_UPDATE)


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid="animals_reset_confirmations")
def reset_confirmations_of_deleted_user(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Before a user is deleted, make target weights they confirmed orientational again.

    A confirmation must name the vet who gave it (docs/05 §5.3); once the vet's account
    is gone it can no longer be traced, so the safe state is ``UNVERIFIED``.
    """
    # Includes the user's own animals: they are deleted right after, but the SET_NULL
    # update of ``target_weight_confirmed_by`` runs first and must not break the
    # confirmation constraint.
    _reset_confirmations(Animal.objects.filter(target_weight_confirmed_by=instance))


@receiver(
    m2m_changed,
    sender=get_user_model().groups.through,
    dispatch_uid="animals_reset_confirmations_without_vet_role",
)
def reset_confirmations_without_vet_role(sender: Any, action: str, **kwargs: Any) -> None:
    """After roles are removed, cancel confirmations by accounts no longer in ``vet``.

    Removing the vet role is how an administrator revokes a wrongly assigned or former
    vet (README); their confirmations then no longer stand for a vet's assessment.
    Works for both directions of the relation (``user.groups`` and ``group.user_set``).
    """
    if action not in ("post_remove", "post_clear"):
        return
    _reset_confirmations(
        Animal.objects.filter(target_weight_status=TargetWeightStatus.VET_CONFIRMED).exclude(
            target_weight_confirmed_by__groups__name=Role.VET
        )
    )


@receiver(post_delete, sender=Animal, dispatch_uid="animals_admin_log_animal")
@receiver(post_delete, sender=BodyMeasurement, dispatch_uid="animals_admin_log_measurement")
@receiver(post_delete, sender=AnimalHealthCondition, dispatch_uid="animals_admin_log_condition")
@receiver(post_delete, sender=AnimalShare, dispatch_uid="animals_admin_log_share")
def anonymise_admin_log_of_deleted_record(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Remove the text of a deleted user record (e.g. the animal's name) from the admin log."""
    anonymise_admin_log(instance)
