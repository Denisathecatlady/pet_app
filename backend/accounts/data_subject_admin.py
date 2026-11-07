"""Admin of the register of requests of data subjects (docs/14 §14.12).

The register is the record that a request was received and how it was handled. Two actions
do the work for a request with a linked account and a verified identity: *Vytvořit export
osobních údajů* (the JSON of the self-service export) and *Provést výmaz účtu* (a confirmation
page lists what will be deleted and asks for the e-mail of the account). A support administrator
may use them only for accounts that are not staff accounts; see ``accounts.data_subject``.
There is no delete permission in the role matrix: a recorded request is evidence.
"""

from typing import Any

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from backoffice.access_log import AccessLoggedAdminMixin, access_logged_action, log_admin_access
from backoffice.admin_tools import Tone, action_confirmed, confirmation_response, status_badge
from backoffice.models import AdminAccessAction

from . import data_subject
from .data_subject import DataSubjectRequestError
from .deadlines import DeadlineKind, deadline_state
from .models import (
    FINISHED_REQUEST_STATUSES,
    OPEN_REQUEST_STATUSES,
    DataSubjectRequest,
    User,
)

ERASE_TEMPLATE = "admin/accounts/erase_account_confirmation.html"
DEADLINE_BADGES = {
    DeadlineKind.DONE: (Tone.SUCCESS, "✓", "vyřízeno"),
    DeadlineKind.OVERDUE: (Tone.DANGER, "⛔", "po termínu"),
    DeadlineKind.SOON: (Tone.WARNING, "⚠", "blíží se termín"),
    DeadlineKind.OK: (Tone.INFO, "ⓘ", "v termínu"),
}


class OverdueFilter(admin.SimpleListFilter):
    """Open requests whose deadline has passed (*po termínu*), or all the others."""

    title = "po termínu"
    parameter_name = "po_terminu"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:
        return [("ano", "ano"), ("ne", "ne")]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        overdue = Q(due_on__lt=timezone.localdate(), status__in=OPEN_REQUEST_STATUSES)
        if self.value() == "ano":
            return queryset.filter(overdue)
        if self.value() == "ne":
            return queryset.exclude(overdue)
        return queryset


class ErasureConfirmForm(forms.Form):
    """The e-mail of the account to be erased, typed in again."""

    confirm_email = forms.CharField(
        label="E-mail účtu, který se smaže",
        max_length=254,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
        help_text="Opište e-mail účtu uvedený výše. Smazání je nevratné.",
    )

    def __init__(self, *args: Any, account: User, **kwargs: Any) -> None:
        self.account = account
        super().__init__(*args, **kwargs)

    def clean_confirm_email(self) -> str:
        typed = self.cleaned_data["confirm_email"]
        if not data_subject.email_matches(self.account, typed):
            raise forms.ValidationError("Zadaný e-mail není e-mailem tohoto účtu.")
        return typed


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(AccessLoggedAdminMixin, SimpleHistoryAdmin):
    list_display = (
        "number",
        "deadline",
        "status",
        "request_type",
        "subject_label",
        "account",
        "due_on",
        "identity_verified",
    )
    list_display_links = ("number",)
    list_filter = (
        "status",
        "request_type",
        "received_via",
        "identity_verified",
        OverdueFilter,
        "received_on",
    )
    search_fields = ("subject_label", "user__email", "outcome_note")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    actions = ["export_personal_data", "erase_account"]
    fieldsets = (
        (
            "Žádost",
            {"fields": ("request_type", "received_on", "received_via", "subject_label", "user")},
        ),
        ("Ověření totožnosti", {"fields": ("identity_verified", "identity_note")}),
        ("Lhůta", {"fields": ("due_on", "extension_reason", "deadline")}),
        ("Vyřízení", {"fields": ("status", "handled_by", "completed_on", "outcome_note")}),
    )

    # --- Fields and rules -------------------------------------------------------------------

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> tuple[str, ...]:
        """The date of receipt is a fact (read-only once recorded); who handles it and when it
        was completed follow from the work, not from typing."""
        fixed = ("handled_by", "completed_on", "deadline")
        return (*fixed, "received_on") if obj is not None else fixed

    def formfield_for_foreignkey(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        """Only a superuser may link a staff account (their requests are for superusers)."""
        if db_field.name == "user" and not request.user.is_superuser:
            kwargs["queryset"] = User.objects.filter(is_staff=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request: HttpRequest, obj: DataSubjectRequest, form: Any, change: bool):
        if obj.handled_by_id is None:
            obj.handled_by = request.user
        super().save_model(request, obj, form, change)

    def has_export_permission(self, request: HttpRequest) -> bool:
        return bool(
            request.user.is_active and request.user.has_perm(data_subject.EXPORT_PERMISSION)
        )

    def has_erase_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_active and request.user.has_perm(data_subject.ERASE_PERMISSION))

    # --- Columns ----------------------------------------------------------------------------

    @admin.display(description="č.", ordering="pk")
    def number(self, obj: DataSubjectRequest) -> str:
        return f"č. {obj.pk}"

    @admin.display(description="účet", ordering="user__email")
    def account(self, obj: DataSubjectRequest) -> str:
        return obj.user.email if obj.user_id else "–"

    @admin.display(description="po termínu")
    def deadline(self, obj: DataSubjectRequest) -> str:
        """Icon + text + colour: done, past the deadline (with days), due soon or in time."""
        if obj.due_on is None:  # the form for a new request: no deadline yet
            return "–"
        state = deadline_state(
            obj.due_on,
            timezone.localdate(),
            finished=obj.status in FINISHED_REQUEST_STATUSES,
        )
        tone, icon, label = DEADLINE_BADGES[state.kind]
        if state.kind is DeadlineKind.OVERDUE:
            label = f"{label} o {state.days} d"
        elif state.kind in (DeadlineKind.SOON, DeadlineKind.OK):
            label = f"{label}, zbývá {state.days} d"
        return status_badge(tone, icon, label)

    # --- Actions ----------------------------------------------------------------------------

    def _single_request(
        self, request: HttpRequest, queryset: QuerySet
    ) -> DataSubjectRequest | None:
        """Return the one selected request, or tell the administrator to select exactly one."""
        selected = list(queryset.select_related("user"))
        if len(selected) != 1:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, selected)
            self.message_user(request, "Vyberte právě jednu žádost.", messages.ERROR)
            return None
        return selected[0]

    @admin.action(description="Vytvořit export osobních údajů", permissions=["export"])
    @access_logged_action(AdminAccessAction.EXPORT)
    def export_personal_data(self, request: HttpRequest, queryset: QuerySet) -> HttpResponse | None:
        """Download the personal data of the linked account as JSON (the self-service export).

        One request at a time, only an open one with a linked account and a verified
        identity. Written to the access log as ``EXPORT`` of the request and of the account.
        """
        dsr = self._single_request(request, queryset)
        if dsr is None:
            return None
        try:
            filename, payload = data_subject.export_for_request(dsr, request.user)
        except DataSubjectRequestError as error:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, [dsr])
            self.message_user(request, f"Export nelze vytvořit: {error}", messages.ERROR)
            return None
        self.record_access(request, AdminAccessAction.EXPORT, [dsr])
        log_admin_access(request, AdminAccessAction.EXPORT, User, [dsr.user_id])
        LogEntry.objects.log_actions(
            request.user.pk,
            [dsr],
            CHANGE,
            change_message="Vytvořen export osobních údajů účtu.",
            single_object=True,
        )
        response = HttpResponse(payload, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response

    @admin.action(description="Provést výmaz účtu", permissions=["erase"])
    def erase_account(self, request: HttpRequest, queryset: QuerySet) -> TemplateResponse | None:
        """Erase the linked account after a confirmation page and the typed e-mail.

        One request at a time, only an open one with a linked account and a verified identity,
        and for a support administrator only a non-staff account. Deletes exactly as the
        self-service deletion does and completes the request with an automatic note.
        """
        dsr = self._single_request(request, queryset)
        if dsr is None:
            return None
        reason = data_subject.refusal_reason(dsr, request.user, erase=True)
        if reason is not None:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, [dsr])
            self.message_user(request, f"Výmaz nelze provést: {reason}", messages.ERROR)
            return None

        account = dsr.user
        form = ErasureConfirmForm(
            request.POST if action_confirmed(request) else None, account=account
        )
        if action_confirmed(request) and form.is_valid():
            account_pk = account.pk
            try:
                with transaction.atomic():
                    data_subject.erase_account(
                        dsr, request.user, confirm_email=form.cleaned_data["confirm_email"]
                    )
                    # In the same transaction: a deletion that cannot be recorded must not stay.
                    log_admin_access(request, AdminAccessAction.DELETE, User, [account_pk])
                    self.record_access(request, AdminAccessAction.CHANGE, [dsr])
                    LogEntry.objects.log_actions(
                        request.user.pk,
                        [dsr],
                        CHANGE,
                        change_message="Proveden výmaz účtu, žádost vyřízena.",
                        single_object=True,
                    )
            except DataSubjectRequestError as error:
                self.record_access(request, AdminAccessAction.VIEW_OBJECT, [dsr])
                self.message_user(request, f"Výmaz nelze provést: {error}", messages.ERROR)
                return None
            self.message_user(
                request,
                "Účet byl smazán a žádost označena jako vyřízená.",
                messages.SUCCESS,
            )
            return None

        self.record_access(request, AdminAccessAction.VIEW_OBJECT, [dsr])
        return confirmation_response(
            self,
            request,
            [dsr],
            action="erase_account",
            template=ERASE_TEMPLATE,
            title="Provést výmaz účtu",
            context={
                "dsr": dsr,
                "account": account,
                "lines": data_subject.erasure_preview(account),
                "form": form,
                "confirm_label": "Trvale smazat účet",
                "can_confirm": True,
                "danger": True,
            },
        )
