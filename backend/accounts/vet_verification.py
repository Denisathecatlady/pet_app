"""Verification of veterinarians: the request, the decision and the e-mails (docs/14 §14.11).

A user asks for the role ``vet`` on ``/ucet/veterinar/`` (:func:`submit_request`). A
support administrator decides in the administration (:func:`decide`): approving adds the user
to the group ``vet``, rejecting changes nothing, revoking removes the group again. Removing
the group is what ends the access to shared animals and, through the ``m2m_changed`` receiver
of the animals app, cancels the target weights the user confirmed (docs/12 §12.4).

Rules kept here, not in the views, so every caller gets them:

* the administrator needs the permission ``accounts.decide_vetverificationrequest``;
* nobody decides their own request (a second person must), a decided request is final;
* approving needs the note how the identity and the entitlement were verified, rejecting and
  revoking need the reason; the decision and the group change are one transaction.

The e-mails (to the user about a decision, to the operator about a new request) are sent by
the caller after its transaction committed, throttled like the other account e-mails.
"""

import enum
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from .models import User, VetVerificationRequest, VetVerificationStatus
from .roles import Role
from .services import claim_email_slot, send_template_email

DECIDE_PERMISSION: Final = "accounts.decide_vetverificationrequest"


class VetVerificationError(Exception):
    """A rule of the verification refused the action. The message is Czech and for the user."""


class Decision(enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVOKE = "revoke"


@dataclass(frozen=True)
class DecisionRule:
    """What a decision needs and what it does."""

    required_status: VetVerificationStatus  # the request must be in this state
    new_status: VetVerificationStatus
    required_note: str  # the field that must be filled in
    missing_note_message: str
    done_message: str  # written to the history of the administration


RULES: Final = MappingProxyType(
    {
        Decision.APPROVE: DecisionRule(
            VetVerificationStatus.PENDING,
            VetVerificationStatus.APPROVED,
            "verification_method_note",
            "Popište, jak byla totožnost a oprávnění ověřena.",
            "Žádost schválena, přidělena role veterináře.",
        ),
        Decision.REJECT: DecisionRule(
            VetVerificationStatus.PENDING,
            VetVerificationStatus.REJECTED,
            "decision_note",
            "Uveďte odůvodnění zamítnutí.",
            "Žádost zamítnuta.",
        ),
        Decision.REVOKE: DecisionRule(
            VetVerificationStatus.APPROVED,
            VetVerificationStatus.REVOKED,
            "decision_note",
            "Uveďte odůvodnění odebrání role.",
            "Odebrána role veterináře.",
        ),
    }
)


# --- The applicant's side -----------------------------------------------------------------


@dataclass(frozen=True)
class RequestState:
    """What the page ``/ucet/veterinar/`` shows for a user."""

    is_vet: bool
    pending: VetVerificationRequest | None
    latest: VetVerificationRequest | None

    @property
    def can_submit(self) -> bool:
        """A request can be filed by a user without the role and without a pending request."""
        return not self.is_vet and self.pending is None


def request_state(user: User) -> RequestState:
    """Return the role, the pending request and the latest request of ``user``."""
    requests = user.vet_verification_requests.order_by("-submitted_at", "-pk")
    return RequestState(
        is_vet=user.is_vet,
        pending=requests.filter(status=VetVerificationStatus.PENDING).first(),
        latest=requests.first(),
    )


def submit_request(
    user: User, *, professional_id: str = "", workplace: str, message: str = ""
) -> VetVerificationRequest:
    """File a request for the role ``vet`` and tell the operator.

    Inputs: the user and the validated form values (see ``VetVerificationForm``).

    Output: the new pending request.

    Raises:
        VetVerificationError: the user already has the role or a pending request (also when
            a second request is filed at the same moment: the database allows only one).
    """
    state = request_state(user)
    if state.is_vet:
        raise VetVerificationError("Roli veterinárního lékaře už máte.")
    if state.pending is not None:
        raise VetVerificationError("Máte nevyřízenou žádost, počkejte na rozhodnutí správce.")
    try:
        with transaction.atomic():
            vet_request = VetVerificationRequest.objects.create(
                user=user, professional_id=professional_id, workplace=workplace, message=message
            )
    except IntegrityError:  # filed twice at the same moment
        raise VetVerificationError(
            "Máte nevyřízenou žádost, počkejte na rozhodnutí správce."
        ) from None
    notify_operator(vet_request)
    return vet_request


# --- The administrator's side -------------------------------------------------------------


def refusal_reason(
    vet_request: VetVerificationRequest, decision: Decision, staff: User
) -> str | None:
    """Return why ``staff`` cannot apply ``decision`` to ``vet_request`` now, or ``None``.

    The reason is Czech, for the administrator. Checked in this order: the own request, a
    state the decision does not apply to (a decided request is final), an inactive account.
    """
    rule = RULES[decision]
    if vet_request.user_id == staff.pk:
        return "Vlastní žádost nesmíte vyřídit, rozhodnout musí jiný správce."
    if vet_request.status != rule.required_status:
        state = VetVerificationStatus(vet_request.status).label
        if decision is Decision.REVOKE:
            return f"Roli lze odebrat jen u schválené žádosti (stav: {state})."
        return f"Žádost už byla vyřízena (stav: {state})."
    if decision is Decision.APPROVE and not vet_request.user.is_active:
        return "Účet žadatele není aktivní."
    return None


def decide(
    vet_request: VetVerificationRequest,
    decision: Decision,
    *,
    staff: User,
    decision_note: str = "",
    verification_method_note: str = "",
) -> VetVerificationRequest:
    """Approve, reject or revoke ``vet_request`` and change the role in one transaction.

    Inputs: the request, the decision, the administrator and the notes. The notes are
    stripped; the one the decision needs (``RULES``) must not be empty.

    Output: the saved request (re-read under a lock, so a request decided meanwhile is seen).

    Raises:
        PermissionDenied: ``staff`` is not active or lacks ``DECIDE_PERMISSION``.
        VetVerificationError: the required note is empty, or ``refusal_reason`` gives one
            (own request, already decided, wrong state). Nothing is changed.
    """
    if not (staff.is_active and staff.has_perm(DECIDE_PERMISSION)):
        raise PermissionDenied("Nemáte oprávnění rozhodovat o žádostech o ověření veterináře.")
    rule = RULES[decision]
    notes = {
        "decision_note": decision_note.strip(),
        "verification_method_note": verification_method_note.strip(),
    }
    if not notes[rule.required_note]:
        raise VetVerificationError(rule.missing_note_message)
    with transaction.atomic():
        current = VetVerificationRequest.objects.select_for_update().get(pk=vet_request.pk)
        reason = refusal_reason(current, decision, staff)
        if reason is not None:
            raise VetVerificationError(reason)
        current.status = rule.new_status
        current.decided_by = staff
        current.decided_at = timezone.now()
        current.decision_note = notes["decision_note"]
        current.verification_method_note = notes["verification_method_note"]
        current.save()
        vet_group, _ = Group.objects.get_or_create(name=Role.VET)
        if decision is Decision.APPROVE:
            current.user.groups.add(vet_group)
        elif decision is Decision.REVOKE:
            current.user.groups.remove(vet_group)  # also cancels their target weight confirmations
    return current


# --- E-mails ------------------------------------------------------------------------------


def send_decision_email(vet_request: VetVerificationRequest, request: HttpRequest) -> bool:
    """Tell the applicant about the decision (approved, rejected or role revoked).

    Throttled like the other account e-mails (``claim_email_slot``, one kind per decision).
    Nothing is sent to an inactive account.

    Output: ``True`` when the e-mail was handed over for delivery.
    """
    user = vet_request.user
    if not user.is_active or not claim_email_slot(f"vet-{vet_request.status}", user):
        return False
    send_template_email(
        user.email,
        "accounts/email/vet_decision",
        {
            "user": user,
            "decision": vet_request.status,
            "decision_note": vet_request.decision_note,
            "page_url": request.build_absolute_uri(reverse("accounts:vet_verification")),
        },
    )
    return True


def notify_operator(vet_request: VetVerificationRequest) -> bool:
    """Tell the operator (``settings.CONTACT_EMAIL``) that a request waits for a decision.

    The message names the applicant's account and says where to decide, nothing more (no
    workplace, no message, no link: the address of the administration is not mailed around).
    Throttled per applicant like the other account e-mails. Nothing is sent when the
    contact address is not set.

    Output: ``True`` when the e-mail was handed over for delivery.
    """
    if not settings.CONTACT_EMAIL or not claim_email_slot("vet-request", vet_request.user):
        return False
    send_template_email(
        settings.CONTACT_EMAIL,
        "accounts/email/vet_request_notice",
        {"applicant_email": vet_request.user.email},
    )
    return True
