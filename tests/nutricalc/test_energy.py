"""Energetická potřeba (docs/05): rovnice, kontrolní příklady §5.8 a pravidla odhadu.

Koeficienty k = 95, 110 (pes) a 75, 100 (kočka) a hmotnosti jsou kontrolní
příklady z docs/05 §5.8. Meze ``k_high`` jsou SYNTETICKÉ.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nutricalc import ENGINE_VERSION
from nutricalc.energy import (
    BODY_WEIGHT_SANITY_RANGE_KG,
    RER_COEFFICIENT,
    RER_EXPONENT,
    EnergyEstimate,
    EnergyFactor,
    estimate_energy,
    mer_kcal,
    nrc_kitten_me_kcal,
    nrc_puppy_me_kcal,
    rer_kcal,
)
from nutricalc.errors import InvalidInputError, SpeciesMismatchError, ValidationError
from nutricalc.vocab import EnergyStatus, PhysiologicalState, Species, WarningLevel
from tests.nutricalc.synthetic import cat_factor, close, dog_factor, energy_input

# --- kontrolní příklady docs/05 §5.8 (tolerance 1e-6 kcal) ----------------------------


@pytest.mark.parametrize(
    ("weight", "expected"),
    [("10", "393.6389276332443562764657"), ("1", "70"), ("20", "662.0191263022230693111873")],
)
def test_rer_golden(weight: str, expected: str) -> None:
    assert close(rer_kcal(Decimal(weight)), expected)


@pytest.mark.parametrize(
    ("weight", "k", "exponent", "expected"),
    [
        ("20", "95", "0.75", "898.4545285530170226366113"),
        ("20", "110", "0.75", "1040.315769903493394631866"),
        ("4", "100", "0.67", "253.1513187940559913341657"),
        ("4", "75", "0.67", "189.8634890955419935006243"),
    ],
)
def test_mer_golden(weight: str, k: str, exponent: str, expected: str) -> None:
    assert close(mer_kcal(Decimal(weight), Decimal(k), Decimal(exponent)), expected)


def test_puppy_golden() -> None:
    # štěně 10 kg, dospělá hmotnost 30 kg (p = 1/3)
    assert close(nrc_puppy_me_kcal(Decimal(10), Decimal(30)), "1516.508837645375718964346")


def test_kitten_golden() -> None:
    # kotě 2 kg, dospělá hmotnost 4 kg (p = 0,5)
    assert close(nrc_kitten_me_kcal(Decimal(2), Decimal(4)), "266.3210839154574375329454")


def test_golden_values_are_exact_to_28_digits() -> None:
    assert rer_kcal(Decimal(10)) == Decimal("393.6389276332443562764657279")
    assert mer_kcal(Decimal(20), Decimal(95), Decimal("0.75")) == Decimal(
        "898.4545285530170226366113139"
    )


def test_rer_constants() -> None:
    assert RER_COEFFICIENT == Decimal("70") and RER_EXPONENT == Decimal("0.75")


# --- validace rovnic -------------------------------------------------------------------


def test_equations_accept_text_and_int() -> None:
    assert rer_kcal("1") == rer_kcal(1) == Decimal(70)
    assert mer_kcal(1, "110", "0.75") == Decimal(110)


@pytest.mark.parametrize("weight", [Decimal(0), Decimal("-1"), "-1", "0"])
def test_rer_rejects_nonpositive_weight(weight: object) -> None:
    with pytest.raises(InvalidInputError):
        rer_kcal(weight)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [10.0, True])
def test_equations_reject_float_and_bool(value: object) -> None:
    with pytest.raises(TypeError):
        rer_kcal(value)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        mer_kcal(Decimal(10), value, Decimal("0.75"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        nrc_puppy_me_kcal(value, Decimal(30))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "args",
    [
        (Decimal(0), Decimal(110), Decimal("0.75")),
        (Decimal(10), Decimal(0), Decimal("0.75")),
        (Decimal(10), Decimal(110), Decimal(0)),
    ],
)
def test_mer_rejects_nonpositive_inputs(args: tuple[Decimal, Decimal, Decimal]) -> None:
    with pytest.raises(InvalidInputError):
        mer_kcal(*args)


@pytest.mark.parametrize("function", [nrc_puppy_me_kcal, nrc_kitten_me_kcal])
@pytest.mark.parametrize(
    ("weight", "mature"),
    [
        (Decimal(0), Decimal(30)),
        (Decimal(-1), Decimal(30)),
        (Decimal(10), Decimal(0)),
        (Decimal("30.01"), Decimal(30)),
    ],
)
def test_growth_equations_reject_invalid_inputs(
    function: object, weight: Decimal, mature: Decimal
) -> None:
    with pytest.raises(InvalidInputError):
        function(weight, mature)  # type: ignore[operator]


@pytest.mark.parametrize("function", [nrc_puppy_me_kcal, nrc_kitten_me_kcal])
def test_growth_equations_allow_p_equal_one(function: object) -> None:
    result = function(Decimal(4), Decimal(4))  # type: ignore[operator]
    assert result > 0


# --- EnergyFactor a EnergyInput -------------------------------------------------------------


def test_energy_factor_is_keyword_only_frozen_and_normalized() -> None:
    factor = dog_factor("110", k_low="95", k_high="130")
    assert (factor.k_low, factor.k, factor.k_high) == (Decimal(95), Decimal(110), Decimal(130))
    with pytest.raises(FrozenInstanceError):
        factor.k = Decimal(1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        EnergyFactor(Species.DOG, "X", Decimal(1), Decimal(1), "S", "V")  # type: ignore[misc, call-arg, arg-type]
    text = EnergyFactor(
        species="CAT",  # type: ignore[arg-type]
        situation_code="TEST_CAT",
        k="100",  # type: ignore[arg-type]
        exponent="0.67",  # type: ignore[arg-type]
        source_key="TEST_FIXTURE",
        data_version="test-1",
    )
    assert text == cat_factor()


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"k": Decimal(0)}, ValidationError),
        ({"k": Decimal(-1)}, ValidationError),
        ({"exponent": Decimal(0)}, ValidationError),
        ({"k_low": Decimal(0)}, ValidationError),
        ({"k_low": Decimal(111)}, ValidationError),
        ({"k_high": Decimal(109)}, ValidationError),
        ({"k": 110.0}, TypeError),
        ({"situation_code": ""}, ValidationError),
        ({"source_key": " "}, ValidationError),
        ({"data_version": None}, TypeError),
        ({"species": "HORSE"}, InvalidInputError),
    ],
)
def test_energy_factor_validation(overrides: dict[str, object], error: type[Exception]) -> None:
    fields: dict[str, object] = {
        "species": Species.DOG,
        "situation_code": "TEST_DOG",
        "k": Decimal(110),
        "exponent": Decimal("0.75"),
        "source_key": "TEST_FIXTURE",
        "data_version": "test-1",
    }
    fields.update(overrides)
    with pytest.raises(error):
        EnergyFactor(**fields)  # type: ignore[arg-type]


def test_energy_factor_allows_equal_bounds() -> None:
    factor = dog_factor("110", k_low="110", k_high="110")
    assert factor.k_low == factor.k == factor.k_high


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"body_weight_kg": 20.0}, TypeError),
        ({"body_weight_kg": Decimal(-1)}, InvalidInputError),
        ({"bcs": 5.0}, TypeError),
        ({"bcs": True}, TypeError),
        ({"bcs": "5"}, TypeError),
        ({"neutered": 1}, TypeError),
        ({"neutered": None}, TypeError),
        ({"factor": None}, TypeError),
        ({"species": "HORSE"}, InvalidInputError),
        ({"physiological_state": "SENIOR"}, InvalidInputError),
    ],
)
def test_energy_input_validation(overrides: dict[str, object], error: type[Exception]) -> None:
    with pytest.raises(error):
        energy_input(**overrides)


def test_energy_input_coerces_text() -> None:
    inp = energy_input(species="DOG", physiological_state="MAINTENANCE", body_weight_kg="20")
    assert inp == energy_input()


def test_estimate_energy_requires_energy_input() -> None:
    with pytest.raises(TypeError):
        estimate_energy({"species": "DOG"})  # type: ignore[arg-type]


# --- estimate_energy: výsledek -------------------------------------------------------------


def _codes(estimate: EnergyEstimate) -> list[str]:
    return [flag.code for flag in estimate.flags]


def test_estimate_ok_dog_golden() -> None:
    estimate = estimate_energy(energy_input())
    assert estimate.status is EnergyStatus.OK
    assert close(estimate.kcal_point, "1040.315769903493394631866")
    assert estimate.kcal_low == estimate.kcal_point == estimate.kcal_high
    assert estimate.rer_kcal == rer_kcal(Decimal(20))
    assert estimate.factor == dog_factor()
    assert estimate.engine_version == ENGINE_VERSION
    assert _codes(estimate) == ["ENERGY_IS_ESTIMATE"]
    assert estimate.flags[0].level is WarningLevel.INFO


def test_estimate_range_from_factor_bounds() -> None:
    estimate = estimate_energy(energy_input(factor=dog_factor("110", k_low="95", k_high="130")))
    assert close(estimate.kcal_low, "898.4545285530170226366113")
    assert close(estimate.kcal_point, "1040.315769903493394631866")
    assert estimate.kcal_high == mer_kcal(Decimal(20), Decimal(130), Decimal("0.75"))
    only_low = estimate_energy(energy_input(factor=dog_factor("110", k_low="95")))
    assert only_low.kcal_high == only_low.kcal_point
    assert only_low.kcal_low is not None and only_low.kcal_low < only_low.kcal_point  # type: ignore[operator]


@pytest.mark.parametrize(
    ("k", "expected"), [("100", "253.1513187940559913"), ("75", "189.8634890955419935")]
)
def test_estimate_cat_golden(k: str, expected: str) -> None:
    inp = energy_input(species=Species.CAT, body_weight_kg=Decimal(4), factor=cat_factor(k))
    assert close(estimate_energy(inp).kcal_point, expected)


@pytest.mark.parametrize(
    ("bcs", "status", "code"),
    [
        (1, EnergyStatus.BLOCKED, "BCS_SEVERE"),
        (2, EnergyStatus.BLOCKED, "BCS_SEVERE"),
        (3, EnergyStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (4, EnergyStatus.OK, None),
        (5, EnergyStatus.OK, None),
        (6, EnergyStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (7, EnergyStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (8, EnergyStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (9, EnergyStatus.EXPERT_REQUIRED, "BCS_OUT_OF_RANGE"),
        (None, EnergyStatus.OK, "BCS_MISSING"),
    ],
)
def test_bcs_policy(bcs: int | None, status: EnergyStatus, code: str | None) -> None:
    estimate = estimate_energy(energy_input(bcs=bcs))
    assert estimate.status is status
    expected_codes = {"ENERGY_IS_ESTIMATE"} | ({code} if code else set())
    assert set(_codes(estimate)) == expected_codes
    if status is EnergyStatus.BLOCKED:
        assert (estimate.kcal_point, estimate.kcal_low, estimate.kcal_high) == (None, None, None)
        assert estimate.rer_kcal is None
    else:
        # čísla se počítají vždy z aktuální hmotnosti, i při EXPERT_REQUIRED
        assert estimate.kcal_point == mer_kcal(Decimal(20), Decimal(110), Decimal("0.75"))
    levels = {flag.code: flag.level for flag in estimate.flags}
    assert levels.get("BCS_SEVERE", WarningLevel.BLOCKED) is WarningLevel.BLOCKED
    assert (
        levels.get("BCS_OUT_OF_RANGE", WarningLevel.EXPERT_REQUIRED) is WarningLevel.EXPERT_REQUIRED
    )
    assert levels.get("BCS_MISSING", WarningLevel.INFO) is WarningLevel.INFO


@pytest.mark.parametrize("bcs", [0, 10, -1, 99])
def test_bcs_outside_scale_is_invalid(bcs: int) -> None:
    with pytest.raises(InvalidInputError):
        estimate_energy(energy_input(bcs=bcs))


@pytest.mark.parametrize(
    "state",
    [PhysiologicalState.GROWTH, PhysiologicalState.GESTATION, PhysiologicalState.LACTATION],
)
def test_unsupported_states_are_blocked_without_numbers(state: PhysiologicalState) -> None:
    estimate = estimate_energy(energy_input(physiological_state=state))
    assert estimate.status is EnergyStatus.BLOCKED
    assert (estimate.kcal_point, estimate.kcal_low, estimate.kcal_high, estimate.rer_kcal) == (
        None,
        None,
        None,
        None,
    )
    assert estimate.flags[0].code == "ENERGY_STATE_NOT_SUPPORTED"
    assert estimate.flags[0].level is WarningLevel.BLOCKED
    assert "ENERGY_IS_ESTIMATE" in _codes(estimate)


def test_blocking_reasons_are_all_reported_most_severe_first() -> None:
    estimate = estimate_energy(
        energy_input(physiological_state=PhysiologicalState.LACTATION, bcs=2, neutered=True)
    )
    assert estimate.status is EnergyStatus.BLOCKED
    assert _codes(estimate) == [
        "BCS_SEVERE",
        "ENERGY_STATE_NOT_SUPPORTED",
        "ENERGY_IS_ESTIMATE",
        "NEUTERED_FACTOR_CHOICE",
    ]


def test_validation_runs_before_blocking() -> None:
    with pytest.raises(InvalidInputError):
        estimate_energy(energy_input(physiological_state=PhysiologicalState.GROWTH, bcs=0))
    with pytest.raises(SpeciesMismatchError):
        estimate_energy(
            energy_input(physiological_state=PhysiologicalState.GROWTH, factor=cat_factor())
        )


def test_neutered_adds_info_but_never_a_multiplier() -> None:
    plain = estimate_energy(energy_input(neutered=False))
    neutered = estimate_energy(energy_input(neutered=True))
    assert neutered.kcal_point == plain.kcal_point
    assert neutered.status is EnergyStatus.OK
    flag = next(flag for flag in neutered.flags if flag.code == "NEUTERED_FACTOR_CHOICE")
    assert flag.level is WarningLevel.INFO
    assert "NEUTERED_FACTOR_CHOICE" not in _codes(plain)


def test_expert_required_with_info_flags() -> None:
    estimate = estimate_energy(energy_input(bcs=7, neutered=True))
    assert estimate.status is EnergyStatus.EXPERT_REQUIRED
    assert _codes(estimate) == ["BCS_OUT_OF_RANGE", "ENERGY_IS_ESTIMATE", "NEUTERED_FACTOR_CHOICE"]


@pytest.mark.parametrize(
    ("species", "weight", "valid"),
    [
        (Species.DOG, "0.5", True),
        (Species.DOG, "0.49", False),
        (Species.DOG, "120", True),
        (Species.DOG, "120.01", False),
        (Species.DOG, "0", False),
        (Species.CAT, "0.5", True),
        (Species.CAT, "0.499", False),
        (Species.CAT, "15", True),
        (Species.CAT, "15.1", False),
        (Species.CAT, "20", False),
    ],
)
def test_body_weight_sanity_range(species: Species, weight: str, valid: bool) -> None:
    factor = dog_factor() if species is Species.DOG else cat_factor()
    inp = energy_input(species=species, body_weight_kg=Decimal(weight), factor=factor)
    if valid:
        assert estimate_energy(inp).kcal_point is not None
    else:
        with pytest.raises(InvalidInputError):
            estimate_energy(inp)


def test_sanity_range_constants() -> None:
    assert BODY_WEIGHT_SANITY_RANGE_KG[Species.DOG] == (Decimal("0.5"), Decimal("120"))
    assert BODY_WEIGHT_SANITY_RANGE_KG[Species.CAT] == (Decimal("0.5"), Decimal("15"))


def test_factor_for_other_species_is_rejected() -> None:
    with pytest.raises(SpeciesMismatchError):
        estimate_energy(energy_input(factor=cat_factor()))
    with pytest.raises(SpeciesMismatchError):
        estimate_energy(energy_input(species=Species.CAT, body_weight_kg=Decimal(4)))


def test_factor_with_wrong_exponent_is_rejected() -> None:
    wrong = EnergyFactor(
        species=Species.DOG,
        situation_code="TEST_DOG",
        k=Decimal(110),
        exponent=Decimal("0.67"),
        source_key="TEST_FIXTURE",
        data_version="test-1",
    )
    with pytest.raises(SpeciesMismatchError):
        estimate_energy(energy_input(factor=wrong))


def test_estimate_is_deterministic_and_frozen() -> None:
    first = estimate_energy(energy_input(bcs=6, neutered=True))
    second = estimate_energy(energy_input(bcs=6, neutered=True))
    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.status = EnergyStatus.OK  # type: ignore[misc]


weights = st.integers(min_value=50, max_value=12000).map(lambda n: Decimal(n).scaleb(-2))


@given(weights, weights)
def test_mer_grows_with_body_weight(first: Decimal, second: Decimal) -> None:
    low, high = sorted((first, second))
    if low == high:
        assert mer_kcal(low, 110, "0.75") == mer_kcal(high, 110, "0.75")
    else:
        assert mer_kcal(low, 110, "0.75") < mer_kcal(high, 110, "0.75")
        assert rer_kcal(low) < rer_kcal(high)
