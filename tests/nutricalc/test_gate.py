"""Bezpečnostní brána (docs/09 §9.2): fáze, BCS, zdravotní stavy, energie a pravidla.

Kódy zdravotních stavů a pravidel jsou SYNTETICKÉ fixtury.
"""

import pytest

from nutricalc.energy import estimate_energy
from nutricalc.errors import InvalidInputError, ValidationError
from nutricalc.gate import GateReason, HealthConditionRef, evaluate_gate
from nutricalc.rules import RuleWarning
from nutricalc.vocab import GateStatus, PhysiologicalState, WarningLevel
from tests.nutricalc.synthetic import energy_input

OK_ENERGY = estimate_energy(energy_input())


def warning(code: str, level: WarningLevel, *ingredients: str) -> RuleWarning:
    return RuleWarning(
        level=level,
        code=code,
        message_cs=f"Syntetické upozornění {code}.",
        source_key="TEST_FIXTURE",
        ingredient_codes=tuple(ingredients),
    )


def gate(
    state: PhysiologicalState = PhysiologicalState.MAINTENANCE,
    bcs: int | None = 5,
    conditions: tuple[HealthConditionRef, ...] = (),
    energy: object = OK_ENERGY,
    warnings: tuple[RuleWarning, ...] = (),
) -> object:
    return evaluate_gate(state, bcs, conditions, energy, warnings)  # type: ignore[arg-type]


def test_healthy_adult_passes() -> None:
    result = gate()
    assert result.status == GateStatus.OK and result.reasons == ()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "state",
    [PhysiologicalState.GROWTH, PhysiologicalState.GESTATION, PhysiologicalState.LACTATION],
)
def test_unsupported_states_are_blocked(state: PhysiologicalState) -> None:
    energy = estimate_energy(energy_input(physiological_state=state))
    result = gate(state=state, energy=energy)
    assert result.status == GateStatus.BLOCKED  # type: ignore[attr-defined]
    codes = {reason.code for reason in result.reasons}  # type: ignore[attr-defined]
    assert codes == {"PHYSIOLOGICAL_STATE_NOT_SUPPORTED", "ENERGY_ESTIMATE_BLOCKED"}


@pytest.mark.parametrize(
    ("bcs", "status", "code"),
    [
        (1, GateStatus.BLOCKED, "BCS_SEVERE"),
        (2, GateStatus.BLOCKED, "BCS_SEVERE"),
        (3, GateStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (4, GateStatus.OK, None),
        (5, GateStatus.OK, None),
        (6, GateStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (9, GateStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (None, GateStatus.OK, None),
    ],
)
def test_bcs_policy(bcs: int | None, status: GateStatus, code: str | None) -> None:
    result = gate(bcs=bcs, energy=None)
    assert result.status == status  # type: ignore[attr-defined]
    assert [r.code for r in result.reasons] == ([code] if code else [])  # type: ignore[attr-defined]


@pytest.mark.parametrize("bcs", [0, 10])
def test_bcs_out_of_scale_is_invalid(bcs: int) -> None:
    with pytest.raises(InvalidInputError):
        gate(bcs=bcs)


def test_bcs_type_is_checked() -> None:
    with pytest.raises(TypeError):
        gate(bcs=True)
    with pytest.raises(TypeError):
        gate(bcs="5")  # type: ignore[arg-type]


def test_health_conditions() -> None:
    blocked = HealthConditionRef("SYN_CKD", WarningLevel.BLOCKED)
    expert = HealthConditionRef("SYN_ALLERGY", WarningLevel.EXPERT_REQUIRED)
    assert gate(conditions=(expert,)).status == GateStatus.EXPERT_REQUIRED  # type: ignore[attr-defined]
    result = gate(conditions=(expert, blocked))
    assert result.status == GateStatus.BLOCKED  # type: ignore[attr-defined]
    assert [(r.level, r.subject) for r in result.reasons] == [  # type: ignore[attr-defined]
        (WarningLevel.BLOCKED, "SYN_CKD"),
        (WarningLevel.EXPERT_REQUIRED, "SYN_ALLERGY"),
    ]


@pytest.mark.parametrize("mode", [WarningLevel.INFO, WarningLevel.NUTRITION_WARNING])
def test_health_condition_mode_is_limited(mode: WarningLevel) -> None:
    with pytest.raises(ValidationError):
        HealthConditionRef("SYN_CKD", mode)


def test_health_condition_code_is_checked() -> None:
    with pytest.raises(ValidationError):
        HealthConditionRef("ckd", WarningLevel.BLOCKED)


def test_blocked_wins_over_expert_required() -> None:
    result = gate(bcs=3, conditions=(HealthConditionRef("SYN_CKD", WarningLevel.BLOCKED),))
    assert result.status == GateStatus.BLOCKED  # type: ignore[attr-defined]
    assert [r.level for r in result.reasons] == [  # type: ignore[attr-defined]
        WarningLevel.BLOCKED,
        WarningLevel.EXPERT_REQUIRED,
    ]


def test_energy_estimate_status_is_a_reason() -> None:
    energy = estimate_energy(energy_input(bcs=7))
    result = gate(bcs=7, energy=energy)
    assert result.status == GateStatus.EXPERT_REQUIRED  # type: ignore[attr-defined]
    codes = [r.code for r in result.reasons]  # type: ignore[attr-defined]
    assert codes == ["BCS_OUT_OF_RANGE", "ENERGY_ESTIMATE_EXPERT_REQUIRED"]
    assert "BCS_OUT_OF_RANGE" in result.reasons[1].message_cs  # type: ignore[attr-defined]


def test_rule_warnings_feed_the_gate() -> None:
    toxic = warning("TOXIC_FOR_SPECIES", WarningLevel.BLOCKED, "SYN_ONION")
    thyroid = warning("THYROID_TISSUE", WarningLevel.EXPERT_REQUIRED, "SYN_NECK", "SYN_GULLET")
    info = warning("RAW_DIET", WarningLevel.INFO)
    nutrition = warning("LIVER_SHARE", WarningLevel.NUTRITION_WARNING)
    assert gate(warnings=(info, nutrition)).status == GateStatus.OK  # type: ignore[attr-defined]
    expert = gate(warnings=(thyroid, info))
    assert expert.status == GateStatus.EXPERT_REQUIRED  # type: ignore[attr-defined]
    assert expert.reasons == (  # type: ignore[attr-defined]
        GateReason(
            WarningLevel.EXPERT_REQUIRED,
            "THYROID_TISSUE",
            "Syntetické upozornění THYROID_TISSUE.",
            "SYN_NECK, SYN_GULLET",
        ),
    )
    blocked = gate(warnings=(thyroid, toxic))
    assert blocked.status == GateStatus.BLOCKED  # type: ignore[attr-defined]
    assert blocked.reasons[0].code == "TOXIC_FOR_SPECIES"  # type: ignore[attr-defined]


def test_reasons_are_deterministic() -> None:
    conditions = (
        HealthConditionRef("SYN_B", WarningLevel.BLOCKED),
        HealthConditionRef("SYN_A", WarningLevel.BLOCKED),
    )
    warnings = (warning("W2", WarningLevel.BLOCKED), warning("W1", WarningLevel.EXPERT_REQUIRED))
    forward = gate(bcs=2, conditions=conditions, warnings=warnings)
    backward = gate(bcs=2, conditions=conditions[::-1], warnings=warnings[::-1])
    assert forward == backward
    duplicated = gate(warnings=(warnings[0], warnings[0]))
    assert len(duplicated.reasons) == 1  # type: ignore[attr-defined]


def test_gate_type_errors() -> None:
    with pytest.raises(InvalidInputError):
        gate(state="SENIOR")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        gate(conditions=("SYN_CKD",))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        gate(energy="OK")
    with pytest.raises(TypeError):
        gate(warnings=("TOXIC",))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        evaluate_gate(
            PhysiologicalState.MAINTENANCE,
            5,
            HealthConditionRef("X", WarningLevel.BLOCKED),  # type: ignore[arg-type]
            None,
            (),
        )
