"""Signal receivers of the catalog app."""

from typing import Any

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ScientificSource


@receiver(
    post_delete,
    sender=settings.AUTH_USER_MODEL,
    dispatch_uid="catalog_clear_verifier_in_history",
)
def clear_verifier_in_history(sender: Any, instance: Any, **kwargs: Any) -> None:
    """After an account is deleted, forget it as ``verified_by`` in the history of sources.

    The live row is handled by ``on_delete=SET_NULL``. The history rows keep the id in a
    column without a foreign key constraint; an id of a deleted account is a leftover
    that would still tie old versions of a source to that person (GDPR art. 17), so it
    is cleared. ``history_user`` is a real foreign key and is set to NULL by Django.
    """
    ScientificSource.history.model.objects.filter(verified_by_id=instance.pk).update(
        verified_by=None
    )
