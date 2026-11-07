"""Signal receivers of the accounts app."""

from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete
from django.dispatch import receiver

from core.privacy import anonymise_admin_log

from .session_policy import start_session
from .staff import refresh_staff_flags


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


# --- User.is_staff follows the roles (docs/14 §14.2) -------------------------------------


@receiver(
    m2m_changed,
    sender=get_user_model().groups.through,
    dispatch_uid="accounts_derive_is_staff_from_groups",
)
def derive_staff_after_group_change(
    sender: Any, instance: Any, action: str, reverse: bool, pk_set: Any, **kwargs: Any
) -> None:
    """Recompute ``is_staff`` after roles are added, removed or cleared.

    Works for both directions of the relation: ``user.groups`` (``instance`` is the user)
    and ``group.user_set`` (``instance`` is the group, ``pk_set`` the users). Clearing a
    group's members passes no ``pk_set``, so the members are remembered before the clear.
    """
    if action == "pre_clear" and reverse:
        instance._staff_refresh_user_ids = list(instance.user_set.values_list("pk", flat=True))
        return
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    if not reverse:
        refresh_staff_flags([instance.pk])
        instance.refresh_from_db(fields=["is_staff"])  # the object in hand shows it too
        return
    if action == "post_clear":
        user_ids = instance.__dict__.pop("_staff_refresh_user_ids", [])
    else:
        user_ids = list(pk_set or [])
    refresh_staff_flags(user_ids)


@receiver(pre_delete, sender=Group, dispatch_uid="accounts_remember_members_of_deleted_group")
def remember_members_of_deleted_group(sender: Any, instance: Group, **kwargs: Any) -> None:
    """Deleting a group removes its members without ``m2m_changed``: remember who they were."""
    instance._staff_refresh_user_ids = list(instance.user_set.values_list("pk", flat=True))


@receiver(post_delete, sender=Group, dispatch_uid="accounts_demote_members_of_deleted_group")
def demote_members_of_deleted_group(sender: Any, instance: Group, **kwargs: Any) -> None:
    refresh_staff_flags(instance.__dict__.pop("_staff_refresh_user_ids", []))


@receiver(post_save, sender=Group, dispatch_uid="accounts_refresh_staff_after_group_rename")
def refresh_staff_after_group_save(
    sender: Any, instance: Group, created: bool, **kwargs: Any
) -> None:
    """A renamed group may stop (or start) being a staff role for its members."""
    if not created:
        refresh_staff_flags(instance.user_set.values_list("pk", flat=True))


# --- Staff session policy (docs/14 §14.5) ------------------------------------------------


@receiver(user_logged_in, dispatch_uid="accounts_start_session_clock")
def start_session_clock(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """Remember when this session began, for the idle and absolute limits of staff."""
    start_session(request)
