"""Signal receivers of the animals app."""

from typing import Any

from django.conf import settings
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Animal


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid="animals_reset_confirmations")
def reset_confirmations_of_deleted_user(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Before a user is deleted, make target weights they confirmed orientational again.

    A confirmation must name the vet who gave it (docs/05 §5.3); once the vet's account
    is gone it can no longer be traced, so the safe state is ``UNVERIFIED``. Saving each
    animal also records the change in its history.
    """
    # Includes the user's own animals: they are deleted right after, but the SET_NULL
    # update of ``target_weight_confirmed_by`` runs first and must not break the
    # confirmation constraint.
    for animal in Animal.objects.filter(target_weight_confirmed_by=instance):
        animal.reset_target_weight_confirmation()
        animal.save(
            update_fields=[
                "target_weight_status",
                "target_weight_confirmed_by",
                "target_weight_confirmed_at",
                "updated_at",
            ]
        )
