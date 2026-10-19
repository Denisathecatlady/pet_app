"""Bezpečnostní brána rozboru: zdravotní stavy, fáze a BCS (docs/09 §9.2).

Brána rozhoduje, zda smí jádro dávku vyhodnotit proti standardu:

- ``BLOCKED`` – automatický výpočet nelze doporučit (např. růst, březost,
  laktace, BCS 1–2, zdravotní stav v režimu ``BLOCKED``, pravidlo úrovně
  ``BLOCKED`` jako surovina toxická pro druh),
- ``EXPERT_REQUIRED`` – výpočet proběhne, ale výsledek musí posoudit odborník
  (BCS 3 a 6–9, stav v režimu ``EXPERT_REQUIRED``…),
- ``OK`` – bez omezení.

``BLOCKED`` má přednost před ``EXPERT_REQUIRED``. Politika fází a BCS je
stejná jako v :mod:`nutricalc.energy` (sdílené konstanty, docs/05 §5.3);
režim zdravotních stavů je data (``HealthCondition.mode``), která schvaluje
specialista 🛠 🩺.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from nutricalc.energy import (
    BCS_BLOCKED,
    BCS_MAX,
    BCS_MIN,
    BCS_WITHOUT_RESTRICTION,
    UNSUPPORTED_STATES,
    EnergyEstimate,
)
from nutricalc.errors import InvalidInputError, ValidationError
from nutricalc.flags import check_code
from nutricalc.rules import RuleWarning
from nutricalc.vocab import (
    WARNING_LEVEL_RANK,
    EnergyStatus,
    GateStatus,
    PhysiologicalState,
    WarningLevel,
    as_member,
)

GATE_LEVELS = frozenset({WarningLevel.EXPERT_REQUIRED, WarningLevel.BLOCKED})
"""Úrovně, které brána zohledňuje (nižší úrovně jsou jen informace)."""


@dataclass(frozen=True)
class HealthConditionRef:
    """Zdravotní stav zvířete s režimem brány (data ``HealthCondition``, docs/09 §9.2).

    ``code`` – kód stavu (velká písmena, číslice, _), např. ``CKD``.
    ``mode`` – ``EXPERT_REQUIRED`` nebo ``BLOCKED``.

    Chyby: ``TypeError``; :class:`~nutricalc.errors.ValidationError` pro
    neplatný kód nebo jiný režim.
    """

    code: str
    mode: WarningLevel

    def __post_init__(self) -> None:
        check_code(self.code, "Kód zdravotního stavu")
        mode = as_member(WarningLevel, self.mode, "režim zdravotního stavu")
        if mode not in GATE_LEVELS:
            raise ValidationError(
                f"Zdravotní stav {self.code}: režim musí být EXPERT_REQUIRED nebo BLOCKED "
                f"(zadáno {mode})."
            )
        object.__setattr__(self, "mode", mode)


@dataclass(frozen=True)
class GateReason:
    """Jeden důvod stavu brány.

    ``level`` (``EXPERT_REQUIRED`` nebo ``BLOCKED``), ``code``, ``message_cs``
    a ``subject`` (čeho se týká: kód zdravotního stavu, suroviny…, jinak ``None``).
    """

    level: WarningLevel
    code: str
    message_cs: str
    subject: str | None = None


@dataclass(frozen=True)
class GateResult:
    """Výsledek brány: ``status`` a ``reasons`` (seřazené od nejzávažnějšího)."""

    status: GateStatus
    reasons: tuple[GateReason, ...]


def _reason_key(reason: GateReason) -> tuple[int, str, str, str]:
    return (-WARNING_LEVEL_RANK[reason.level], reason.code, reason.subject or "", reason.message_cs)


def _check_bcs(bcs: object) -> int | None:
    if bcs is None:
        return None
    if isinstance(bcs, bool) or not isinstance(bcs, int):
        raise TypeError(f"BCS musí být celé číslo 1–9 nebo None, ne {type(bcs).__name__}.")
    if not BCS_MIN <= bcs <= BCS_MAX:
        raise InvalidInputError(f"BCS {bcs} je mimo devítibodovou škálu {BCS_MIN}–{BCS_MAX}.")
    return bcs


def evaluate_gate(
    physiological_state: PhysiologicalState | str,
    bcs: int | None,
    health_conditions: Iterable[HealthConditionRef],
    energy_estimate: EnergyEstimate | None,
    rule_warnings: Iterable[RuleWarning],
) -> GateResult:
    """Vyhodnotí bezpečnostní bránu (docs/09 §9.2).

    Důvody:
        - fyziologický stav růst, březost, laktace →
          ``BLOCKED`` ``PHYSIOLOGICAL_STATE_NOT_SUPPORTED``,
        - BCS 1–2 → ``BLOCKED`` ``BCS_SEVERE``; BCS 3 a 6–9 →
          ``EXPERT_REQUIRED`` ``BCS_OUT_OF_RANGE``; BCS neznámé brána
          neomezuje (informační upozornění nese odhad energie),
        - každý zdravotní stav → jeho režim, kód ``HEALTH_CONDITION``
          (předmět = kód stavu),
        - odhad energie ve stavu ``BLOCKED`` / ``EXPERT_REQUIRED`` →
          ``ENERGY_ESTIMATE_BLOCKED`` / ``ENERGY_ESTIMATE_EXPERT_REQUIRED``,
        - upozornění pravidel úrovně ``BLOCKED`` nebo ``EXPERT_REQUIRED``
          (např. surovina toxická pro druh) → stejná úroveň a kód.
    Stav brány je nejzávažnější úroveň důvodů; bez důvodu ``OK``.

    Vstup: fyziologický stav, BCS (1–9 nebo ``None``), zdravotní stavy,
    odhad energie (nebo ``None``) a upozornění pravidel.
    Výstup: :class:`GateResult` (důvody bez duplicit, seřazené deterministicky).
    Chyby: ``TypeError`` pro jiné typy;
    :class:`~nutricalc.errors.InvalidInputError` pro BCS mimo 1–9 nebo
    neznámý stav.
    """
    state = as_member(PhysiologicalState, physiological_state, "fyziologický stav")
    score = _check_bcs(bcs)
    reasons: list[GateReason] = []
    if state in UNSUPPORTED_STATES:
        reasons.append(
            GateReason(
                WarningLevel.BLOCKED,
                "PHYSIOLOGICAL_STATE_NOT_SUPPORTED",
                f"Pro stav {state} nelze automatický výpočet doporučit (růst, březost a laktace "
                "nejsou v této verzi podporovány). Dávku musí sestavit veterinář.",
                state.value,
            )
        )
    if score is not None and score in BCS_BLOCKED:
        reasons.append(
            GateReason(
                WarningLevel.BLOCKED,
                "BCS_SEVERE",
                f"BCS {score}/9: automatický výpočet nelze doporučit. Může jít o onemocnění; "
                "obraťte se na veterináře.",
            )
        )
    elif score is not None and score not in BCS_WITHOUT_RESTRICTION:
        reasons.append(
            GateReason(
                WarningLevel.EXPERT_REQUIRED,
                "BCS_OUT_OF_RANGE",
                f"BCS {score}/9 je mimo pásmo 4–5/9. Rozbor vychází z aktuální hmotnosti a "
                "neslouží k hubnutí ani přibírání; výsledek musí posoudit odborník.",
            )
        )
    if isinstance(health_conditions, (str, HealthConditionRef)) or not isinstance(
        health_conditions, Iterable
    ):
        raise TypeError("health_conditions musí být kolekce HealthConditionRef.")
    for condition in health_conditions:
        if not isinstance(condition, HealthConditionRef):
            raise TypeError(
                f"Zdravotní stav musí být HealthConditionRef, ne {type(condition).__name__}."
            )
        action = (
            "automatický výpočet nelze doporučit"
            if condition.mode == WarningLevel.BLOCKED
            else "výsledek musí posoudit odborník"
        )
        reasons.append(
            GateReason(
                condition.mode,
                "HEALTH_CONDITION",
                f"Zdravotní stav {condition.code}: {action} (bezpečnostní brána, docs/09 §9.2).",
                condition.code,
            )
        )
    if energy_estimate is not None:
        if not isinstance(energy_estimate, EnergyEstimate):
            raise TypeError(
                f"energy_estimate musí být EnergyEstimate, ne {type(energy_estimate).__name__}."
            )
        if energy_estimate.status != EnergyStatus.OK:
            level = WarningLevel(energy_estimate.status.value)
            codes = sorted(
                {flag.code for flag in energy_estimate.flags if flag.level in GATE_LEVELS}
            )
            detail = f" ({', '.join(codes)})" if codes else ""
            reasons.append(
                GateReason(
                    level,
                    f"ENERGY_ESTIMATE_{energy_estimate.status.value}",
                    f"Odhad energetické potřeby má stav {energy_estimate.status}{detail}.",
                )
            )
    for warning in rule_warnings:
        if not isinstance(warning, RuleWarning):
            raise TypeError(f"Upozornění musí být RuleWarning, ne {type(warning).__name__}.")
        if warning.level in GATE_LEVELS:
            subject = ", ".join(warning.ingredient_codes) or None
            reasons.append(GateReason(warning.level, warning.code, warning.message_cs, subject))
    ordered = tuple(sorted(dict.fromkeys(reasons), key=_reason_key))
    if any(reason.level == WarningLevel.BLOCKED for reason in ordered):
        status = GateStatus.BLOCKED
    elif ordered:
        status = GateStatus.EXPERT_REQUIRED
    else:
        status = GateStatus.OK
    return GateResult(status=status, reasons=ordered)
