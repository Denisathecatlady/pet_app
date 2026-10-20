"""Signal receivers of the accounts app."""

from typing import Any

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.privacy import anonymise_admin_log


@receiver(post_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid="accounts_cleanup_user")
def remove_records_of_deleted_user(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Remove personal records that do not cascade from a deleted user.

    Runs for every deletion path (account deletion by the user, the admin, the purge
    of unactivated registrations): django-axes keeps login records by e-mail, not by
    foreign key, and the admin log keeps the e-mail as the object's text.
    """
    from axes.models import AccessAttempt, AccessFailureLog, AccessLog

    for model in (AccessLog, AccessAttempt, AccessFailureLog):
        model.objects.filter(username=instance.email).delete()
    anonymise_admin_log(instance)
