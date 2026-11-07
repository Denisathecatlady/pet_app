"""Admin of third-party models that need the back office's rules (docs/14 §14.7).

Called once by ``BarfAdminConfig.ready`` after every app's admin module was imported:

* django-axes registers admins that show the form data of failed requests, are in English and
  do not record accesses. They are replaced by admins that use the access-log mixin, show no
  submitted data and are in Czech. The list of failed-sign-in counters says which accounts are
  locked now and unlocks them with axes' own reset function (action *Odemknout*, docs/14
  §14.13); deleting a counter unlocks the account too, so a support person needs
  ``axes.delete_accessattempt`` (``ROLE_PERMISSIONS``) and both are recorded as ``UNLOCK``.
* django-otp registers admins of its devices, which show secret keys and recovery codes. They
  are removed: two-factor authentication is managed on the account page and, for loss
  recovery, by the superuser action *Zrušit dvoufázové ověření* and ``manage.py reset_2fa``.
"""

from typing import Any

from datetime import datetime

from axes.conf import settings as axes_settings
from axes.helpers import get_cool_off
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from axes.utils import reset as axes_reset
from django.contrib import admin, messages
from django.db.models import Model, OuterRef, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import HttpRequest
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from .access_log import AccessLoggedAdminMixin
from .admin_tools import Tone, status_badge
from .models import AdminAccessAction

# Czech names for the English models and fields of django-axes (they appear in the lists,
# the forms and the index of the administration).
MODEL_NAMES = {
    AccessAttempt: ("počítadlo neúspěšných přihlášení", "počítadla neúspěšných přihlášení"),
    AccessLog: ("záznam o přihlášení", "záznamy o přihlášení"),
    AccessFailureLog: ("záznam o neúspěšném přihlášení", "záznamy o neúspěšných přihlášeních"),
}
FIELD_LABELS = {
    "attempt_time": "čas",
    "logout_time": "čas odhlášení",
    "username": "e-mail",
    "ip_address": "IP adresa",
    "user_agent": "prohlížeč",
    "http_accept": "hlavička Accept",
    "path_info": "adresa",
    "failures_since_start": "neúspěšných pokusů",
    "locked_out": "zamčeno",
}
# The same field means something else in the list of counters: the time of the last failure.
MODEL_FIELD_LABELS = {AccessAttempt: {"attempt_time": "poslední pokus"}}
APP_NAME = "Zámky přihlášení"


def lock_threshold() -> datetime | None:
    """Return the moment before which a failed attempt no longer counts, or ``None`` if never.

    Axes counts the failures of an account and address newer than ``now - cool-off`` and locks
    when they reach the limit (``AxesDatabaseHandler.get_user_attempts``); with no cool-off
    (``AXES_COOLOFF_TIME = None``) nothing ever expires.
    """
    cool_off = get_cool_off()
    return None if cool_off is None else timezone.now() - cool_off


class LockedOutFilter(admin.SimpleListFilter):
    """Counters of accounts that are locked out now (``locked_failures`` reaches the limit)."""

    title = "zamčeno"
    parameter_name = "zamceno"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:
        return [("ano", "ano"), ("ne", "ne")]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        limit = axes_settings.AXES_FAILURE_LIMIT
        if self.value() == "ano":
            return queryset.filter(locked_failures__gte=limit)
        if self.value() == "ne":
            return queryset.filter(locked_failures__lt=limit)
        return queryset


class _ReadOnlyAxesAdmin(AccessLoggedAdminMixin, admin.ModelAdmin):
    """Records of django-axes: shown, never added or edited (deleting is a permission)."""

    date_hierarchy = "attempt_time"
    fields: tuple[str, ...] = ()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def get_readonly_fields(self, request: HttpRequest, obj: Model | None = None) -> list[str]:
        return list(self.fields)


class AccessAttemptAdmin(_ReadOnlyAxesAdmin):
    """Counters of failed sign-ins; an account is locked while its failures reach the limit.

    A counter belongs to an e-mail, an address and a browser; axes locks an e-mail on an
    address when the failures of all its counters within the cool-off add up to
    ``AXES_FAILURE_LIMIT``, so the column *zamčeno* sums them (``locked_failures``) instead of
    reading one row. The submitted form data that axes keeps (``get_data``, ``post_data``) is
    not shown: a mistyped password may be in it. *Odemknout* removes the counters of the
    selected e-mails with axes' own ``reset`` and is recorded as ``UNLOCK``, like deleting a
    counter.
    """

    access_delete_action = AdminAccessAction.UNLOCK
    list_display = ("username", "locked", "ip_address", "failures_since_start", "attempt_time")
    list_filter = (LockedOutFilter, "attempt_time")
    search_fields = ("username", "ip_address")
    fields = (
        "username",
        "ip_address",
        "user_agent",
        "path_info",
        "failures_since_start",
        "attempt_time",
        "locked",
    )
    actions = ["unlock_selected"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[AccessAttempt]:
        """Add ``locked_failures``: the failures of the row's e-mail and address within the
        cool-off, summed over all browsers, in one query for the whole list."""
        counters = AccessAttempt.objects.filter(
            username=OuterRef("username"), ip_address=OuterRef("ip_address")
        )
        threshold = lock_threshold()
        if threshold is not None:
            counters = counters.filter(attempt_time__gte=threshold)
        total = (
            counters.order_by()
            .values("username", "ip_address")
            .annotate(total=Sum("failures_since_start"))
            .values("total")
        )
        return super().get_queryset(request).annotate(locked_failures=Coalesce(Subquery(total), 0))

    @admin.display(description="zamčeno")
    def locked(self, obj: AccessAttempt) -> str:
        """Icon + text + colour: locked now, lock expired, or failures left before the lock."""
        limit = axes_settings.AXES_FAILURE_LIMIT
        failures = obj.locked_failures  # annotated by get_queryset
        if failures >= limit:
            return status_badge(Tone.DANGER, "⛔", "zamčeno")
        if obj.failures_since_start >= limit:
            return status_badge(Tone.INFO, "ⓘ", "zámek vypršel")
        return status_badge(Tone.INFO, "ⓘ", f"ne, zbývá pokusů: {limit - failures}")

    @admin.action(description="Odemknout", permissions=["delete"])
    def unlock_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Unlock the e-mail addresses of the selected counters, on every address.

        Calls axes' own ``reset(username=...)`` for each e-mail, which removes all counters of
        it (also those of other addresses and browsers: an account is unlocked, not a row).
        Counters without an e-mail are skipped (``reset`` without one would clear everything).
        Written to the access log as ``UNLOCK`` for every counter that was removed.
        """
        usernames = sorted({name for name in queryset.values_list("username", flat=True) if name})
        skipped = queryset.filter(username__isnull=True).count()
        removed_pks = list(
            AccessAttempt.objects.filter(username__in=usernames).values_list("pk", flat=True)
        )
        for username in usernames:
            axes_reset(username=username)
        self.record_access(request, AdminAccessAction.UNLOCK, object_pks=removed_pks)
        self.message_user(
            request,
            f"Odemčeno účtů: {len(usernames)} (smazaných počítadel: {len(removed_pks)}).",
            messages.SUCCESS,
        )
        if skipped:
            self.message_user(
                request,
                f"Přeskočeno počítadel bez e-mailu: {skipped}.",
                messages.WARNING,
            )

    def get_actions(self, request: HttpRequest) -> dict[str, Any]:
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)  # one way to unlock, with a clear name
        return actions


class AccessLogAdmin(_ReadOnlyAxesAdmin):
    list_display = ("attempt_time", "username", "ip_address", "logout_time")
    list_filter = ("attempt_time",)
    search_fields = ("username", "ip_address")
    fields = ("username", "ip_address", "user_agent", "path_info", "attempt_time", "logout_time")


class AccessFailureLogAdmin(_ReadOnlyAxesAdmin):
    list_display = ("attempt_time", "username", "ip_address", "locked_out")
    list_filter = ("attempt_time", "locked_out")
    search_fields = ("username", "ip_address")
    fields = ("username", "ip_address", "user_agent", "path_info", "attempt_time", "locked_out")


AXES_ADMINS = {
    AccessAttempt: AccessAttemptAdmin,
    AccessLog: AccessLogAdmin,
    AccessFailureLog: AccessFailureLogAdmin,
}


def adapt_registered_admins() -> None:
    """Replace the admins of django-axes and remove those of the django-otp devices."""
    from django.apps import apps

    apps.get_app_config("axes").verbose_name = APP_NAME
    for model, names in MODEL_NAMES.items():
        model._meta.verbose_name, model._meta.verbose_name_plural = names
        for field in model._meta.fields:
            if field.name in FIELD_LABELS:
                field.verbose_name = FIELD_LABELS[field.name]
        for field_name, label in MODEL_FIELD_LABELS.get(model, {}).items():
            model._meta.get_field(field_name).verbose_name = label
    for model, admin_class in AXES_ADMINS.items():
        if admin.site.is_registered(model):
            admin.site.unregister(model)
            admin.site.register(model, admin_class)
    for model in (TOTPDevice, StaticDevice, StaticToken):
        if admin.site.is_registered(model):
            admin.site.unregister(model)
