"""Požadavky standardu, výběr sloupce a přepočet minim (docs/06 §6.4).

Všechny hodnoty požadavků jsou SYNTETICKÉ (standard TESTSTD). Referenční
energie 110/95 (pes) a 100/75 (kočka) a hmotnost 20 kg jsou kontrolní
příklady z docs/05 §5.8; k_skut = 120, 100 a 80 jsou příklady z docs/11 §11.2.
"""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nutricalc.energy import mer_kcal
from nutricalc.errors import (
    BasisMismatchError,
    InvalidInputError,
    SpeciesMismatchError,
    UnitMismatchError,
    ValidationError,
)
from nutricalc.requirements import (
    K_ACTUAL_SIGNIFICANT_DIGITS,
    LIFE_STAGE_PAIRS,
    Requirement,
    actual_k,
    check_profile_pair,
    check_requirement_set,
    column_code,
    daily_requirement,
    scale_minima,
    select_requirements,
)
from nutricalc.units import Quantity
from nutricalc.vocab import (
    MAXIMUM_TYPES,
    MINIMUM_TYPES,
    RATIO_TYPES,
    Basis,
    LifeStage,
    RequirementType,
    Species,
    Unit,
    WarningLevel,
)
from tests.nutricalc.synthetic import req, std_pair, std_profile

D = Decimal


# --- Requirement ---------------------------------------------------------------------------


def test_requirement_normalizes_text_values_and_is_frozen() -> None:
    requirement = Requirement(
        nutrient_code="SYN_M",
        requirement_type="MIN_RECOMMENDED",  # type: ignore[arg-type]
        value="3.3330",  # type: ignore[arg-type]
        unit="g",  # type: ignore[arg-type]
        basis="PER_1000KCAL_ME",  # type: ignore[arg-type]
        source_key="TEST_FIXTURE",
    )
    assert requirement.requirement_type is RequirementType.MIN_RECOMMENDED
    assert requirement.value == D("3.3330") and str(requirement.value) == "3.3330"
    assert requirement.unit is Unit.G and requirement.basis is Basis.PER_1000KCAL_ME
    assert requirement.condition_note == ""
    assert requirement.quantity() == Quantity(D("3.3330"), Unit.G, Basis.PER_1000KCAL_ME)
    with pytest.raises(FrozenInstanceError):
        requirement.value = D(1)  # type: ignore[misc]


@pytest.mark.parametrize("kind", list(RequirementType))
def test_requirement_type_groups(kind: RequirementType) -> None:
    requirement = req("SYN_N", kind, "1.5")
    flags = (requirement.is_minimum, requirement.is_maximum, requirement.is_ratio)
    assert flags.count(True) == 1
    assert requirement.is_minimum == (kind in MINIMUM_TYPES)
    assert requirement.is_maximum == (kind in MAXIMUM_TYPES)
    assert requirement.is_ratio == (kind in RATIO_TYPES)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_requirement_value_must_be_positive(value: str) -> None:
    with pytest.raises(ValidationError):
        req("SYN_M", RequirementType.MIN_RECOMMENDED, value)


def test_requirement_rejects_float() -> None:
    with pytest.raises(TypeError):
        Requirement(
            nutrient_code="SYN_M",
            requirement_type=RequirementType.MIN_RECOMMENDED,
            value=1.5,  # type: ignore[arg-type]
            unit=Unit.G,
            basis=Basis.PER_1000KCAL_ME,
            source_key="TEST_FIXTURE",
        )


@pytest.mark.parametrize("basis", [b for b in Basis if b != Basis.PER_1000KCAL_ME])
def test_requirement_basis_must_be_per_1000_kcal(basis: Basis) -> None:
    with pytest.raises(BasisMismatchError):
        Requirement(
            nutrient_code="SYN_M",
            requirement_type=RequirementType.MIN_RECOMMENDED,
            value=D(1),
            unit=Unit.G,
            basis=basis,
            source_key="TEST_FIXTURE",
        )


@pytest.mark.parametrize(
    ("kind", "unit"),
    [
        (RequirementType.RATIO_MIN, Unit.G),
        (RequirementType.RATIO_MAX, Unit.MG),
        (RequirementType.MIN_RECOMMENDED, Unit.RATIO),
        (RequirementType.NUTRITIONAL_MAX, Unit.RATIO),
        (RequirementType.AI, Unit.KCAL),
        (RequirementType.SUL, Unit.KJ),
    ],
)
def test_requirement_unit_must_match_type(kind: RequirementType, unit: Unit) -> None:
    with pytest.raises(UnitMismatchError):
        req("SYN_N", kind, "1", unit=unit)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("nutrient_code", "", ValidationError),
        ("source_key", " ", ValidationError),
        ("condition_note", " vlhká", ValidationError),
        ("condition_note", None, TypeError),
        ("requirement_type", "MINIMUM", InvalidInputError),
    ],
)
def test_requirement_rejects_invalid_text(field: str, value: object, error: type) -> None:
    fields: dict[str, object] = {
        "nutrient_code": "SYN_M",
        "requirement_type": RequirementType.MIN_RECOMMENDED,
        "value": D(1),
        "unit": Unit.G,
        "basis": Basis.PER_1000KCAL_ME,
        "source_key": "TEST_FIXTURE",
        field: value,
    }
    with pytest.raises(error):
        Requirement(**fields)  # type: ignore[arg-type]


# --- soubor požadavků ----------------------------------------------------------------------


def test_requirement_set_is_sorted_deterministically() -> None:
    items = [
        req("SYN_P", RequirementType.NUTRITIONAL_MAX, "7.7777"),
        req("SYN_R", RequirementType.RATIO_MAX, "1.6789"),
        req("SYN_M", RequirementType.MIN_RECOMMENDED, "3.3333"),
        req("SYN_P", RequirementType.MIN_RECOMMENDED, "4.4444"),
        req("SYN_R", RequirementType.RATIO_MIN, "1.2345"),
    ]
    forward = check_requirement_set(items)
    assert forward == check_requirement_set(reversed(items))
    assert [(r.nutrient_code, r.requirement_type.value) for r in forward] == [
        ("SYN_M", "MIN_RECOMMENDED"),
        ("SYN_P", "MIN_RECOMMENDED"),
        ("SYN_P", "NUTRITIONAL_MAX"),
        ("SYN_R", "RATIO_MIN"),
        ("SYN_R", "RATIO_MAX"),
    ]


@pytest.mark.parametrize(
    "kinds",
    [
        (RequirementType.MIN_RECOMMENDED, RequirementType.MR),
        (RequirementType.AI, RequirementType.RA),
        (RequirementType.MIN_RECOMMENDED, RequirementType.MIN_RECOMMENDED),
    ],
)
def test_at_most_one_minimum_per_nutrient_and_condition(
    kinds: tuple[RequirementType, RequirementType],
) -> None:
    with pytest.raises(ValidationError, match="minimum"):
        check_requirement_set([req("SYN_M", kinds[0], "1.1111"), req("SYN_M", kinds[1], "2.2222")])


def test_minimum_under_other_condition_is_allowed() -> None:
    checked = check_requirement_set(
        [
            req("SYN_M", "MIN_RECOMMENDED", "1.1111"),
            req("SYN_M", "MR", "2.2222", condition_note="podmínka X"),
        ]
    )
    assert len(checked) == 2


@pytest.mark.parametrize("kind", sorted(MAXIMUM_TYPES | RATIO_TYPES))
def test_at_most_one_of_each_maximum_and_ratio_type(kind: RequirementType) -> None:
    code = "SYN_R" if kind in RATIO_TYPES else "SYN_M"
    with pytest.raises(ValidationError, match="vícekrát"):
        check_requirement_set([req(code, kind, "5.5555"), req(code, kind, "6.6666")])


def test_all_three_maximum_types_may_coexist() -> None:
    checked = check_requirement_set(
        [
            req("SYN_Z", "MIN_RECOMMENDED", "1.1111"),
            req("SYN_Z", "NUTRITIONAL_MAX", "5.5555"),
            req("SYN_Z", "LEGAL_MAX_EU", "4.4444"),
            req("SYN_Z", "SUL", "6.6666"),
        ]
    )
    assert len(checked) == 4


@pytest.mark.parametrize("maximum", ["NUTRITIONAL_MAX", "LEGAL_MAX_EU", "SUL"])
@pytest.mark.parametrize("value", ["2.2222", "1.5555"])
def test_minimum_must_be_below_every_maximum(maximum: str, value: str) -> None:
    with pytest.raises(ValidationError, match="menší"):
        check_requirement_set(
            [req("SYN_M", "MIN_RECOMMENDED", "2.2222"), req("SYN_M", maximum, value)]
        )


@pytest.mark.parametrize("value", ["1.2345", "1.1111"])
def test_ratio_min_must_be_below_ratio_max(value: str) -> None:
    with pytest.raises(ValidationError, match="RATIO_MIN"):
        check_requirement_set(
            [req("SYN_R", "RATIO_MIN", "1.2345"), req("SYN_R", "RATIO_MAX", value)]
        )


def test_one_unit_per_nutrient() -> None:
    with pytest.raises(ValidationError, match="jednotky"):
        check_requirement_set(
            [
                req("SYN_Z", "MIN_RECOMMENDED", "1.1111", unit=Unit.MG),
                req("SYN_Z", "SUL", "9.9999", unit=Unit.G),
            ]
        )


def test_requirement_set_rejects_other_types() -> None:
    with pytest.raises(TypeError):
        check_requirement_set(["CA"])  # type: ignore[list-item]


# --- StandardProfile -----------------------------------------------------------------------


def test_profile_normalizes_collections() -> None:
    profile = std_profile(mandatory=["CA", "P"], requirements=reversed(std_profile().requirements))
    assert profile.requirements == std_profile().requirements
    assert profile.mandatory_nutrients == frozenset({"CA", "P"})
    assert profile.nutrient_codes == frozenset({"PROTEIN", "CA", "P", "CA_P"})
    assert [r.requirement_type for r in profile.for_nutrient("P")] == [
        RequirementType.MIN_RECOMMENDED,
        RequirementType.NUTRITIONAL_MAX,
    ]


def test_profile_exponent_must_match_species() -> None:
    with pytest.raises(SpeciesMismatchError):
        std_profile(species=Species.CAT, exponent=D("0.75"))
    with pytest.raises(SpeciesMismatchError):
        std_profile(species=Species.DOG, exponent=D("0.67"))


def test_mandatory_nutrient_needs_requirement() -> None:
    with pytest.raises(ValidationError, match="TAURINE"):
        std_profile(mandatory={"CA", "TAURINE"})


@pytest.mark.parametrize("value", [D(0), D(-1)])
def test_profile_reference_k_must_be_positive(value: Decimal) -> None:
    with pytest.raises((ValidationError, InvalidInputError)):
        std_profile(reference_k=value)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("reference_k", 110.0, TypeError),
        ("requirements", "CA", TypeError),
        ("mandatory_nutrients", "CA", TypeError),
        ("standard_code", "", ValidationError),
        ("data_version", "", ValidationError),
        ("life_stage", "ADULT", InvalidInputError),
    ],
)
def test_profile_rejects_invalid_fields(field: str, value: object, error: type) -> None:
    with pytest.raises(error):
        std_profile(**{field: value})  # type: ignore[arg-type]


def test_profile_rejects_duplicate_minimum() -> None:
    with pytest.raises(ValidationError):
        std_profile(requirements=[*std_profile().requirements, req("CA", "AI", "9.8765")])


# --- k_skut ----------------------------------------------------------------------------------


def test_actual_k_recovers_factor_exactly() -> None:
    der = mer_kcal(D(20), D(110), D("0.75"))
    assert actual_k(der, D(20), Species.DOG) == D(110)
    assert actual_k(mer_kcal(D(4), D(75), D("0.67")), D(4), Species.CAT) == D(75)


@given(
    st.integers(min_value=5, max_value=1200).map(lambda n: D(n).scaleb(-1)),
    st.sampled_from(["75", "95", "100", "110", "125"]),
)
def test_actual_k_round_trip_never_crosses_column_boundary(weight: Decimal, k: str) -> None:
    # DER = k · BW^n se počítá s 28 číslicemi; bez zaokrouhlení k_skut by
    # zpětný výpočet občas dal 109,99…9 a zvolil jiný sloupec.
    assert actual_k(mer_kcal(weight, D(k), D("0.75")), weight, Species.DOG) == D(k)


def test_actual_k_precision_is_bounded() -> None:
    value = actual_k(D(1000), D(3), Species.DOG)
    assert len(value.as_tuple().digits) <= K_ACTUAL_SIGNIFICANT_DIGITS


@pytest.mark.parametrize(("der", "weight"), [(D(0), D(20)), (D(100), D(0)), (D(-1), D(20))])
def test_actual_k_rejects_non_positive(der: Decimal, weight: Decimal) -> None:
    with pytest.raises(InvalidInputError):
        actual_k(der, weight, Species.DOG)


def test_actual_k_rejects_float() -> None:
    with pytest.raises(TypeError):
        actual_k(1000.0, D(20), Species.DOG)  # type: ignore[arg-type]


# --- výběr sloupce ---------------------------------------------------------------------------


def test_life_stage_pairs_are_structure_only() -> None:
    assert dict(LIFE_STAGE_PAIRS) == {LifeStage.ADULT_MAINTENANCE: LifeStage.ADULT_MAINTENANCE_LOW}


@pytest.mark.parametrize(
    ("k", "life_stage", "factor"),
    [
        ("120", LifeStage.ADULT_MAINTENANCE, D(1)),
        ("110", LifeStage.ADULT_MAINTENANCE, D(1)),
        ("109.99999", LifeStage.ADULT_MAINTENANCE_LOW, D(1)),
        ("100", LifeStage.ADULT_MAINTENANCE_LOW, D(1)),
        ("95", LifeStage.ADULT_MAINTENANCE_LOW, D(1)),
        ("80", LifeStage.ADULT_MAINTENANCE_LOW, D(95) / D(80)),
    ],
)
def test_dog_column_selection(k: str, life_stage: LifeStage, factor: Decimal) -> None:
    high, low = std_pair()
    selected = select_requirements(high, low, D(k))
    assert selected.profile_used.life_stage == life_stage
    assert selected.min_scale_factor == factor
    assert selected.k_actual == D(k)
    assert selected.column_code == f"TESTSTD:1:DOG:{life_stage}"
    assert selected.column.reference_k == selected.profile_used.reference_k


def test_factor_95_over_80_matches_docs_example() -> None:
    selected = select_requirements(*std_pair(), D(80))
    assert selected.min_scale_factor == D("1.1875")


@pytest.mark.parametrize(
    ("k", "life_stage", "factor"),
    [
        ("100", LifeStage.ADULT_MAINTENANCE, D(1)),
        ("75", LifeStage.ADULT_MAINTENANCE_LOW, D(1)),
        ("60", LifeStage.ADULT_MAINTENANCE_LOW, D("1.25")),
    ],
)
def test_cat_column_selection(k: str, life_stage: LifeStage, factor: Decimal) -> None:
    selected = select_requirements(*std_pair(Species.CAT), D(k))
    assert selected.profile_used.life_stage == life_stage
    assert selected.min_scale_factor == factor


def test_selection_follows_reference_k_data() -> None:
    # Hranice nejsou v kódu: se syntetickými sloupci 123 a 45 se mění i volba.
    high = std_profile("high", reference_k=D(123))
    low = std_profile("low", reference_k=D(45))
    assert select_requirements(high, low, D(110)).profile_used is low
    assert select_requirements(high, low, D(123)).profile_used is high
    assert select_requirements(high, low, D(30)).min_scale_factor == D("1.5")


def test_scaling_applies_only_to_minima() -> None:
    high, low = std_pair()
    selected = select_requirements(high, low, D(80))
    factor = D(95) / D(80)
    assert len(selected.requirements) == len(low.requirements)
    for original, scaled in zip(low.requirements, selected.requirements, strict=True):
        assert scaled.requirement_type == original.requirement_type
        if original.is_minimum:
            assert scaled.value == original.value * factor
            assert scaled.value > original.value
        else:
            assert scaled == original
    # profil použitý pro výběr zůstává nepřepočtený
    assert selected.profile_used.requirements == low.requirements


@pytest.mark.parametrize("kind", list(RequirementType))
def test_scale_minima_per_requirement_type(kind: RequirementType) -> None:
    original = req("SYN_R" if kind in RATIO_TYPES else "SYN_M", kind, "2.2222")
    (scaled,) = scale_minima([original], D("1.5"))
    expected = D("3.3333") if kind in MINIMUM_TYPES else D("2.2222")
    assert scaled.value == expected


def test_scaling_flag_only_when_factor_differs_from_one() -> None:
    high, low = std_pair()
    for k in ("120", "100", "95"):
        assert select_requirements(high, low, D(k)).flags == ()
    (flag,) = select_requirements(high, low, D(80)).flags
    assert flag.code == "REQUIREMENT_SCALING_NEEDS_REVIEW"
    assert flag.level == WarningLevel.NUTRITION_WARNING
    assert "specialista" in flag.message_cs


def test_scale_minima_validation() -> None:
    with pytest.raises(ValidationError):
        scale_minima([req("SYN_M", "AI", "1.1111")], D("0.9"))
    with pytest.raises(TypeError):
        scale_minima([req("SYN_M", "AI", "1.1111")], 1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        scale_minima(["CA"], D(1))  # type: ignore[list-item]


def test_select_rejects_invalid_k() -> None:
    with pytest.raises(InvalidInputError):
        select_requirements(*std_pair(), D(0))
    with pytest.raises(TypeError):
        select_requirements(*std_pair(), 80.0)  # type: ignore[arg-type]


def test_cat_profile_cannot_pair_with_dog_profile() -> None:
    dog_high, _ = std_pair(Species.DOG)
    _, cat_low = std_pair(Species.CAT)
    with pytest.raises(SpeciesMismatchError):
        select_requirements(dog_high, cat_low, D(110))


@pytest.mark.parametrize("field", ["standard_code", "edition"])
def test_profiles_must_share_standard_and_edition(field: str) -> None:
    high, low = std_pair()
    with pytest.raises(ValidationError):
        check_profile_pair(high, replace(low, **{field: "JINÝ"}))  # type: ignore[arg-type]


def test_profiles_must_form_life_stage_pair() -> None:
    high, low = std_pair()
    with pytest.raises(SpeciesMismatchError):
        check_profile_pair(low, high)
    with pytest.raises(SpeciesMismatchError):
        check_profile_pair(high, high)
    growth = std_profile("low", life_stage=LifeStage.LATE_GROWTH)
    with pytest.raises(SpeciesMismatchError):
        check_profile_pair(high, growth)


def test_high_column_must_have_larger_reference_k() -> None:
    high = std_profile("high", reference_k=D(95))
    low = std_profile("low", reference_k=D(95))
    with pytest.raises(ValidationError, match="Referenční energie"):
        check_profile_pair(high, low)


def test_profiles_must_use_same_units() -> None:
    high = std_profile(
        "high", requirements=[req("SYN_Z", "AI", "1.1111", unit=Unit.MG)], mandatory=()
    )
    low = std_profile(
        "low", requirements=[req("SYN_Z", "AI", "1.1111", unit=Unit.UG)], mandatory=()
    )
    with pytest.raises(ValidationError, match="SYN_Z"):
        check_profile_pair(high, low)


def test_check_profile_pair_rejects_other_types() -> None:
    with pytest.raises(TypeError):
        check_profile_pair("high", std_profile("low"))  # type: ignore[arg-type]


def test_column_code() -> None:
    assert column_code(std_profile("low", Species.CAT)) == "TESTSTD:1:CAT:ADULT_MAINTENANCE_LOW"


# --- denní požadavek -------------------------------------------------------------------------


def test_daily_requirement() -> None:
    der = mer_kcal(D(20), D(110), D("0.75"))
    daily = daily_requirement(req("P", "MIN_RECOMMENDED", "4.321"), der)
    assert daily.basis == Basis.PER_DAY and daily.unit == Unit.G
    assert daily.value == D("4.321") * der / D(1000)


def test_daily_requirement_rejects_ratio_and_bad_energy() -> None:
    with pytest.raises(UnitMismatchError):
        daily_requirement(req("CA_P", "RATIO_MAX", "1.6789"), D(1000))
    with pytest.raises(ValidationError):
        daily_requirement(req("P", "MIN_RECOMMENDED", "4.4444"), D(0))
    with pytest.raises(TypeError):
        daily_requirement("P", D(1000))  # type: ignore[arg-type]


def test_profile_requirements_must_be_collection() -> None:
    with pytest.raises(TypeError):
        replace(std_profile(), requirements="CA")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        replace(std_profile(), requirements=req("SYN_M", "AI", "1.1111"))  # type: ignore[arg-type]
