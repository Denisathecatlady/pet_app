"""Celý rozbor dávky (docs/06 §6.1, §6.9, §6.10) přes ``analyze_recipe``.

Referenční příklad SYN_A/SYN_B je z docs/06 §6.10 (syntetické suroviny).
Standard TESTSTD, pravidla, zdravotní stavy a prahy jsou SYNTETICKÉ fixtury;
nejde o požadavky FEDIAF, NRC ani AAFCO.
"""

import json
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nutricalc import ENGINE_VERSION
from nutricalc.analysis import AnalysisResult, analyze_recipe, result_hash
from nutricalc.composition import IngredientProfile, NutrientValue, RecipeItem
from nutricalc.errors import (
    InvalidInputError,
    SpeciesMismatchError,
    UnsupportedMethodError,
    ValidationError,
)
from nutricalc.evaluation import NutrientStatus, SummaryStatus, format_coverage
from nutricalc.gate import HealthConditionRef
from nutricalc.rules import (
    Always,
    CategoryMassShareAbove,
    IngredientFlagPresent,
    NutrientStatusIn,
    WarningRule,
)
from nutricalc.snapshot import canonical_json, input_hash
from nutricalc.vocab import (
    Completeness,
    GateStatus,
    LifeStage,
    MeMethod,
    PhysiologicalState,
    QualityGrade,
    RequirementType,
    Species,
    ValueKind,
    WarningLevel,
)
from tests.nutricalc.synthetic import (
    DEFAULT_MANDATORY,
    RULES_VERSION,
    analysis_input,
    animal,
    below_lod,
    cat_factor,
    dog_factor,
    golden_items,
    item,
    measured,
    missing,
    profile,
    req,
    std_pair,
    std_requirements,
    syn_a,
    syn_b,
    zero,
)

D = Decimal
S = NutrientStatus
ME_GOLDEN = D("506.688")
VERSIONS_WITH_RULES = (
    ("INGREDIENTS", "syn-1"),
    ("STANDARDS", "teststd-1"),
    ("ENERGY", "test-1"),
    ("RULES", RULES_VERSION),
)


def with_requirements(
    high: list | None = None, low: list | None = None, mandatory: object = DEFAULT_MANDATORY
) -> dict[str, object]:
    high_profile, low_profile = std_pair(high=high, low=low, mandatory=mandatory)  # type: ignore[arg-type]
    return {"high_profile": high_profile, "low_profile": low_profile}


def replaced(column: str, code: str, kind: RequirementType, value: str) -> list:
    """Výchozí syntetické požadavky sloupce s jednou nahrazenou hodnotou."""
    result = [
        r for r in std_requirements(column) if (r.nutrient_code, r.requirement_type) != (code, kind)
    ]
    return [*result, req(code, kind, value)]


def rule(
    code: str, condition: object, level: WarningLevel = WarningLevel.INFO, **extra: object
) -> WarningRule:
    return WarningRule(
        code=code,
        level=level,
        message_cs=f"Syntetické upozornění {code}.",
        source_key="TEST_FIXTURE",
        condition=condition,  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )


def analyze(**overrides: object) -> AnalysisResult:
    return analyze_recipe(analysis_input(**overrides))


# --- referenční příklad docs/06 §6.10 ---------------------------------------------------------------


def test_golden_example_energy_and_phosphorus() -> None:
    result = analyze()
    assert result.me.kcal == ME_GOLDEN
    assert result.me.completeness == Completeness.COMPLETE
    phosphorus = result.nutrient("P")
    assert phosphorus.total.completeness == Completeness.COMPLETE
    assert phosphorus.total.point == D("3.1")
    assert phosphorus.per_1000kcal is not None
    assert phosphorus.per_1000kcal.point == D("3.1") * D(1000) / ME_GOLDEN
    assert str(phosphorus.per_1000kcal.point).startswith("6.118")
    assert phosphorus.status == S.ADEQUATE
    assert phosphorus.missing_energy_share == 0
    assert phosphorus.confidence == QualityGrade.B


def test_golden_example_calcium_partial_min_met() -> None:
    # Syntetické minimum Ca 3,333 g / 1000 kcal: dolní mez 9,868… ho splní i bez dat SYN_A.
    calcium = analyze().nutrient("CA")
    assert calcium.total.completeness == Completeness.PARTIAL
    assert calcium.total.lower == D("5.0") and calcium.total.upper is None
    assert calcium.total.missing_mass_share == D(300) / D(350)
    assert format_coverage(calcium.total.missing_mass_share * 100, 1) == "85,7 %"
    assert calcium.missing_energy_share == 1
    assert calcium.per_1000kcal is not None and calcium.per_1000kcal.upper is None
    assert calcium.status == S.MIN_MET_PARTIAL
    assert calcium.evaluation is not None
    assert calcium.evaluation.coverage_high_pct is None


def test_golden_example_calcium_partial_not_evaluable() -> None:
    # Syntetické minimum 12,345 g / 1000 kcal je nad dolní mezí 9,868… → nelze vyhodnotit.
    overrides = with_requirements(
        high=replaced("high", "CA", RequirementType.MIN_RECOMMENDED, "12.345")
    )
    result = analyze(**overrides)
    calcium = result.nutrient("CA")
    assert calcium.status == S.NOT_EVALUABLE
    assert calcium.evaluation is not None and calcium.evaluation.coverage_low_pct is None
    assert result.summary.status == SummaryStatus.INCOMPLETE
    assert result.summary.not_evaluated == ("CA",)
    assert (result.summary.evaluated_count, result.summary.required_count) == (2, 3)


def test_golden_example_ratio_not_evaluable() -> None:
    ratio = analyze().ratio("CA_P")
    assert ratio.interval is None
    assert ratio.status == S.NOT_EVALUABLE


def test_golden_example_below_lod_variant() -> None:
    result = analyze(items=golden_items(below_lod("0.005")))
    calcium = result.nutrient("CA")
    assert calcium.total.completeness == Completeness.COMPLETE
    assert (calcium.total.lower, calcium.total.upper) == (D("5.0"), D("5.015"))
    ratio = result.ratio()
    assert ratio.interval is not None
    assert ratio.interval.lower == D("5.0") / D("3.1")
    assert ratio.interval.upper == D("5.015") / D("3.1")
    assert str(ratio.interval.lower).startswith("1.6129")
    assert str(ratio.interval.upper).startswith("1.6177")
    # syntetické RATIO_MAX 1,615 leží uvnitř intervalu → na hranici
    assert ratio.status == S.BORDERLINE_MAX
    assert result.summary.status == SummaryStatus.BORDERLINE


def test_golden_example_summary_and_metadata() -> None:
    result = analyze()
    assert result.summary.status == SummaryStatus.ALL_EVALUATED_MET
    assert "TESTSTD 1 (pes, dospělý, udržovací potřeba)" in result.summary.message_cs
    assert "neznamená, že dávka je bezpečná" in result.summary.message_cs
    assert result.gate.status == GateStatus.OK
    assert result.engine_version == ENGINE_VERSION
    assert result.data_versions == analysis_input().data_versions
    assert [n.nutrient_code for n in result.nutrients] == ["CA", "P", "PROTEIN"]
    column = result.selected_column
    assert column is not None
    assert column.life_stage == LifeStage.ADULT_MAINTENANCE
    assert column.k_actual == D(110) and column.min_scale_factor == D(1)
    der = result.energy.kcal_point
    assert der is not None
    assert result.energy_deviation_pct == (ME_GOLDEN - der) / der * 100


def test_mandatory_ratio_not_evaluable_makes_summary_incomplete() -> None:
    result = analyze(**with_requirements(mandatory=DEFAULT_MANDATORY | {"CA_P"}))
    assert result.summary.status == SummaryStatus.INCOMPLETE
    assert result.summary.not_evaluated == ("CA_P",)


def test_mandatory_min_met_partial_with_maximum_is_incomplete() -> None:
    high = [*std_requirements("high"), req("CA", RequirementType.NUTRITIONAL_MAX, "33.33")]
    low = [*std_requirements("low"), req("CA", RequirementType.NUTRITIONAL_MAX, "33.33")]
    result = analyze(**with_requirements(high, low))
    assert result.nutrient("CA").status == S.MIN_MET_PARTIAL
    assert result.summary.status == SummaryStatus.INCOMPLETE


# --- výběr sloupce a přepočet --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("k", "life_stage", "factor"),
    [
        ("120", LifeStage.ADULT_MAINTENANCE, D(1)),
        ("100", LifeStage.ADULT_MAINTENANCE_LOW, D(1)),
        ("80", LifeStage.ADULT_MAINTENANCE_LOW, D("1.1875")),
    ],
)
def test_column_selection_in_analysis(k: str, life_stage: LifeStage, factor: Decimal) -> None:
    result = analyze(energy_factor=dog_factor(k))
    assert result.selected_column is not None
    assert result.selected_column.life_stage == life_stage
    assert result.selected_column.min_scale_factor == factor
    codes = {flag.code for flag in result.flags}
    assert ("REQUIREMENT_SCALING_NEEDS_REVIEW" in codes) == (factor != 1)


def test_only_minima_are_scaled_in_analysis() -> None:
    result = analyze(energy_factor=dog_factor("80"))
    phosphorus = {r.requirement_type: r.value for r in result.nutrient("P").requirements}
    assert phosphorus[RequirementType.MIN_RECOMMENDED] == D("5.003") * D("1.1875")
    assert phosphorus[RequirementType.NUTRITIONAL_MAX] == D("7.777")
    ratio = result.ratio().evaluation
    assert ratio is not None
    assert {r.value for r in ratio.requirements} == {D("1.234"), D("1.615")}


def test_conditional_requirements_are_flagged_not_applied() -> None:
    conditional = req("PROTEIN", RequirementType.MR, "99.99", condition_note="syntetická podmínka")
    result = analyze(**with_requirements([*std_requirements("high"), conditional]))
    protein = result.nutrient("PROTEIN")
    assert conditional not in protein.requirements
    assert protein.status == S.ADEQUATE
    flags = [flag for flag in result.flags if flag.code == "REQUIREMENT_CONDITION_NOT_APPLIED"]
    assert [flag.subject for flag in flags] == ["PROTEIN"]


# --- chybějící data nikdy nejsou nula --------------------------------------------------------------------


def test_nutrient_missing_everywhere_is_not_evaluable() -> None:
    high = [
        *std_requirements("high"),
        req("ZN", RequirementType.MIN_RECOMMENDED, "1.2345", unit="mg"),
    ]
    low = [
        *std_requirements("low"),
        req("ZN", RequirementType.MIN_RECOMMENDED, "1.2345", unit="mg"),
    ]
    result = analyze(**with_requirements(high, low, DEFAULT_MANDATORY | {"ZN"}))
    zinc = result.nutrient("ZN")
    assert zinc.total.completeness == Completeness.UNKNOWN
    assert zinc.status == S.NOT_EVALUABLE
    assert zinc.evaluation is not None and zinc.evaluation.coverage_low_pct is None
    assert zinc.confidence is None
    assert zinc.total.missing_mass_share == 1
    assert result.summary.status == SummaryStatus.INCOMPLETE


calcium_values = st.one_of(
    st.just(missing()),
    st.integers(0, 2000).map(lambda n: measured(str(D(n).scaleb(-2)))),
    st.integers(1, 100).map(lambda n: below_lod(str(D(n).scaleb(-3)))),
    st.just(zero()),
)


@st.composite
def recipes(draw: st.DrawFn, force_missing_ca: bool = False) -> list[RecipeItem]:
    count = draw(st.integers(1, 5))
    entries = []
    missing_index = draw(st.integers(0, count - 1)) if force_missing_ca else -1
    for index in range(count):
        values: dict[str, NutrientValue] = {
            "PROTEIN": measured(str(D(draw(st.integers(0, 300))).scaleb(-1))),
            "FAT": measured(str(D(draw(st.integers(0, 300))).scaleb(-1))),
            "NFE": zero(),
            "CRUDE_FIBRE": zero(),
            "P": measured(str(D(draw(st.integers(0, 500))).scaleb(-2))),
            "CA": missing() if index == missing_index else draw(calcium_values),
        }
        grams = D(draw(st.integers(1, 5000))).scaleb(-1)
        entries.append(RecipeItem(profile(f"SYN_{index:02d}", values), grams))
    return entries


@given(recipes(force_missing_ca=True), st.integers(1, 3000).map(lambda n: str(D(n).scaleb(-2))))
def test_missing_calcium_never_becomes_deficit(items: list[RecipeItem], ca_min: str) -> None:
    overrides = with_requirements(
        high=replaced("high", "CA", RequirementType.MIN_RECOMMENDED, ca_min),
        low=replaced("low", "CA", RequirementType.MIN_RECOMMENDED, str(D(ca_min) * 2)),
    )
    result = analyze(items=tuple(items), **overrides)
    calcium = result.nutrient("CA")
    assert calcium.total.completeness in (Completeness.PARTIAL, Completeness.UNKNOWN)
    assert calcium.evaluation is not None
    assert S.BELOW_MIN not in calcium.evaluation.all_statuses
    assert S.BORDERLINE_MIN not in calcium.evaluation.all_statuses
    assert calcium.status in (S.NOT_EVALUABLE, S.MIN_MET_PARTIAL)
    if calcium.status == S.NOT_EVALUABLE:
        assert calcium.evaluation.coverage_low_pct is None
    assert result.ratio().interval is None
    assert (
        result.summary.status != SummaryStatus.ALL_EVALUATED_MET
        or calcium.status == S.MIN_MET_PARTIAL
    )


# --- energie dávky neznámá ----------------------------------------------------------------------------


def test_unknown_ration_energy_makes_everything_not_evaluable() -> None:
    no_fat = profile("SYN_A", {"PROTEIN": measured("20"), "P": measured("0.2"), "CA": zero()})
    result = analyze(items=(item(no_fat, "300"), item(syn_b(), "50")))
    assert result.me.kcal is None
    assert {flag.code for flag in result.flags} >= {"ME_NOT_AVAILABLE"}
    for nutrient in result.nutrients:
        assert nutrient.per_1000kcal is None
        assert nutrient.status == S.NOT_EVALUABLE
    assert result.ratio().interval is not None  # poměr na energii nezávisí
    assert result.summary.status == SummaryStatus.INCOMPLETE
    assert result.energy_deviation_pct is None
    assert result.nutrient("P").missing_energy_share is None


def test_zero_ration_energy_is_not_evaluable() -> None:
    result = analyze(items=(item(syn_b(), "50"),))
    assert result.me.kcal == 0
    assert all(n.status == S.NOT_EVALUABLE for n in result.nutrients)
    assert result.nutrient("P").missing_energy_share is None


def test_partial_ration_energy_is_flagged() -> None:
    no_nfe = profile(
        "SYN_A",
        {
            "PROTEIN": measured("20"),
            "FAT": measured("10"),
            "CRUDE_FIBRE": zero(),
            "P": measured("0.2"),
        },
    )
    result = analyze(items=(item(no_nfe, "300"), item(syn_b(), "50")))
    assert result.me.completeness == Completeness.PARTIAL
    assert "ME_PARTIAL" in {flag.code for flag in result.flags}
    assert result.nutrient("P").status == S.ADEQUATE


# --- bezpečnostní brána ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [PhysiologicalState.GROWTH, PhysiologicalState.GESTATION, PhysiologicalState.LACTATION],
)
def test_unsupported_state_is_blocked_with_descriptive_totals(state: PhysiologicalState) -> None:
    result = analyze(animal=animal(physiological_state=state))
    assert result.gate.status == GateStatus.BLOCKED
    assert result.summary.status == SummaryStatus.BLOCKED
    assert result.energy.kcal_point is None
    assert result.selected_column is None
    assert result.me.kcal == ME_GOLDEN
    phosphorus = result.nutrient("P")
    assert phosphorus.total.point == D("3.1") and phosphorus.per_1000kcal is not None
    for nutrient in result.nutrients:
        assert nutrient.evaluation is None and nutrient.requirements == ()
        assert nutrient.status is None
    assert result.ratio().evaluation is None
    assert result.summary.evaluated_count == 0


@pytest.mark.parametrize(
    ("bcs", "gate_status"),
    [
        (1, GateStatus.BLOCKED),
        (2, GateStatus.BLOCKED),
        (3, GateStatus.EXPERT_REQUIRED),
        (4, GateStatus.OK),
        (5, GateStatus.OK),
        (6, GateStatus.EXPERT_REQUIRED),
        (9, GateStatus.EXPERT_REQUIRED),
        (None, GateStatus.OK),
    ],
)
def test_bcs_policy(bcs: int | None, gate_status: GateStatus) -> None:
    result = analyze(animal=animal(bcs=bcs))
    assert result.gate.status == gate_status
    if gate_status == GateStatus.BLOCKED:
        assert result.summary.status == SummaryStatus.BLOCKED
        assert result.energy.kcal_point is None
        assert all(n.evaluation is None for n in result.nutrients)
    else:
        # EXPERT_REQUIRED: čísla se spočítají a vyhodnotí, rozhodnutí je na odborníkovi
        assert result.summary.status == SummaryStatus.ALL_EVALUATED_MET
        assert all(n.evaluation is not None for n in result.nutrients)
    if bcs is None:
        assert "BCS_MISSING" in {flag.code for flag in result.energy.flags}


def test_blocking_health_condition() -> None:
    result = analyze(
        animal=animal(health_conditions=(HealthConditionRef("SYN_CKD", WarningLevel.BLOCKED),))
    )
    assert result.gate.status == GateStatus.BLOCKED
    assert result.summary.status == SummaryStatus.BLOCKED
    assert result.energy.kcal_point is not None  # energie se spočítá, požadavky ne
    assert result.selected_column is None
    assert all(n.evaluation is None for n in result.nutrients)


def test_toxic_ingredient_rule_blocks() -> None:
    onion = profile(
        "SYN_TOXIC",
        {"PROTEIN": zero(), "FAT": zero(), "NFE": zero(), "CRUDE_FIBRE": zero()},
        safety_flags={"TOXIC_FOR_DOG"},
    )
    rules = (
        rule(
            "TOXIC_FOR_SPECIES",
            IngredientFlagPresent("TOXIC_FOR_DOG"),
            WarningLevel.BLOCKED,
            species={Species.DOG},
        ),
        rule("RAW_DIET", Always()),
        rule("P_STATUS", NutrientStatusIn("P", frozenset({S.ADEQUATE, S.MIN_MET_PARTIAL}))),
    )
    unblocked = analyze(
        items=golden_items(), warning_rules=rules, data_versions=VERSIONS_WITH_RULES
    )
    assert [w.code for w in unblocked.warnings] == ["P_STATUS", "RAW_DIET"]
    result = analyze(
        items=(*golden_items(), item(onion, "5")),
        warning_rules=rules,
        data_versions=VERSIONS_WITH_RULES,
    )
    assert result.gate.status == GateStatus.BLOCKED
    assert result.gate.reasons[0].code == "TOXIC_FOR_SPECIES"
    assert result.gate.reasons[0].subject == "SYN_TOXIC"
    # při blokaci zůstanou jen upozornění nezávislá na stavech živin
    assert [w.code for w in result.warnings] == ["TOXIC_FOR_SPECIES", "RAW_DIET"]
    assert result.flags == unblocked.flags == ()
    assert result.summary.status == SummaryStatus.BLOCKED


def test_expert_rule_keeps_evaluation() -> None:
    gland = profile(
        "SYN_NECK",
        {
            "PROTEIN": zero(),
            "FAT": zero(),
            "NFE": zero(),
            "CRUDE_FIBRE": zero(),
            "P": zero(),
            "CA": zero(),
        },
        safety_flags={"THYROID_TISSUE"},
    )
    rules = (
        rule(
            "THYROID_TISSUE", IngredientFlagPresent("THYROID_TISSUE"), WarningLevel.EXPERT_REQUIRED
        ),
    )
    result = analyze(
        items=(*golden_items(), item(gland, "5")),
        warning_rules=rules,
        data_versions=VERSIONS_WITH_RULES,
    )
    assert result.gate.status == GateStatus.EXPERT_REQUIRED
    assert all(n.evaluation is not None for n in result.nutrients)


def test_rules_see_nutrient_and_ratio_statuses() -> None:
    rules = (
        rule(
            "CA_P_RANGE",
            NutrientStatusIn(
                "CA_P", frozenset({S.BELOW_MIN, S.BORDERLINE_MIN, S.BORDERLINE_MAX, S.ABOVE_MAX})
            ),
            WarningLevel.NUTRITION_WARNING,
        ),
        rule("MINERAL_SHARE", CategoryMassShareAbove("TEST", D("0.5"))),
    )
    result = analyze(
        items=golden_items(below_lod("0.005")),
        warning_rules=rules,
        data_versions=VERSIONS_WITH_RULES,
    )
    assert [w.code for w in result.warnings] == ["CA_P_RANGE", "MINERAL_SHARE"]
    assert result.warnings[1].ingredient_codes == ("SYN_A", "SYN_B")


# --- kočka ----------------------------------------------------------------------------------------------


def cat_input(**overrides: object) -> object:
    high, low = std_pair(Species.CAT)
    fields: dict[str, object] = {
        "animal": animal(species=Species.CAT, body_weight_kg=D(4)),
        "energy_factor": cat_factor(),
        "high_profile": high,
        "low_profile": low,
        "me_method": MeMethod.MOD_ATWATER,
    }
    fields.update(overrides)
    return analysis_input(**fields)


def test_cat_without_taurine_data_is_never_met() -> None:
    requirements = [
        *std_requirements("high"),
        req("TAURINE", RequirementType.MIN_RECOMMENDED, "0.123"),
    ]
    low = [*std_requirements("low"), req("TAURINE", RequirementType.MIN_RECOMMENDED, "0.123")]
    high_profile, low_profile = std_pair(
        Species.CAT, requirements, low, DEFAULT_MANDATORY | {"TAURINE"}
    )
    result = analyze_recipe(cat_input(high_profile=high_profile, low_profile=low_profile))  # type: ignore[arg-type]
    assert result.nutrient("TAURINE").status == S.NOT_EVALUABLE
    assert result.summary.status == SummaryStatus.INCOMPLETE
    assert result.summary.not_evaluated == ("TAURINE",)


def test_cat_analysis_uses_cat_columns() -> None:
    result = analyze_recipe(cat_input())  # type: ignore[arg-type]
    assert result.selected_column is not None
    assert result.selected_column.species == Species.CAT
    assert result.selected_column.k_actual == D(100)


# --- neplatný vstup ---------------------------------------------------------------------------------------


def test_cat_profile_cannot_be_used_for_dog() -> None:
    high, low = std_pair(Species.CAT)
    with pytest.raises(SpeciesMismatchError):
        analyze(high_profile=high, low_profile=low)


def test_dog_profile_cannot_be_used_for_cat() -> None:
    high, low = std_pair(Species.DOG)
    with pytest.raises(SpeciesMismatchError):
        analyze_recipe(cat_input(high_profile=high, low_profile=low))  # type: ignore[arg-type]


def test_cat_energy_factor_cannot_be_used_for_dog() -> None:
    with pytest.raises(SpeciesMismatchError):
        analyze(energy_factor=cat_factor())


def test_mixed_species_profiles_are_rejected() -> None:
    dog_high, _ = std_pair(Species.DOG)
    _, cat_low = std_pair(Species.CAT)
    with pytest.raises(SpeciesMismatchError):
        analyze(high_profile=dog_high, low_profile=cat_low)


def test_profile_for_other_life_stage_is_rejected() -> None:
    with pytest.raises(SpeciesMismatchError):
        analyze(animal=animal(life_stage=LifeStage.LATE_GROWTH))


def test_low_life_stage_animal_is_accepted() -> None:
    result = analyze(animal=animal(life_stage=LifeStage.ADULT_MAINTENANCE_LOW))
    assert result.gate.status == GateStatus.OK


def test_engine_version_must_match() -> None:
    with pytest.raises(ValidationError, match="verzi jádra"):
        analyze(engine_version="0.0.1")


@pytest.mark.parametrize(
    "versions",
    [
        (("INGREDIENTS", "syn-1"), ("STANDARDS", "teststd-2"), ("ENERGY", "test-1")),
        (("INGREDIENTS", "syn-1"), ("STANDARDS", "teststd-1"), ("ENERGY", "test-2")),
        (("INGREDIENTS", "syn-1"), ("ENERGY", "test-1")),
        (("STANDARDS", "teststd-1"), ("ENERGY", "test-1")),
    ],
)
def test_data_versions_must_match_data(versions: tuple) -> None:
    with pytest.raises(ValidationError):
        analyze(data_versions=versions)


def test_rules_require_rules_version() -> None:
    with pytest.raises(ValidationError, match="RULES"):
        analyze(warning_rules=(rule("RAW_DIET", Always()),))


def test_profiles_from_different_data_versions_are_rejected() -> None:
    high, low = std_pair()
    with pytest.raises(ValidationError):
        analyze(high_profile=high, low_profile=replace(low, data_version="teststd-0"))


def test_unknown_ratio_is_rejected() -> None:
    extra = [req("ZN_CU", RequirementType.RATIO_MAX, "9.9")]
    with pytest.raises(ValidationError, match="ZN_CU"):
        analyze(
            **with_requirements(
                [*std_requirements("high"), *extra], [*std_requirements("low"), *extra]
            )
        )


def test_input_errors_from_energy_and_me_propagate() -> None:
    with pytest.raises(InvalidInputError):
        analyze(animal=animal(body_weight_kg=D(200)))
    with pytest.raises(UnsupportedMethodError):
        analyze(me_method=MeMethod.NRC2006_CAT)
    with pytest.raises(TypeError):
        analyze_recipe("snapshot")  # type: ignore[arg-type]


# --- determinismus a reprodukovatelnost ------------------------------------------------------------------


def test_same_input_gives_identical_result_and_hashes() -> None:
    first = analyze()
    second = analyze()
    assert first == second
    assert first.input_hash == second.input_hash == input_hash(analysis_input())
    assert first.result_hash == second.result_hash == result_hash(first)
    assert len(first.result_hash) == 64


def test_result_hash_covers_result_without_itself() -> None:
    result = analyze()
    text = canonical_json(result, exclude=frozenset({"result_hash"}))
    data = json.loads(text, parse_float=lambda value: pytest.fail(f"float v JSON: {value}"))
    assert "result_hash" not in data and data["input_hash"] == result.input_hash
    assert "computed_at" not in text
    tampered = replace(result, summary=replace(result.summary, message_cs="Jiná věta."))
    assert result_hash(tampered) != result.result_hash


def test_permuted_items_give_same_hashes() -> None:
    forward = analyze()
    backward = analyze(items=tuple(reversed(golden_items())))
    assert backward == forward
    assert (backward.input_hash, backward.result_hash) == (forward.input_hash, forward.result_hash)


def test_different_method_or_data_gives_different_hashes() -> None:
    base = analyze()
    atwater = analyze(me_method=MeMethod.MOD_ATWATER)
    assert atwater.input_hash != base.input_hash
    assert atwater.result_hash != base.result_hash
    assert atwater.me.kcal == D("465.0")  # 3 × 155,0 kcal (docs/06 §6.3)


@given(recipes(), st.randoms(use_true_random=False))
def test_analysis_does_not_depend_on_item_order(items: list[RecipeItem], shuffler: object) -> None:
    shuffled = items[:]
    shuffler.shuffle(shuffled)  # type: ignore[attr-defined]
    first = analyze(items=tuple(items))
    second = analyze(items=tuple(shuffled))
    assert first == second
    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash


def test_analysis_does_not_depend_on_global_decimal_context() -> None:
    expected = analyze(items=golden_items(below_lod("0.005")), energy_factor=dog_factor("80"))
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps = dict.fromkeys(context.traps, False)  # type: ignore[assignment]
        assert (
            analyze(items=golden_items(below_lod("0.005")), energy_factor=dog_factor("80"))
            == expected
        )


def test_quality_of_contributors_drives_confidence() -> None:
    poor_b = IngredientProfile(
        "SYN_B",
        "SYN_B@test-1",
        "TEST",
        frozenset(),
        {
            **dict(syn_b().values),
            "P": NutrientValue(D("5.0"), ValueKind.MEASURED, quality=QualityGrade.D),
        },
    )
    result = analyze(items=(item(syn_a(), "300"), item(poor_b, "50")))
    # SYN_B dává 2,5 g z 3,1 g P (> práh 0,1) → spolehlivost D
    assert result.nutrient("P").confidence == QualityGrade.D


def test_result_lookup_helpers() -> None:
    result = analyze()
    with pytest.raises(KeyError):
        result.nutrient("ZN")
    with pytest.raises(KeyError):
        result.ratio("ZN_CU")
    with pytest.raises(TypeError):
        result_hash("result")  # type: ignore[arg-type]


def test_conditional_ratio_requirement_is_flagged() -> None:
    conditional = req(
        "CA_P", RequirementType.RATIO_MAX, "1.9123", condition_note="syntetická podmínka"
    )
    result = analyze(**with_requirements([*std_requirements("high"), conditional]))
    flags = [flag for flag in result.flags if flag.code == "REQUIREMENT_CONDITION_NOT_APPLIED"]
    assert [flag.subject for flag in flags] == ["CA_P"]


def test_ratio_components_need_same_unit() -> None:
    def columns(column: str) -> list:
        kept = [r for r in std_requirements(column) if r.nutrient_code != "CA"]
        return [*kept, req("CA", RequirementType.MIN_RECOMMENDED, "3333", unit="mg")]

    with pytest.raises(ValidationError, match="stejnou jednotku"):
        analyze(**with_requirements(columns("high"), columns("low")))


def test_ratio_components_without_own_requirement_use_grams() -> None:
    only_ratio = [req("CA_P", RequirementType.RATIO_MAX, "1.9123")]
    result = analyze(**with_requirements(only_ratio, only_ratio, mandatory=()))
    assert [n.nutrient_code for n in result.nutrients] == ["CA", "P"]
    assert all(n.status == S.NO_REFERENCE for n in result.nutrients)
    assert result.ratio().status == S.NOT_EVALUABLE  # Ca je PARTIAL
    # nic se nevyhodnotilo → nikdy „splněno“
    assert result.summary.status == SummaryStatus.INCOMPLETE
