"""Services of the animals app: attention level, age, summaries, sharing, confirmation.

Views stay thin and call these functions. Nothing here computes energy or nutrients:
the attention level only says whether the records call for attention or for an
expert (docs/09 §9.2, docs/08 §8.6).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final, NamedTuple

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, QuerySet, prefetch_related_objects
from django.utils import timezone
from django.utils.dateformat import format as format_date

from accounts.models import User, UserManager
from accounts.roles import Role

from .models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    BodyMeasurement,
    ConditionMode,
    MuscleCondition,
    PhysiologicalState,
    TargetWeightStatus,
)

# --- Attention level (docs/09 §9.2, docs/08 §8.6) ---------------------------------------------

OK: Final = "OK"
INFO: Final = "INFO"
EXPERT_REQUIRED: Final = "EXPERT_REQUIRED"
BLOCKED: Final = "BLOCKED"
LEVELS: Final = (OK, INFO, EXPERT_REQUIRED, BLOCKED)  # ascending severity

ADULT_AGE_MONTHS: Final = 12  # docs/09 §9.2 growth gate, given by the task specification

_STATE_REASONS: Final = {
    PhysiologicalState.GROWTH: (
        "Růst (štěně, kotě): automatický výpočet dávky nelze doporučit. Výživu rostoucího "
        "zvířete má naplánovat veterinární lékař nebo veterinární nutriční specialista."
    ),
    PhysiologicalState.GESTATION: (
        "Březost: automatický výpočet dávky nelze doporučit. Výživu březí samice má "
        "naplánovat veterinární lékař nebo veterinární nutriční specialista."
    ),
    PhysiologicalState.LACTATION: (
        "Laktace: automatický výpočet dávky nelze doporučit. Výživu kojící samice má "
        "naplánovat veterinární lékař nebo veterinární nutriční specialista."
    ),
}
NO_BCS_REASON: Final = (
    "Skóre tělesné kondice (BCS) zatím není zadané. Bez něj nelze posoudit, zda je "
    "aktuální hmotnost vhodná."
)
# docs/08 §8.7
UNVERIFIED_TARGET_REASON: Final = (
    "Zadaná cílová hmotnost je orientační. Ideální hmotnost by měl potvrdit veterinář podle BCS."
)
YOUNG_MAINTENANCE_REASON: Final = (
    "Podle data narození je zvířeti méně než 12 měsíců, ale fyziologický stav je „dospělé "
    "zvíře“. Zvíře může ještě růst: stav ověřte s veterinárním lékařem."
)


class Reason(NamedTuple):
    level: str
    text: str


class Attention(NamedTuple):
    """Overall level (``OK``, ``INFO``, ``EXPERT_REQUIRED``, ``BLOCKED``) and its reasons."""

    level: str
    reasons: tuple[Reason, ...]


def short_date(value: date) -> str:
    return format_date(value, "j. n. Y")


def _bcs_reason(measurement: BodyMeasurement) -> Reason | None:
    bcs = measurement.bcs
    when = short_date(measurement.measured_on)
    if bcs is None or 4 <= bcs <= 5:
        return None
    if bcs <= 2:
        return Reason(
            BLOCKED,
            f"Poslední BCS je {bcs}/9 (z {when}), tedy výrazná podvýživa. Může jít "
            "o onemocnění: obraťte se na veterinárního lékaře. Automatický výpočet dávky "
            "nelze doporučit.",
        )
    if bcs == 3:
        return Reason(
            EXPERT_REQUIRED,
            f"Poslední BCS je 3/9 (z {when}), tedy podváha. Přibírání potřebuje plán "
            "a kontrolu veterinárního lékaře.",
        )
    return Reason(
        EXPERT_REQUIRED,
        f"Poslední BCS je {bcs}/9 (z {when}), tedy nadváha. Hubnutí potřebuje plán "
        "a kontrolu veterinárního lékaře.",
    )


def age_in_months(birth_date: date, today: date) -> int:
    """Return the number of completed months between ``birth_date`` and ``today`` (>= 0)."""
    months = (today.year - birth_date.year) * 12 + today.month - birth_date.month
    if today.day < birth_date.day:
        months -= 1
    return max(months, 0)


def attention(animal: Animal, *, today: date | None = None) -> Attention:
    """Return the attention level of ``animal`` with Czech reasons.

    Rules (docs/09 §9.2):

    * ``BLOCKED``: physiological state growth, gestation or lactation; a condition
      with mode ``BLOCKED``; the latest BCS is 1 or 2.
    * ``EXPERT_REQUIRED``: a condition with mode ``EXPERT_REQUIRED``; the latest BCS is
      3 or 6–9; the latest MCS shows any muscle loss; younger than 12 months by birth
      date while the state is maintenance.
    * ``INFO``: no BCS recorded; a target weight that a vet has not confirmed.
    * ``OK`` otherwise. ``OK`` means only that the records give no reason to warn.

    Inputs: the animal (measurements and conditions are read through prefetch caches
    when present) and optionally today's date (default: today in ``TIME_ZONE``).
    Output: :class:`Attention`; reasons are sorted from the most severe.
    """
    today = today or timezone.localdate()
    prefetch_related_objects([animal], "measurements", "conditions__condition")
    measurements = list(animal.measurements.all())  # newest first (Meta.ordering)
    reasons: list[Reason] = []

    state_reason = _STATE_REASONS.get(animal.physiological_state)
    if state_reason:
        reasons.append(Reason(BLOCKED, state_reason))

    for item in animal.conditions.all():
        name = item.condition.name_cs
        if item.condition.mode == ConditionMode.BLOCKED:
            reasons.append(
                Reason(
                    BLOCKED,
                    f"Zdravotní stav „{name}“: automatický výpočet dávky nelze doporučit. "
                    "O stravě rozhoduje veterinární lékař.",
                )
            )
        else:
            reasons.append(
                Reason(
                    EXPERT_REQUIRED,
                    f"Zdravotní stav „{name}“: výživu má posoudit veterinární lékař.",
                )
            )

    latest_bcs = next((m for m in measurements if m.bcs is not None), None)
    if latest_bcs is None:
        reasons.append(Reason(INFO, NO_BCS_REASON))
    else:
        bcs_reason = _bcs_reason(latest_bcs)
        if bcs_reason:
            reasons.append(bcs_reason)

    latest_mcs = next((m for m in measurements if m.mcs), None)
    if latest_mcs is not None and latest_mcs.mcs != MuscleCondition.NORMAL:
        reasons.append(
            Reason(
                EXPERT_REQUIRED,
                f"Poslední hodnocení svalové kondice (z {short_date(latest_mcs.measured_on)}): "
                f"{latest_mcs.get_mcs_display()}. Ztrátu svalové hmoty má posoudit "
                "veterinární lékař.",
            )
        )

    if (
        animal.physiological_state == PhysiologicalState.MAINTENANCE
        and animal.birth_date is not None
        and age_in_months(animal.birth_date, today) < ADULT_AGE_MONTHS
    ):
        reasons.append(Reason(EXPERT_REQUIRED, YOUNG_MAINTENANCE_REASON))

    if (
        animal.target_weight_kg is not None
        and animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    ):
        reasons.append(Reason(INFO, UNVERIFIED_TARGET_REASON))

    reasons.sort(key=lambda reason: LEVELS.index(reason.level), reverse=True)
    level = reasons[0].level if reasons else OK
    return Attention(level, tuple(reasons))


# --- Age and summaries ------------------------------------------------------------------------


def _plural(count: int, one: str, few: str, many: str) -> str:
    if count == 1:
        return one
    if 2 <= count <= 4:
        return few
    return many


def age_text(animal: Animal, *, today: date | None = None) -> str:
    """Return the age in Czech ("5 měsíců", "asi 3 roky") or "neznámý" without a birth date."""
    if animal.birth_date is None:
        return "neznámý"
    months = age_in_months(animal.birth_date, today or timezone.localdate())
    if months < 1:
        text = "méně než 1 měsíc"
    elif months < 12:
        text = f"{months} {_plural(months, 'měsíc', 'měsíce', 'měsíců')}"
    else:
        years = months // 12
        text = f"{years} {_plural(years, 'rok', 'roky', 'let')}"
    return f"asi {text}" if animal.birth_date_estimated else text


@dataclass(frozen=True)
class AnimalSummary:
    """What a dashboard card shows about one animal."""

    animal: Animal
    age: str
    latest_weight: BodyMeasurement | None
    latest_bcs: BodyMeasurement | None
    attention: Attention


SUMMARY_PREFETCH: Final = (
    "measurements",
    Prefetch("conditions", queryset=AnimalHealthCondition.objects.select_related("condition")),
)


def summarize(animals: Iterable[Animal], *, today: date | None = None) -> list[AnimalSummary]:
    """Build dashboard summaries; prefetch ``SUMMARY_PREFETCH`` to avoid extra queries."""
    today = today or timezone.localdate()
    summaries = []
    for animal in animals:
        measurements = list(animal.measurements.all())
        summaries.append(
            AnimalSummary(
                animal=animal,
                age=age_text(animal, today=today),
                latest_weight=measurements[0] if measurements else None,
                latest_bcs=next((m for m in measurements if m.bcs is not None), None),
                attention=attention(animal, today=today),
            )
        )
    return summaries


def owned_animals(user: Any) -> QuerySet[Animal]:
    """Animals owned by ``user``, prefetched for :func:`summarize`."""
    return Animal.objects.filter(owner=user).prefetch_related(*SUMMARY_PREFETCH)


def shared_animals(user: Any) -> QuerySet[Animal]:
    """Animals shared with ``user`` through an active share; empty unless ``user`` is a vet."""
    if not user.has_role(Role.VET):
        return Animal.objects.none()
    return (
        Animal.objects.filter(shares__vet=user, shares__revoked_at__isnull=True)
        .select_related("owner")
        .prefetch_related(*SUMMARY_PREFETCH)
    )


# --- Sharing with a vet -----------------------------------------------------------------------

NOT_A_VET_MESSAGE: Final = (
    "K tomuto e-mailu nepatří aktivní účet veterinárního lékaře. Sdílet lze jen s účtem, "
    "kterému správce aplikace přidělil roli veterinárního lékaře. Požádejte svého "
    "veterináře, ať si založí účet a o roli požádá."
)


def find_vet(email: str) -> User | None:
    """Return the active user with ``email`` in the ``vet`` group, or ``None``."""
    return User.objects.filter(
        email=UserManager.normalize_email(email), is_active=True, groups__name=Role.VET
    ).first()


def share_with_vet(animal: Animal, email: str, granted_by: Any) -> AnimalShare:
    """Share ``animal`` with the vet whose account has ``email``.

    Inputs: the animal, the vet's e-mail and the owner who grants access.
    Output: the new active share.

    Raises:
        ValidationError: no active vet account has this e-mail, it is the owner's own
            e-mail, or the animal is already shared with this vet.
    """
    vet = find_vet(email)
    if vet is None:
        raise ValidationError(NOT_A_VET_MESSAGE, code="not_a_vet")
    if vet.pk == animal.owner_id:
        raise ValidationError("Zvíře nelze sdílet se svým vlastním účtem.", code="self")
    already = "S tímto veterinářem už zvíře sdílíte."
    if AnimalShare.objects.active().filter(animal=animal, vet=vet).exists():
        raise ValidationError(already, code="duplicate")
    try:
        with transaction.atomic():
            return AnimalShare.objects.create(animal=animal, vet=vet, granted_by=granted_by)
    except IntegrityError:  # shared concurrently
        raise ValidationError(already, code="duplicate") from None


def revoke_share(share: AnimalShare) -> None:
    """End an active share now. The vet loses access immediately; the record is kept."""
    if share.revoked_at is None:
        share.revoked_at = timezone.now()
        share.save(update_fields=["revoked_at"])


# --- Target weight confirmation (docs/05 §5.3) ------------------------------------------------


def confirm_target_weight(animal: Animal, vet: Any, expected_kg: Decimal) -> None:
    """Record that ``vet`` confirms the animal's current target weight.

    Inputs: the animal (the caller has checked ``CONFIRM_TARGET_WEIGHT``), the vet and
    the value the vet saw on the page. Confirming a value that has changed meanwhile
    is refused, so a vet never confirms a number they have not seen.

    Raises:
        ValidationError: no target weight is set, it is already confirmed, or it
            differs from ``expected_kg``.
    """
    if animal.target_weight_kg is None:
        raise ValidationError("Majitel zatím nezadal cílovou hmotnost.", code="missing")
    if animal.target_weight_confirmed:
        raise ValidationError("Cílová hmotnost už je potvrzená.", code="confirmed")
    if animal.target_weight_kg != expected_kg:
        raise ValidationError(
            "Cílová hmotnost se mezitím změnila. Zkontrolujte novou hodnotu a potvrďte ji znovu.",
            code="changed",
        )
    animal.target_weight_status = TargetWeightStatus.VET_CONFIRMED
    animal.target_weight_confirmed_by = vet
    animal.target_weight_confirmed_at = timezone.now()
    animal.save(
        update_fields=[
            "target_weight_status",
            "target_weight_confirmed_by",
            "target_weight_confirmed_at",
            "updated_at",
        ]
    )
