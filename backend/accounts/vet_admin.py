"""Admin of the requests for the role of a veterinarian (docs/14 §14.11).

The list is for reading; the decision is made by three actions that open a confirmation page
requiring the notes (*Schválit*, *Zamítnout*, *Odebrat roli veterináře*). Nobody edits a
request by hand: the record says who decided what and why, so it has no change form (and a
superuser cannot rewrite it either). Only users with the permission
``accounts.decide_vetverificationrequest`` (the role ``support_admin`` and superusers) may
decide; a request is never decided by the person who filed it (``vet_verification``).

Like the user admin, a non-superuser does not see the requests of staff accounts, except
their own (which they cannot decide).
"""

from typing import Any

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.template.response import TemplateResponse
from simple_history.admin import SimpleHistoryAdmin

from backoffice.access_log import AccessLoggedAdminMixin
from backoffice.admin_tools import Tone, action_confirmed, confirmation_response, status_badge
from backoffice.models import AdminAccessAction

from . import vet_verification
from .models import VET_REQUEST_NOTE_MAX_LENGTH, VetVerificationRequest, VetVerificationStatus
from .vet_verification import Decision, VetVerificationError

TEMPLATE = "admin/accounts/vet_decision_confirmation.html"
STATUS_BADGES = {
    VetVerificationStatus.PENDING: (Tone.INFO, "ⓘ"),
    VetVerificationStatus.APPROVED: (Tone.SUCCESS, "✓"),
    VetVerificationStatus.REJECTED: (Tone.DANGER, "⛔"),
    VetVerificationStatus.REVOKED: (Tone.WARNING, "⚠"),
}
# Wording of each decision on the confirmation page and in the messages.
WORDING = {
    Decision.APPROVE: {
        "title": "Schválit žádost o ověření veterináře",
        "button": "Schválit a přidělit roli",
        "done": "Schváleno žádostí: {n}. Uživatelé mají roli veterináře.",
    },
    Decision.REJECT: {
        "title": "Zamítnout žádost o ověření veterináře",
        "button": "Zamítnout žádost",
        "done": "Zamítnuto žádostí: {n}.",
    },
    Decision.REVOKE: {
        "title": "Odebrat roli veterináře",
        "button": "Odebrat roli",
        "done": (
            "Odebrána role veterináře: {n}. Přístup ke sdíleným zvířatům zanikl a cílové "
            "hmotnosti, které uživatelé potvrdili, jsou znovu orientační."
        ),
    },
}
MAX_REFUSALS_LISTED = 5


class VetDecisionForm(forms.Form):
    """The notes of a decision: approving needs how the person was verified, the other two the
    reason (the applicant reads it)."""

    def __init__(self, *args: Any, decision: Decision, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        note = {
            "widget": forms.Textarea(attrs={"rows": 4}),
            "max_length": VET_REQUEST_NOTE_MAX_LENGTH,
        }
        if decision is Decision.APPROVE:
            self.fields["verification_method_note"] = forms.CharField(
                label="Jak byla totožnost a oprávnění ověřena",
                help_text=(
                    "Povinné. Interní poznámka: žadatel ji neuvidí. "
                    "Nezapisujte do ní čísla dokladů."
                ),
                **note,
            )
            self.fields["decision_note"] = forms.CharField(
                label="Poznámka pro žadatele",
                required=False,
                help_text="Nepovinné. Žadatel ji uvidí na stránce a v e-mailu.",
                **note,
            )
        else:
            self.fields["decision_note"] = forms.CharField(
                label="Odůvodnění",
                help_text="Povinné. Žadatel ho uvidí na stránce a v e-mailu.",
                **note,
            )

    def notes(self) -> dict[str, str]:
        """Return the cleaned notes for ``vet_verification.decide`` (empty for absent ones)."""
        return {
            name: self.cleaned_data.get(name, "")
            for name in ("decision_note", "verification_method_note")
        }


@admin.register(VetVerificationRequest)
class VetVerificationRequestAdmin(AccessLoggedAdminMixin, SimpleHistoryAdmin):
    list_display = (
        "applicant",
        "state",
        "workplace",
        "submitted_at",
        "decided_at",
        "decided_by_email",
    )
    list_filter = ("status", "submitted_at", "decided_at")
    search_fields = ("user__email", "workplace", "professional_id")
    list_select_related = ("user", "decided_by")
    fieldsets = (
        (
            "Žádost",
            {"fields": ("applicant", "submitted_at", "workplace", "professional_id", "message")},
        ),
        (
            "Rozhodnutí",
            {
                "fields": (
                    "state",
                    "decided_by_email",
                    "decided_at",
                    "decision_note",
                    "verification_method_note",
                )
            },
        ),
    )
    readonly_fields = (
        "applicant",
        "submitted_at",
        "workplace",
        "professional_id",
        "message",
        "state",
        "decided_by_email",
        "decided_at",
        "decision_note",
        "verification_method_note",
    )
    actions = ["approve_requests", "reject_requests", "revoke_vet_role"]

    # --- Who sees and may do what ---------------------------------------------------------

    @staticmethod
    def _superuser(request: HttpRequest) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def get_queryset(self, request: HttpRequest) -> QuerySet[VetVerificationRequest]:
        queryset = super().get_queryset(request)
        if self._superuser(request):
            return queryset
        return queryset.filter(Q(user__is_staff=False) | Q(user=request.user))

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_decide_permission(self, request: HttpRequest) -> bool:
        return bool(
            request.user.is_active and request.user.has_perm(vet_verification.DECIDE_PERMISSION)
        )

    # --- Columns ----------------------------------------------------------------------------

    @admin.display(description="žadatel", ordering="user__email")
    def applicant(self, obj: VetVerificationRequest) -> str:
        return obj.user.email

    @admin.display(description="stav", ordering="status")
    def state(self, obj: VetVerificationRequest) -> str:
        tone, icon = STATUS_BADGES[VetVerificationStatus(obj.status)]
        return status_badge(tone, icon, obj.get_status_display())

    @admin.display(description="rozhodl", ordering="decided_by__email")
    def decided_by_email(self, obj: VetVerificationRequest) -> str:
        return obj.decided_by.email if obj.decided_by_id else "–"

    # --- Actions ----------------------------------------------------------------------------

    @admin.action(description="Schválit", permissions=["decide"])
    def approve_requests(self, request: HttpRequest, queryset: QuerySet) -> TemplateResponse | None:
        """Approve the selected requests: add the role ``vet`` (needs how they were verified)."""
        return self._decide(request, queryset, Decision.APPROVE, "approve_requests")

    @admin.action(description="Zamítnout", permissions=["decide"])
    def reject_requests(self, request: HttpRequest, queryset: QuerySet) -> TemplateResponse | None:
        """Reject the selected requests (needs the reason); the role is not changed."""
        return self._decide(request, queryset, Decision.REJECT, "reject_requests")

    @admin.action(description="Odebrat roli veterináře", permissions=["decide"])
    def revoke_vet_role(self, request: HttpRequest, queryset: QuerySet) -> TemplateResponse | None:
        """Take the role away from the users of the selected approved requests (needs the reason).

        Access to shared animals ends at once and the target weights they confirmed turn back to
        orientational (the receiver of the animals app reacts to the removed group).
        """
        return self._decide(request, queryset, Decision.REVOKE, "revoke_vet_role")

    def _decide(
        self, request: HttpRequest, queryset: QuerySet, decision: Decision, action: str
    ) -> TemplateResponse | None:
        """Show the confirmation page, or - when it is confirmed - decide in ONE transaction.

        A selected request that cannot be decided (the staff member's own, already decided,
        in the wrong state) is skipped and reported; if none can be decided nothing happens.
        If a request was decided by somebody else meanwhile, nothing at all is changed. Every
        outcome is written to the access log: a shown page as ``VIEW_OBJECT`` (it shows the
        applicants' data), a decision as ``CHANGE`` of each request (``log_change``).
        """
        selected = list(queryset.select_related("user"))
        eligible, refused = [], []
        for vet_request in selected:
            reason = vet_verification.refusal_reason(vet_request, decision, request.user)
            if reason is None:
                eligible.append(vet_request)
            else:
                refused.append((vet_request, reason))
        wording = WORDING[decision]

        if not eligible:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, selected)
            self.message_user(request, "Žádnou z vybraných žádostí nelze vyřídit.", messages.ERROR)
            self._report_refused(request, refused)
            return None

        form = VetDecisionForm(
            request.POST if action_confirmed(request) else None, decision=decision
        )
        if action_confirmed(request) and form.is_valid():
            try:
                with transaction.atomic():
                    decided = [
                        vet_verification.decide(
                            vet_request, decision, staff=request.user, **form.notes()
                        )
                        for vet_request in eligible
                    ]
            except VetVerificationError as error:
                self.record_access(request, AdminAccessAction.VIEW_OBJECT, selected)
                self.message_user(request, f"Nic se nezměnilo: {error}", messages.ERROR)
                return None
            for vet_request in decided:
                self.log_change(request, vet_request, vet_verification.RULES[decision].done_message)
            self.message_user(request, wording["done"].format(n=len(decided)), messages.SUCCESS)
            self._report_emails(request, decided)
            self._report_refused(request, refused)
            return None

        self.record_access(request, AdminAccessAction.VIEW_OBJECT, selected)
        return confirmation_response(
            self,
            request,
            selected,
            action=action,
            template=TEMPLATE,
            title=wording["title"],
            context={
                "decision": decision.value,
                "eligible": eligible,
                "refused": refused,
                "form": form,
                "confirm_label": wording["button"],
                "can_confirm": True,
                "danger": decision is not Decision.APPROVE,
            },
        )

    def _report_emails(self, request: HttpRequest, decided: list[VetVerificationRequest]) -> None:
        sent = sum(vet_verification.send_decision_email(item, request) for item in decided)
        self.message_user(request, f"E-mail žadateli odeslán: {sent}.", messages.SUCCESS)
        if sent < len(decided):
            self.message_user(
                request,
                f"E-mail neodeslán: {len(decided) - sent} (omezení počtu e-mailů nebo "
                "neaktivní účet). Rozhodnutí žadatel uvidí na stránce Role veterinárního lékaře.",
                messages.WARNING,
            )

    def _report_refused(
        self, request: HttpRequest, refused: list[tuple[VetVerificationRequest, str]]
    ) -> None:
        if not refused:
            return
        lines = [f"{item.user.email}: {reason}" for item, reason in refused[:MAX_REFUSALS_LISTED]]
        more = len(refused) - MAX_REFUSALS_LISTED
        if more > 0:
            lines.append(f"… a dalších {more}")
        self.message_user(
            request,
            f"Přeskočeno žádostí: {len(refused)}. " + " ".join(lines),
            messages.WARNING,
        )
