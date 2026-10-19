"""Vyhodnocení živin, zobrazení pokrytí, poměr Ca:P, spolehlivost a souhrn (docs/06 §6.6).

Hodnoty požadavků jsou SYNTETICKÉ (živina ``SYN_N``, standard TESTSTD).
Reálná čísla jsou jen z příkladu docs/06 §6.10 (Ca 5,0 g, P 3,1 g, LOD 0,005 g,
ME 506,688 kcal).
"""

from decimal import Decimal

import pytest

from nutricalc.composition import NutrientTotal, sum_nutrient
from nutricalc.errors import (
    BasisMismatchError,
    InvalidInputError,
    UnitMismatchError,
    ValidationError,
)
from nutricalc.evaluation import (
    STATUS_LABELS,
    STATUS_PRIORITY,
    NutrientInterval,
    NutrientStatus,
    QualityContributor,
    RatioInterval,
    SummaryStatus,
    confidence,
    evaluate_nutrient,
    evaluate_ratio,
    format_coverage,
    format_decimal_cs,
    met_message,
    no_data_evaluation,
    per_1000kcal_interval,
    profile_label,
    ratio_interval,
    summarize,
)
from nutricalc.requirements import Requirement
from nutricalc.vocab import (
    MAXIMUM_TYPES,
    MINIMUM_TYPES,
    RATIO_TYPES,
    Basis,
    Completeness,
    GateStatus,
    QualityGrade,
    RequirementType,
    Species,
    Unit,
)
from tests.nutricalc.synthetic import (
    below_lod,
    golden_items,
    item,
    measured,
    missing,
    profile,
    req,
    std_profile,
    syn_a,
    syn_b,
    zero,
)

D = Decimal
S = NutrientStatus
CODE = "SYN_N"
COMPLETE, PARTIAL, UNKNOWN = Completeness.COMPLETE, Completeness.PARTIAL, Completeness.UNKNOWN


def interval(
    lower: str,
    upper: str | None = None,
    completeness: Completeness = COMPLETE,
    point: str | None = None,
    unit: Unit = Unit.G,
    basis: Basis = Basis.PER_1000KCAL_ME,
) -> NutrientInterval:
    """Obsah SYN_N na 1000 kcal; u COMPLETE bez horní meze je interval bodový."""
    if completeness == COMPLETE and upper is None:
        upper = lower
    return NutrientInterval(
        nutrient_code=CODE,
        unit=unit,
        basis=basis,
        lower=D(lower),
        upper=None if upper is None else D(upper),
        point=None if point is None else D(point),
        completeness=completeness,
    )


def minimum(value: str = "10", kind: str = "MIN_RECOMMENDED") -> Requirement:
    return req(CODE, kind, value)


def maximum(value: str = "50", kind: str = "NUTRITIONAL_MAX") -> Requirement:
    return req(CODE, kind, value)


# --- NutrientInterval ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lower", "upper", "point", "completeness"),
    [
        ("5", None, None, COMPLETE),
        ("5", "4", None, COMPLETE),
        ("5", "6", "7", COMPLETE),
        ("5", "6", None, PARTIAL),
        ("5", None, "5", PARTIAL),
        ("0", "1", None, UNKNOWN),
    ],
)
def test_interval_rejects_inconsistent_bounds(
    lower: str, upper: str | None, point: str | None, completeness: Completeness
) -> None:
    with pytest.raises(ValidationError):
        NutrientInterval(
            nutrient_code=CODE,
            unit=Unit.G,
            basis=Basis.PER_1000KCAL_ME,
            lower=D(lower),
            upper=None if upper is None else D(upper),
            point=None if point is None else D(point),
            completeness=completeness,
        )


def test_interval_rejects_float_and_negative() -> None:
    with pytest.raises(TypeError):
        interval("1").__class__(
            nutrient_code=CODE,
            unit=Unit.G,
            basis=Basis.PER_1000KCAL_ME,
            lower=1.0,  # type: ignore[arg-type]
            upper=None,
            point=None,
            completeness=PARTIAL,
        )
    with pytest.raises(InvalidInputError):
        interval("-1", completeness=PARTIAL)


def test_per_1000kcal_interval_golden_phosphorus() -> None:
    # docs/06 §6.10: P 3,1 g/den při ME 506,688 kcal = 6,118… g / 1000 kcal
    total = sum_nutrient(golden_items(), "P", Unit.G)
    result = per_1000kcal_interval(total, D("506.688"))
    assert result.completeness == COMPLETE and result.basis == Basis.PER_1000KCAL_ME
    assert result.lower == result.upper == result.point
    assert result.point == D("3.1") * D(1000) / D("506.688")
    assert str(result.point).startswith("6.118163445749652")


def test_per_1000kcal_interval_partial_keeps_only_lower_bound() -> None:
    total = sum_nutrient(golden_items(), "CA", Unit.G)
    result = per_1000kcal_interval(total, D("506.688"))
    assert result.completeness == PARTIAL
    assert result.upper is None and result.point is None
    assert result.lower == D("5.0") * D(1000) / D("506.688")


def test_per_1000kcal_interval_rejects_non_positive_energy() -> None:
    total = sum_nutrient(golden_items(), "P", Unit.G)
    with pytest.raises(ValidationError):
        per_1000kcal_interval(total, D(0))
    with pytest.raises(TypeError):
        per_1000kcal_interval("P", D(1))  # type: ignore[arg-type]


# --- evaluate_nutrient: pravidla ---------------------------------------------------------------


def statuses(per_1000: NutrientInterval, *requirements: Requirement) -> tuple[NutrientStatus, ...]:
    return evaluate_nutrient(per_1000, requirements).all_statuses


def test_no_requirement_is_no_reference() -> None:
    result = evaluate_nutrient(interval("5"), ())
    assert result.status == S.NO_REFERENCE and result.all_statuses == (S.NO_REFERENCE,)
    assert result.coverage_low_pct is None


def test_unknown_is_not_evaluable_without_numbers() -> None:
    result = evaluate_nutrient(interval("0", completeness=UNKNOWN), (minimum(), maximum()))
    assert result.status == S.NOT_EVALUABLE
    assert result.coverage_low_pct is result.coverage_high_pct is None
    assert result.pct_of_max_low is result.pct_of_max_high is None


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("10", S.ADEQUATE),
        ("9.999999999", S.BELOW_MIN),
        ("10.000000001", S.ADEQUATE),
        ("0", S.BELOW_MIN),
    ],
)
def test_minimum_boundary(content: str, expected: NutrientStatus) -> None:
    # docs/11: hodnota = min → ADEQUATE, min − 1e-9 → BELOW_MIN
    assert evaluate_nutrient(interval(content), (minimum("10"),)).status == expected


@pytest.mark.parametrize(
    ("lower", "upper", "expected"),
    [
        ("5", "9", (S.BELOW_MIN,)),
        ("5", "10", (S.BORDERLINE_MIN,)),
        ("9.99", "12", (S.BORDERLINE_MIN,)),
        ("10", "12", (S.ADEQUATE,)),
        ("40", "50", (S.ADEQUATE,)),
        ("40", "50.001", (S.BORDERLINE_MAX,)),
        ("50", "60", (S.BORDERLINE_MAX,)),
        ("50.001", "60", (S.ABOVE_MAX,)),
        ("5", "60", (S.BORDERLINE_MIN, S.BORDERLINE_MAX)),
    ],
)
def test_complete_interval_rules(
    lower: str, upper: str, expected: tuple[NutrientStatus, ...]
) -> None:
    assert statuses(interval(lower, upper), minimum("10"), maximum("50")) == expected


def test_legal_maximum_is_informative_only() -> None:
    # docs/11: nad zákonným, ale pod nutričním maximem → ABOVE_LEGAL_MAX_INFO
    result = evaluate_nutrient(
        interval("45"), (minimum("10"), maximum("40", "LEGAL_MAX_EU"), maximum("50"))
    )
    assert result.all_statuses == (S.ABOVE_LEGAL_MAX_INFO,)
    assert result.status == S.ABOVE_LEGAL_MAX_INFO


def test_legal_maximum_crossing_is_not_a_status() -> None:
    result = evaluate_nutrient(interval("35", "45"), (maximum("40", "LEGAL_MAX_EU"),))
    assert result.all_statuses == (S.ADEQUATE,)


@pytest.mark.parametrize(
    ("lower", "upper", "expected"),
    [("70", "80", S.ADEQUATE), ("70", "81", S.BORDERLINE_MAX), ("80.5", "90", S.ABOVE_SUL)],
)
def test_sul(lower: str, upper: str, expected: NutrientStatus) -> None:
    assert evaluate_nutrient(interval(lower, upper), (maximum("80", "SUL"),)).status == expected


@pytest.mark.parametrize(
    ("lower", "requirements", "expected"),
    [
        ("12", ("min",), (S.MIN_MET_PARTIAL,)),
        ("10", ("min",), (S.MIN_MET_PARTIAL,)),
        ("9.9", ("min",), (S.NOT_EVALUABLE,)),
        ("0", ("min",), (S.NOT_EVALUABLE,)),
        ("12", ("min", "max"), (S.MIN_MET_PARTIAL,)),
        ("51", ("min", "max"), (S.ABOVE_MAX, S.MIN_MET_PARTIAL)),
        ("20", ("max",), (S.NOT_EVALUABLE,)),
        ("51", ("max",), (S.ABOVE_MAX,)),
        ("81", ("sul",), (S.ABOVE_SUL,)),
        ("45", ("legal",), (S.NOT_EVALUABLE, S.ABOVE_LEGAL_MAX_INFO)),
    ],
)
def test_partial_rules(
    lower: str, requirements: tuple[str, ...], expected: tuple[NutrientStatus, ...]
) -> None:
    available = {
        "min": minimum("10"),
        "max": maximum("50"),
        "sul": maximum("80", "SUL"),
        "legal": maximum("40", "LEGAL_MAX_EU"),
    }
    chosen = [available[name] for name in requirements]
    assert statuses(interval(lower, completeness=PARTIAL), *chosen) == expected


def test_partial_lower_bound_is_never_below_min() -> None:
    # Chybějící údaj není nula: nízká dolní mez PARTIAL nikdy nedá BELOW_MIN.
    for lower in ("0", "1", "9.99"):
        result = evaluate_nutrient(interval(lower, completeness=PARTIAL), (minimum("10"),))
        assert S.BELOW_MIN not in result.all_statuses
        assert S.BORDERLINE_MIN not in result.all_statuses
        assert result.coverage_low_pct is None


def test_coverage_and_percent_of_maximum() -> None:
    result = evaluate_nutrient(interval("5", "30"), (minimum("10"), maximum("40")))
    assert result.coverage_low_pct == D(50) and result.coverage_high_pct == D(300)
    assert result.pct_of_max_low == D("12.5") and result.pct_of_max_high == D(75)


def test_coverage_for_min_met_partial_is_only_lower_bound() -> None:
    result = evaluate_nutrient(interval("15", completeness=PARTIAL), (minimum("10"), maximum("40")))
    assert result.coverage_low_pct == D(150) and result.coverage_high_pct is None
    assert result.pct_of_max_low is None and result.pct_of_max_high is None


def test_percent_of_maximum_for_partial_only_when_certainly_exceeded() -> None:
    result = evaluate_nutrient(interval("60", completeness=PARTIAL), (maximum("40"),))
    assert result.pct_of_max_low == D(150) and result.pct_of_max_high is None


def test_no_coverage_without_minimum() -> None:
    result = evaluate_nutrient(interval("20"), (maximum("40"),))
    assert result.coverage_low_pct is None and result.coverage_high_pct is None
    assert result.pct_of_max_low == D(50)


def test_primary_status_follows_priority() -> None:
    assert STATUS_PRIORITY[:3] == (S.ABOVE_MAX, S.ABOVE_SUL, S.BELOW_MIN)
    assert set(STATUS_PRIORITY) == set(NutrientStatus)
    result = evaluate_nutrient(
        interval("60", completeness=PARTIAL),
        (minimum("10"), maximum("50"), maximum("55", "LEGAL_MAX_EU")),
    )
    assert result.all_statuses == (S.ABOVE_MAX, S.MIN_MET_PARTIAL, S.ABOVE_LEGAL_MAX_INFO)
    assert result.status == S.ABOVE_MAX


def test_status_labels_cover_all_statuses() -> None:
    assert set(STATUS_LABELS) == set(NutrientStatus)
    assert STATUS_LABELS[S.NOT_EVALUABLE] == "Nelze vyhodnotit – chybí data"


# --- záměna typů požadavku -----------------------------------------------------------------

MINIMUM_STATUSES = {S.BELOW_MIN, S.BORDERLINE_MIN, S.MIN_MET_PARTIAL}
MAXIMUM_STATUSES = {S.ABOVE_MAX, S.BORDERLINE_MAX, S.ABOVE_SUL, S.ABOVE_LEGAL_MAX_INFO}


@pytest.mark.parametrize("kind", list(RequirementType))
def test_requirement_type_is_never_confused(kind: RequirementType) -> None:
    """Maximum se nikdy nevyhodnotí jako minimum a naopak (docs/11 §11.2)."""
    if kind in RATIO_TYPES:
        with pytest.raises(ValidationError):
            evaluate_nutrient(interval("1"), (req(CODE, kind, "10"),))
        return
    requirement = req(CODE, kind, "10")
    low = evaluate_nutrient(interval("1"), (requirement,))
    high = evaluate_nutrient(interval("100"), (requirement,))
    partial_high = evaluate_nutrient(interval("100", completeness=PARTIAL), (requirement,))
    found = set(low.all_statuses) | set(high.all_statuses) | set(partial_high.all_statuses)
    if kind in MINIMUM_TYPES:
        assert low.status == S.BELOW_MIN
        assert high.status == S.ADEQUATE
        assert partial_high.status == S.MIN_MET_PARTIAL
        assert not found & MAXIMUM_STATUSES
        assert high.coverage_low_pct == D(1000)
    else:
        assert kind in MAXIMUM_TYPES
        assert low.status == S.ADEQUATE
        assert not found & MINIMUM_STATUSES
        assert low.coverage_low_pct is None and high.coverage_low_pct is None
        expected = {
            RequirementType.NUTRITIONAL_MAX: S.ABOVE_MAX,
            RequirementType.SUL: S.ABOVE_SUL,
            RequirementType.LEGAL_MAX_EU: S.ABOVE_LEGAL_MAX_INFO,
        }[kind]
        assert high.status == expected


@pytest.mark.parametrize("kind", [k for k in RequirementType if k not in RATIO_TYPES])
def test_ratio_evaluation_rejects_nutrient_requirement_types(kind: RequirementType) -> None:
    ca = sum_nutrient(golden_items(zero()), "CA", Unit.G)
    p = sum_nutrient(golden_items(zero()), "P", Unit.G)
    with pytest.raises(ValidationError):
        evaluate_ratio(ca, p, (req("CA_P", kind, "1.0123"),))


# --- evaluate_nutrient: kontrola vstupu ----------------------------------------------------------


def test_unit_and_basis_must_match() -> None:
    with pytest.raises(UnitMismatchError):
        evaluate_nutrient(interval("5", unit=Unit.MG), (minimum(),))
    with pytest.raises(BasisMismatchError):
        evaluate_nutrient(interval("5", basis=Basis.PER_DAY), (minimum(),))


def test_requirement_of_other_nutrient_is_rejected() -> None:
    with pytest.raises(ValidationError):
        evaluate_nutrient(interval("5"), (req("CA", "MIN_RECOMMENDED", "1.1111"),))


def test_two_minima_are_rejected() -> None:
    with pytest.raises(ValidationError):
        evaluate_nutrient(interval("5"), (minimum("1"), minimum("2", "AI")))


def test_condition_note_filters_requirements() -> None:
    conditional = req(CODE, "MIN_RECOMMENDED", "10", condition_note="podmínka X")
    assert evaluate_nutrient(interval("5"), (conditional,)).status == S.NO_REFERENCE
    result = evaluate_nutrient(interval("5"), (conditional,), condition_note="podmínka X")
    assert result.status == S.BELOW_MIN
    assert result.requirements == (conditional,)


def test_evaluate_nutrient_type_errors() -> None:
    with pytest.raises(TypeError):
        evaluate_nutrient("5", (minimum(),))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        evaluate_nutrient(interval("5"), minimum())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        evaluate_nutrient(interval("5"), (minimum(),), condition_note=None)  # type: ignore[arg-type]


def test_no_data_evaluation() -> None:
    assert no_data_evaluation(CODE, (minimum(),)).status == S.NOT_EVALUABLE
    assert no_data_evaluation(CODE, ()).status == S.NO_REFERENCE


def test_evaluation_compares_unrounded_values() -> None:
    # 99,96 % pokrytí: stav BELOW_MIN, zobrazení „< 100 %“ (docs/11 §11.2, docs/09 T5)
    result = evaluate_nutrient(interval("9.996"), (minimum("10"),))
    assert result.status == S.BELOW_MIN
    assert result.coverage_low_pct == D("99.96")
    assert format_coverage(result.coverage_low_pct) == "< 100 %"


# --- zobrazení -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pct", "decimals", "expected"),
    [
        ("99.96", 0, "< 100 %"),
        ("99.5", 0, "< 100 %"),
        ("99.4999", 0, "99 %"),
        ("100", 0, "100 %"),
        ("100.4", 0, "100 %"),
        ("100.5", 0, "100 %"),
        ("101.5", 0, "102 %"),
        ("0", 0, "0 %"),
        ("112.5", 1, "112,5 %"),
        ("99.996", 2, "< 100 %"),
        ("99.994", 2, "99,99 %"),
        ("1234.5", 0, "1 234 %"),
        ("1234567.25", 1, "1 234 567,2 %"),
    ],
)
def test_format_coverage(pct: str, decimals: int, expected: str) -> None:
    assert format_coverage(D(pct), decimals) == expected


def test_format_coverage_rejects_invalid_input() -> None:
    with pytest.raises(TypeError):
        format_coverage(99.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        format_coverage(None)  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        format_coverage(D(-1))
    with pytest.raises(TypeError):
        format_coverage(D(1), True)
    with pytest.raises(InvalidInputError):
        format_coverage(D(1), -1)


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        ("1040.315769903493394631866", 2, "1 040,32"),
        ("393.6389276332443562764657", 2, "393,64"),
        ("-1234.5", 1, "-1 234,5"),
        ("-0.04", 1, "0,0"),
        ("1000", 0, "1 000"),
        ("999", 0, "999"),
        ("0.125", 2, "0,12"),
    ],
)
def test_format_decimal_cs(value: str, decimals: int, expected: str) -> None:
    assert format_decimal_cs(D(value), decimals) == expected


# --- poměr Ca:P ----------------------------------------------------------------------------------


def totals(ca: object = None) -> tuple[NutrientTotal, NutrientTotal]:
    items = golden_items(ca)  # type: ignore[arg-type]
    return sum_nutrient(items, "CA", Unit.G), sum_nutrient(items, "P", Unit.G)


def test_ratio_point_golden() -> None:
    # docs/11: Ca 5,0 g a P 3,1 g → 1,6129…
    ca, p = totals(zero())
    result = ratio_interval(ca, p)
    assert result is not None
    assert result.point == result.lower == result.upper == D("5.0") / D("3.1")
    assert str(result.point).startswith("1.6129032258")


def test_ratio_interval_golden_below_lod() -> None:
    # docs/06 §6.10: SYN_A Ca BELOW_LOD (LOD 0,005 g/100 g) → Ca ∈ [5,000; 5,015]
    ca, p = totals(below_lod("0.005"))
    assert (ca.lower, ca.upper, ca.completeness) == (D("5.0"), D("5.015"), COMPLETE)
    result = ratio_interval(ca, p)
    assert result == RatioInterval(
        lower=D("5.0") / D("3.1"), upper=D("5.015") / D("3.1"), point=None
    )
    assert str(result.lower).startswith("1.6129")
    assert str(result.upper).startswith("1.6177")


def test_ratio_not_computed_for_partial_calcium() -> None:
    ca, p = totals()
    assert ca.completeness == PARTIAL
    assert ratio_interval(ca, p) is None
    evaluation = evaluate_ratio(ca, p, (req("CA_P", "RATIO_MAX", "1.7123"),))
    assert evaluation.status == S.NOT_EVALUABLE and evaluation.interval is None


def test_ratio_with_zero_phosphorus_is_not_evaluable() -> None:
    items = [
        item(profile("SYN_C", {"CA": measured("1"), "P": zero()}), "100"),
    ]
    ca, p = sum_nutrient(items, "CA", Unit.G), sum_nutrient(items, "P", Unit.G)
    assert p.lower == 0 and p.completeness == COMPLETE
    assert ratio_interval(ca, p) is None
    assert evaluate_ratio(ca, p, (req("CA_P", "RATIO_MIN", "1.0123"),)).status == S.NOT_EVALUABLE


def test_ratio_with_phosphorus_lower_bound_zero_is_not_evaluable() -> None:
    items = [item(profile("SYN_C", {"CA": measured("1"), "P": below_lod("0.01")}), "100")]
    ca, p = sum_nutrient(items, "CA", Unit.G), sum_nutrient(items, "P", Unit.G)
    assert p.completeness == COMPLETE and p.lower == 0 and p.upper is not None and p.upper > 0
    assert ratio_interval(ca, p) is None


@pytest.mark.parametrize(
    ("ratio_min", "ratio_max", "expected"),
    [
        ("1.7123", "1.9123", S.BELOW_MIN),
        ("1.615", "1.9123", S.BORDERLINE_MIN),
        ("1.6012", "1.6234", S.ADEQUATE),
        ("1.4123", "1.615", S.BORDERLINE_MAX),
        ("1.2345", "1.6012", S.ABOVE_MAX),
    ],
)
def test_ratio_statuses(ratio_min: str, ratio_max: str, expected: NutrientStatus) -> None:
    ca, p = totals(below_lod("0.005"))  # [1,6129…; 1,6177…]
    result = evaluate_ratio(
        ca, p, (req("CA_P", "RATIO_MIN", ratio_min), req("CA_P", "RATIO_MAX", ratio_max))
    )
    assert result.status == expected
    assert result.all_statuses == (expected,)
    assert (result.numerator_code, result.denominator_code) == ("CA", "P")


def test_ratio_without_requirement_is_no_reference_but_computed() -> None:
    ca, p = totals(zero())
    result = evaluate_ratio(ca, p, ())
    assert result.status == S.NO_REFERENCE and result.interval is not None


def test_ratio_rejects_swapped_or_mismatched_totals() -> None:
    ca, p = totals(zero())
    with pytest.raises(ValidationError):
        evaluate_ratio(p, ca, ())
    with pytest.raises(ValidationError):
        evaluate_ratio(ca, p, (), ratio_code="ZN_CU")
    ca_mg = sum_nutrient(golden_items(zero()), "CA", Unit.MG)
    with pytest.raises(UnitMismatchError):
        evaluate_ratio(ca_mg, p, ())
    with pytest.raises(ValidationError):
        evaluate_ratio(ca, p, (req("CA", "RATIO_MAX", "2.3456"),))
    with pytest.raises(TypeError):
        evaluate_ratio("CA", p, ())  # type: ignore[arg-type]


# --- spolehlivost --------------------------------------------------------------------------------


def contributor(code: str, upper: str, grade: QualityGrade) -> QualityContributor:
    return QualityContributor(code, D(upper), grade)


def test_confidence_is_worst_grade_of_relevant_contributors() -> None:
    contributors = [
        contributor("SYN_A", "90", QualityGrade.B),
        contributor("SYN_B", "9", QualityGrade.C),
        contributor("SYN_C", "1", QualityGrade.D),  # 1 % < práh 0,05
    ]
    assert confidence(contributors, D("0.05")) == QualityGrade.C
    assert confidence(contributors, D("0.01")) == QualityGrade.D  # přesně na prahu se počítá
    assert confidence(contributors, D("0.5")) == QualityGrade.B
    assert confidence(reversed(contributors), D("0.05")) == QualityGrade.C


def test_confidence_edge_cases() -> None:
    assert confidence([], D("0.05")) is None
    zeros = [contributor("SYN_A", "0", QualityGrade.A), contributor("SYN_B", "0", QualityGrade.C)]
    assert confidence(zeros, D("0.05")) == QualityGrade.C
    equal = [
        contributor(f"SYN_{n}", "1", QualityGrade.A if n else QualityGrade.B) for n in range(3)
    ]
    assert confidence(equal, D("0.9")) == QualityGrade.B  # nikdo prahu nedosáhne → všichni


def test_confidence_threshold_is_data_and_validated() -> None:
    with pytest.raises(TypeError):
        confidence([], 0.05)  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        confidence([], D("1.5"))
    with pytest.raises(InvalidInputError):
        confidence([], D("-0.1"))
    with pytest.raises(TypeError):
        confidence([("SYN_A", D(1), QualityGrade.A)], D("0.1"))  # type: ignore[list-item]


# --- souhrn --------------------------------------------------------------------------------------

LABEL = "TESTSTD 1 (pes, dospělý, udržovací potřeba)"
MANDATORY = ("CA", "P")


def summary(
    results: dict[str, NutrientStatus],
    maxima: dict[str, tuple[RequirementType, ...]] | None = None,
    gate: GateStatus = GateStatus.OK,
) -> object:
    return summarize(gate, results, MANDATORY, maxima or {}, standard_label=LABEL)


def test_summary_blocked_wins() -> None:
    result = summary({"CA": S.ADEQUATE, "P": S.ADEQUATE}, gate=GateStatus.BLOCKED)
    assert result.status == SummaryStatus.BLOCKED  # type: ignore[attr-defined]
    assert result.evaluated_count == 0 and result.required_count == 2  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "results",
    [
        {"CA": S.NOT_EVALUABLE, "P": S.ADEQUATE},
        {"P": S.ADEQUATE},
        {"CA": S.NO_REFERENCE, "P": S.ADEQUATE},
        {"CA": S.NOT_EVALUABLE, "P": S.BELOW_MIN},
    ],
)
def test_summary_incomplete_when_mandatory_not_evaluated(
    results: dict[str, NutrientStatus],
) -> None:
    result = summary(results)
    assert result.status == SummaryStatus.INCOMPLETE  # type: ignore[attr-defined]
    assert result.evaluated_count == 1 and result.required_count == 2  # type: ignore[attr-defined]
    assert result.not_evaluated == ("CA",)  # type: ignore[attr-defined]
    assert "vyhodnoceno 1 z 2" in result.message_cs  # type: ignore[attr-defined]


def test_min_met_partial_with_maximum_is_incomplete() -> None:
    results = {"CA": S.MIN_MET_PARTIAL, "P": S.ADEQUATE}
    with_max = summary(results, {"CA": (RequirementType.MIN_RECOMMENDED, RequirementType.SUL)})
    assert with_max.status == SummaryStatus.INCOMPLETE  # type: ignore[attr-defined]
    without_max = summary(results, {"CA": (RequirementType.MIN_RECOMMENDED,)})
    assert without_max.status == SummaryStatus.ALL_EVALUATED_MET  # type: ignore[attr-defined]
    assert without_max.evaluated_count == 2  # type: ignore[attr-defined]


@pytest.mark.parametrize("status", [S.BELOW_MIN, S.ABOVE_MAX, S.ABOVE_SUL])
def test_summary_deficits(status: NutrientStatus) -> None:
    result = summary({"CA": S.ADEQUATE, "P": S.ADEQUATE, "ZN": status})
    assert result.status == SummaryStatus.DEFICITS_OR_EXCESSES  # type: ignore[attr-defined]


@pytest.mark.parametrize("status", [S.BORDERLINE_MIN, S.BORDERLINE_MAX])
def test_summary_borderline(status: NutrientStatus) -> None:
    result = summary({"CA": status, "P": S.ADEQUATE})
    assert result.status == SummaryStatus.BORDERLINE  # type: ignore[attr-defined]


def test_summary_all_evaluated_met_sentence() -> None:
    result = summary(
        {"CA": S.ADEQUATE, "P": S.ABOVE_LEGAL_MAX_INFO, "ZN": S.NOT_EVALUABLE, "CU": S.NO_REFERENCE}
    )
    assert result.status == SummaryStatus.ALL_EVALUATED_MET  # type: ignore[attr-defined]
    message = result.message_cs  # type: ignore[attr-defined]
    assert message == met_message(LABEL)
    assert message.startswith(f"Všechny vyhodnocené požadavky standardu {LABEL} jsou splněny.")
    assert "neznamená, že dávka je bezpečná" in message
    counts = dict(result.status_counts)  # type: ignore[attr-defined]
    assert counts[S.ADEQUATE] == 1 and counts[S.NOT_EVALUABLE] == 1 and counts[S.BELOW_MIN] == 0
    assert [status for status, _ in result.status_counts] == list(STATUS_PRIORITY)  # type: ignore[attr-defined]


def test_profile_label() -> None:
    assert profile_label(std_profile()) == LABEL
    assert profile_label(std_profile("low", Species.CAT)) == (
        "TESTSTD 1 (kočka, dospělý, nízká potřeba energie)"
    )


def test_summarize_validates_input() -> None:
    with pytest.raises(InvalidInputError):
        summarize("GREEN", {}, (), {}, standard_label=LABEL)
    with pytest.raises(InvalidInputError):
        summarize(GateStatus.OK, {"CA": "FINE"}, (), {}, standard_label=LABEL)  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        summarize(GateStatus.OK, [], (), {}, standard_label=LABEL)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        summarize(GateStatus.OK, {}, "CA", {}, standard_label=LABEL)
    with pytest.raises(ValidationError):
        summarize(GateStatus.OK, {}, (), {}, standard_label="")


def test_missing_values_are_not_counted_as_zero_in_sum() -> None:
    # SYN_A bez Ca a SYN_B s Ca: dolní mez je jen příspěvek SYN_B, horní mez neznámá.
    total = sum_nutrient([item(syn_a(missing()), "300"), item(syn_b(), "50")], "CA", Unit.G)
    assert total.completeness == PARTIAL and total.upper is None
    assert total.missing_mass_share == D(300) / D(350)


def test_format_rejects_numbers_too_long_for_display() -> None:
    assert format_coverage(D("1E+25")) == "10 000 000 000 000 000 000 000 000 %"
    with pytest.raises(InvalidInputError):
        format_coverage(D("1E+27"), 2)
    with pytest.raises(InvalidInputError):
        format_decimal_cs(D("1E+30"))


def test_more_type_checks() -> None:
    from dataclasses import replace

    ca, p = totals(zero())
    with pytest.raises(BasisMismatchError):
        ratio_interval(ca, replace(p, basis=Basis.PER_1000KCAL_ME))
    with pytest.raises(TypeError):
        profile_label("TESTSTD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        summarize(GateStatus.OK, {}, (), [], standard_label=LABEL)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "results",
    [{}, {"ZN": S.NOT_EVALUABLE}, {"ZN": S.NO_REFERENCE, "CU": S.NOT_EVALUABLE}],
)
def test_summary_with_nothing_evaluated_is_incomplete(results: dict[str, NutrientStatus]) -> None:
    result = summarize(GateStatus.OK, results, (), {}, standard_label=LABEL)
    assert result.status == SummaryStatus.INCOMPLETE
    assert (result.evaluated_count, result.required_count) == (0, 0)
