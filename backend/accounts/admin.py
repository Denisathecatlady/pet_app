"""Admin for the e-mail based user (docs/14 §14.4).

Who may do what with users:

* **Superusers** edit every field except ``is_staff`` (derived from the roles, read-only)
  and the password (nobody can read or set a password hash here).
* **Everybody else with the permission** (the role ``support_admin``) sees and edits only
  NON-staff users, and of those only the names and the active flag. The superuser flag, the
  individual permissions and the roles are not even in their form, so a crafted request
  cannot change them either. They can neither see nor edit, deactivate or delete superusers
  and other staff users.
* **Deleting a user** (the permission and the *delete selected* action) is for superusers
  only, whatever permissions a group has. Erasure of an ordinary user goes through the data
  subject request flow (GDPR art. 17).
* A password is never typed in by an administrator, not even for a new account: the action
  *Odeslat odkaz na obnovu hesla* sends the normal, rate-limited reset e-mail to the user.
* Registrations that wait for activation have a filter and two actions: *Znovu odeslat
  aktivační e-mail* (the throttled service of the web) and *Smazat neaktivované registrace
  starší než lhůta* (after a confirmation page; the same function as ``manage.py
  purge_pending_accounts``, which deletes only what is past ``PENDING_ACCOUNT_RETENTION``).
"""

import logging
from typing import Any

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.urls import URLPattern

from backoffice.access_log import AccessLoggedAdminMixin
from backoffice.admin_tools import action_confirmed, confirmation_response
from backoffice.models import AdminAccessAction

from . import services, two_factor
from .forms import PasswordResetForm
from .models import User
from .roles import ROLE_LABELS

logger = logging.getLogger(__name__)

PURGE_TEMPLATE = "admin/accounts/purge_pending_confirmation.html"
MAX_LISTED_REGISTRATIONS = 20


class PendingRegistrationFilter(admin.SimpleListFilter):
    """Registrations that wait for the activation e-mail to be confirmed."""

    title = "čeká na aktivaci"
    parameter_name = "ceka_na_aktivaci"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:
        return [("ano", "ano"), ("po_lhute", "ano, po lhůtě (smaže se)")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[User]) -> QuerySet[User]:
        if self.value() == "ano":
            return queryset.filter(activation_pending=True, is_active=False)
        if self.value() == "po_lhute":
            return queryset.filter(pk__in=services.stale_pending_accounts().values("pk"))
        return queryset


class AdminUserCreationForm(forms.ModelForm):
    """Creates an account from an e-mail address alone.

    No password is typed in: the account has none until its owner sets one with the link
    from *Odeslat odkaz na obnovu hesla*, so no administrator ever knows a password.
    """

    class Meta:
        model = User
        fields = ("email",)

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class AdminUserChangeForm(forms.ModelForm):
    """Edits the fields chosen by ``UserAdmin.get_fieldsets``; has no password field."""

    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(AccessLoggedAdminMixin, DjangoUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email",)}),)
    list_display = (
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "role_names",
        "date_joined",
    )
    list_filter = (PendingRegistrationFilter, "is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    actions = [
        "send_password_reset_link",
        "resend_activation_email",
        "delete_stale_registrations",
        "reset_two_factor",
    ]

    # --- Who may touch which user ---------------------------------------------------------

    @staticmethod
    def _is_superuser(request: HttpRequest) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def get_queryset(self, request: HttpRequest) -> QuerySet[User]:
        """Non-superusers do not see staff users at all (nor superusers, who are staff).

        The roles are fetched for the whole list at once (the list shows them).
        """
        queryset = super().get_queryset(request).prefetch_related("groups")
        return queryset if self._is_superuser(request) else queryset.filter(is_staff=False)

    def has_view_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        if obj is not None and obj.is_staff and not self._is_superuser(request):
            return False
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        if obj is not None and obj.is_staff and not self._is_superuser(request):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        """Superusers only, whatever permissions a group or a user was given."""
        return self._is_superuser(request) and super().has_delete_permission(request, obj)

    def get_urls(self) -> list[URLPattern]:
        """Without Django's page for typing in another user's password (an e-mail link is used)."""
        return super(DjangoUserAdmin, self).get_urls()

    # --- The form -------------------------------------------------------------------------

    def get_fieldsets(self, request: HttpRequest, obj: User | None = None) -> Any:
        if obj is None:
            return self.add_fieldsets
        if not self._is_superuser(request):
            return (
                (None, {"fields": ("email",)}),
                ("Osobní údaje", {"fields": ("first_name", "last_name")}),
                ("Stav účtu", {"fields": ("is_active", "activation_pending", "role_names")}),
                ("Zabezpečení", {"fields": ("two_factor_state",)}),
                ("Důležitá data", {"fields": ("last_login", "date_joined")}),
            )
        return (
            (None, {"fields": ("email",)}),
            ("Osobní údaje", {"fields": ("first_name", "last_name")}),
            ("Stav účtu", {"fields": ("is_active", "activation_pending")}),
            (
                "Oprávnění a role",
                {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
            ),
            ("Zabezpečení", {"fields": ("two_factor_state",)}),
            ("Důležitá data", {"fields": ("last_login", "date_joined")}),
        )

    def get_readonly_fields(self, request: HttpRequest, obj: User | None = None) -> tuple:
        if obj is None:
            return ()
        always = (
            "activation_pending",
            "is_staff",
            "role_names",
            "two_factor_state",
            "last_login",
            "date_joined",
        )
        # The e-mail is the login name and the address reset links go to: a change of it is a
        # change of who controls the account, so only a superuser makes it.
        return always if self._is_superuser(request) else ("email", *always)

    @admin.display(description="role")
    def role_names(self, obj: User) -> str:
        labels = sorted(ROLE_LABELS.get(group.name, group.name) for group in obj.groups.all())
        return ", ".join(labels) or "žádná"

    @admin.display(description="dvoufázové ověření")
    def two_factor_state(self, obj: User) -> str:
        status = two_factor.status(obj)
        if status.enrolled:
            return f"✓ zapnuto (nepoužitých záložních kódů: {status.recovery_codes_left})"
        if status.required:
            return "⚠ povinné, zatím nenastaveno"
        return "ⓘ vypnuto"

    # --- Actions --------------------------------------------------------------------------

    @admin.action(description="Odeslat odkaz na obnovu hesla", permissions=["change"])
    def send_password_reset_link(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        """Send the normal password reset e-mail (same text, same limits as on the web).

        Nothing is sent to an inactive account or when an e-mail of this kind went to the user
        within the last two minutes or ten were sent today (``claim_email_slot``).
        """
        sent = 0
        for user in queryset:
            form = PasswordResetForm({"email": user.email})
            if not form.is_valid():
                continue
            form.save(
                request=request,
                use_https=request.is_secure(),
                email_template_name="accounts/email/password_reset_body.txt",
                subject_template_name="accounts/email/password_reset_subject.txt",
            )
            if form.sent_to:
                sent += 1
                self.log_change(request, user, "Odeslán odkaz na obnovu hesla.")
        skipped = queryset.count() - sent
        self.message_user(request, f"Odkaz na obnovu hesla byl odeslán: {sent}.", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"Neodesláno: {skipped} (účet není aktivní nebo byl e-mail tohoto druhu "
                "odeslán před chvílí).",
                messages.WARNING,
            )

    @admin.action(description="Znovu odeslat aktivační e-mail", permissions=["change"])
    def resend_activation_email(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        """Send the activation link again to the selected registrations that wait for it.

        Uses the service of the web (``services.send_activation_email``): at most one such
        e-mail per two minutes and ten e-mails a day per account. The message counts the
        e-mails sent, those held back by that limit and the selected accounts that do not
        wait for activation (active or deactivated by an administrator), which get nothing.
        """
        selected = list(queryset)
        waiting = [user for user in selected if user.activation_pending and not user.is_active]
        sent = 0
        for user in waiting:
            if services.send_activation_email(user, request):
                sent += 1
                self.log_change(request, user, "Znovu odeslán aktivační e-mail.")
        if not sent:  # nothing was changed: the records were only looked at
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, selected)
        self.message_user(request, f"Aktivační e-mail byl odeslán: {sent}.", messages.SUCCESS)
        if sent < len(waiting):
            self.message_user(
                request,
                f"Neodesláno kvůli omezení počtu e-mailů: {len(waiting) - sent}. "
                "Zkuste to za několik minut.",
                messages.WARNING,
            )
        if len(waiting) < len(selected):
            self.message_user(
                request,
                f"Přeskočeno účtů, které nečekají na aktivaci: {len(selected) - len(waiting)}.",
                messages.WARNING,
            )

    def has_purge_pending_permission(self, request: HttpRequest) -> bool:
        """Support administrators may do it (they see only non-staff accounts); it deletes
        nothing that the daily ``purge_pending_accounts`` would not delete anyway."""
        return bool(request.user.is_active and request.user.has_perm("accounts.change_user"))

    @admin.action(
        description="Smazat neaktivované registrace starší než lhůta",
        permissions=["purge_pending"],
    )
    def delete_stale_registrations(
        self, request: HttpRequest, queryset: QuerySet[User]
    ) -> TemplateResponse | None:
        """Delete the selected registrations that were never activated and are past the retention.

        Only accounts that are inactive, still ``activation_pending`` and older than
        ``settings.PENDING_ACCOUNT_RETENTION`` are deleted, whatever is selected; the
        confirmation page shows how many. The deletion is the shared function
        ``services.purge_pending_accounts`` and is written to the access log (``DELETE``).
        """
        selected = list(queryset)
        stale_ids = set(
            services.stale_pending_accounts()
            .filter(pk__in=[user.pk for user in selected])
            .values_list("pk", flat=True)
        )
        stale = [user for user in selected if user.pk in stale_ids]
        if not stale:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, selected)
            self.message_user(
                request,
                "Mezi vybranými účty není žádná neaktivovaná registrace starší než lhůta.",
                messages.WARNING,
            )
            return None
        if action_confirmed(request):
            with transaction.atomic():
                self.log_deletions(request, stale)
                deleted = services.purge_pending_accounts(
                    users=User.objects.filter(pk__in=[user.pk for user in stale])
                )
            self.message_user(
                request, f"Smazáno neaktivovaných registrací: {deleted}.", messages.SUCCESS
            )
            return None
        self.record_access(request, AdminAccessAction.VIEW_OBJECT, selected)
        return confirmation_response(
            self,
            request,
            selected,
            action="delete_stale_registrations",
            template=PURGE_TEMPLATE,
            title="Smazat neaktivované registrace",
            context={
                "count": len(stale),
                "skipped": len(selected) - len(stale),
                "listed": [user.email for user in stale[:MAX_LISTED_REGISTRATIONS]],
                "more": max(len(stale) - MAX_LISTED_REGISTRATIONS, 0),
                "retention_days": settings.PENDING_ACCOUNT_RETENTION.days,
                "confirm_label": "Trvale smazat registrace",
                "can_confirm": True,
                "danger": True,
            },
        )

    def has_reset_two_factor_permission(self, request: HttpRequest) -> bool:
        return self._is_superuser(request)

    @admin.action(description="Zrušit dvoufázové ověření", permissions=["reset_two_factor"])
    def reset_two_factor(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        """Remove every two-factor device of the selected users (loss of the device).

        Superusers only. A staff user must set two-factor up again at the next request. Each
        reset is recorded in the log of the administration (who, whom, when) and in the access
        log; the shell equivalent is ``manage.py reset_2fa <e-mail>``.
        """
        for user in queryset:
            two_factor.remove_devices(user)
            self.log_change(request, user, "Zrušeno dvoufázové ověření.")
            logger.warning("Two-factor reset for user %s by %s.", user.pk, request.user.pk)
        self.message_user(
            request,
            f"Dvoufázové ověření bylo zrušeno: {queryset.count()}. "
            "Uživatel ho musí nastavit znovu.",
            messages.SUCCESS,
        )


# The other admins of the accounts app register themselves when their module is imported.
from . import data_subject_admin, vet_admin  # noqa: E402, F401
