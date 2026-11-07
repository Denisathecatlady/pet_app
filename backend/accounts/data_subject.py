"""Handling of requests of data subjects: the export and the erasure of an account (docs/14 §14.12).

The register of requests is the model ``DataSubjectRequest``. Two things can be done for a
request from the administration, both only for a request that

* is still open (received or in progress),
* has an account linked, and
* has the identity of the requester verified (``identity_verified``).

:func:`export_for_request` makes the same JSON file as *Můj účet → Stáhnout moje data*
(``accounts.export.export_json``); :func:`erase_account` deletes the account with the same
function as the self-service deletion (``accounts.services.delete_account``) and completes the
request, in one transaction. A support administrator may do either only for an account that is
not a staff account; superusers for any, but never erase their own account. The permissions are
``accounts.export_datasubjectrequest`` and ``accounts.erase_datasubjectrequest``.

Whether and how the file reaches the requester, how the identity is verified, which requests
may be refused and what is kept afterwards are decisions of the lawyer (docs/12 §12.8).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Final

from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib.admin.utils import NestedObjects
from django.core.exceptions import PermissionDenied
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone
from django.utils.dateformat import format as format_date
from django.utils.text import capfirst

from . import services
from .export import export_json
from .models import DataSubjectRequest, DataSubjectRequestStatus, User, UserManager

EXPORT_PERMISSION: Final = "accounts.export_datasubjectrequest"
ERASE_PERMISSION: Final = "accounts.erase_datasubjectrequest"


class DataSubjectRequestError(Exception):
    """A rule refused the action. The message is Czech and for the administrator."""


@dataclass(frozen=True)
class ErasureLine:
    """One kind of record that an erasure deletes, and how many of them."""

    label: str
    count: int


def _not_staff_or_superuser(user: User, staff: User) -> bool:
    return not user.is_staff or staff.is_superuser


def refusal_reason(dsr: DataSubjectRequest, staff: User, *, erase: bool) -> str | None:
    """Return why ``staff`` cannot export or erase for ``dsr`` now, or ``None``.

    The reason is Czech. ``erase=True`` adds the rule of the erasure: not the administrator's
    own account (which also keeps the last superuser: a superuser who erases another one is
    an active superuser themselves).
    """
    if not dsr.is_open:
        return "Žádost už je vyřízena."
    if dsr.user_id is None:
        return "K žádosti není přiřazen účet žadatele."
    if not dsr.identity_verified:
        return "Totožnost žadatele není ověřena."
    user = dsr.user
    if not _not_staff_or_superuser(user, staff):
        return "Účty správců vyřizuje jen superuživatel."
    if erase and user.pk == staff.pk:
        return "Vlastní účet tímto postupem smazat nelze, použijte stránku Můj účet."
    return None


def _require(staff: User, permission: str) -> None:
    if not (staff.is_active and staff.has_perm(permission)):
        raise PermissionDenied("Nemáte oprávnění k této akci.")


def export_for_request(dsr: DataSubjectRequest, staff: User) -> tuple[str, str]:
    """Make the personal data export of the account linked to ``dsr``.

    Output: ``(file name, JSON text)``; the JSON is the one of the self-service download. The
    file name carries the number of the request, never the e-mail of the account.

    Raises:
        PermissionDenied: ``staff`` lacks ``EXPORT_PERMISSION``.
        DataSubjectRequestError: ``refusal_reason`` gives one (finished request, no account,
            identity not verified, staff account for a non-superuser).
    """
    _require(staff, EXPORT_PERMISSION)
    reason = refusal_reason(dsr, staff, erase=False)
    if reason is not None:
        raise DataSubjectRequestError(reason)
    name = f"barf-nutri-export-zadost-{dsr.pk}-{timezone.localdate().isoformat()}.json"
    return name, export_json(dsr.user)


def erasure_preview(user: User) -> list[ErasureLine]:
    """List what deleting ``user`` removes, from the same collector the administration's own
    deletion page uses (so a model added later is listed without changing this code).

    Records kept outside foreign keys are counted too: the sign-in records of django-axes
    (by e-mail). The history of changes of the deleted records goes with them.
    """
    collector = NestedObjects(using=DEFAULT_DB_ALIAS)
    collector.collect([user])
    lines = [
        ErasureLine(capfirst(model._meta.verbose_name_plural), len(objects))
        for model, objects in collector.model_objs.items()
        if not model._meta.auto_created  # the tables behind many-to-many fields (user → group)
    ]
    logins = sum(
        model.objects.filter(username=user.email).count()
        for model in (AccessLog, AccessAttempt, AccessFailureLog)
    )
    if logins:
        lines.append(ErasureLine("Záznamy o přihlášení (django-axes)", logins))
    return sorted(lines, key=lambda line: line.label)


def email_matches(user: User, typed: str) -> bool:
    """Return whether ``typed`` is the e-mail of ``user`` (letter case and spaces do not count)."""
    return UserManager.normalize_email(typed) == user.email


def outcome_note(lines: Iterable[ErasureLine], today: date) -> str:
    """The note written to a request completed by an erasure: the date and counts, no personal
    data (the account is gone, the record stays)."""
    counts = ", ".join(f"{line.label.lower()}: {line.count}" for line in lines)
    return (
        f"Výmaz účtu proveden správcem dne {format_date(today, 'j. n. Y')}. "
        f"Smazáno: {counts}. Zálohy databáze obsahují údaje do uplynutí doby uchování záloh."
    )


def erase_account(
    dsr: DataSubjectRequest, staff: User, *, confirm_email: str
) -> DataSubjectRequest:
    """Erase the account linked to ``dsr`` and complete the request, in one transaction.

    The account is deleted by ``services.delete_account``, the function behind *Můj účet →
    Smazat účet*: the animals and their records, shares, history of changes, sign-in records,
    two-factor devices and requests for the role of a veterinarian go with it. The request
    stays, without the account, as ``COMPLETED`` with an automatic outcome note (counts and the
    date, no personal data) and ``completed_on`` today; the administrator who did it becomes
    ``handled_by`` when nobody was.

    Inputs: the request, the administrator, and the e-mail of the account typed in again.

    Output: the completed request.

    Raises:
        PermissionDenied: ``staff`` lacks ``ERASE_PERMISSION``.
        DataSubjectRequestError: ``refusal_reason`` (``erase=True``) gives one, or
            ``confirm_email`` is not the e-mail of the account. Nothing is deleted.
    """
    _require(staff, ERASE_PERMISSION)
    with transaction.atomic():
        current = (
            DataSubjectRequest.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=dsr.pk)
        )
        reason = refusal_reason(current, staff, erase=True)
        if reason is not None:
            raise DataSubjectRequestError(reason)
        user = current.user
        if not email_matches(user, confirm_email):
            raise DataSubjectRequestError("Zadaný e-mail není e-mailem tohoto účtu.")
        lines = erasure_preview(user)
        services.delete_account(user)
        current.refresh_from_db()  # the link to the account was emptied by the deletion
        current.status = DataSubjectRequestStatus.COMPLETED
        current.completed_on = timezone.localdate()
        current.outcome_note = outcome_note(lines, current.completed_on)
        if current.handled_by_id is None:
            current.handled_by = staff
        current.save()
    return current
