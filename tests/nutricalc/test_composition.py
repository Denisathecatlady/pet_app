"""Hodnoty živin, profily surovin a denní součty s úplností (docs/06 §6.5, §6.10).

Suroviny SYN_* jsou SYNTETICKÉ fixtury (tests/nutricalc/synthetic.py).
"""

import copy
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from nutricalc.composition import (
    MISSING_VALUE,
    Contribution,
    Contributor,
    IngredientProfile,
    NutrientValue,
    RecipeItem,
    contribution,
    sum_nutrient,
    validate_items,
)
from nutricalc.errors import (
    DuplicateItemError,
    InvalidInputError,
    UnitMismatchError,
    ValidationError,
)
from nutricalc.units import Quantity, per_day_to_per_1000kcal
from nutricalc.vocab import Basis, Completeness, QualityGrade, Unit, ValueKind
from tests.nutricalc.synthetic import (
    QUALITY,
    below_lod,
    item,
    measured,
    missing,
    profile,
    syn_a,
    syn_b,
    zero,
)

D = Decimal

# --- NutrientValue --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "kind", "extra"),
    [
        pytest.param(None, ValueKind.MISSING, {}, id="missing"),
        pytest.param(D(0), ValueKind.ZERO_BY_DEFINITION, {}, id="zero"),
        pytest.param(D("2.5"), ValueKind.MEASURED, {}, id="measured"),
        pytest.param(
            D("2.5"), ValueKind.CALCULATED, {"value_min": D(2), "value_max": D(3)}, id="interval"
        ),
        pytest.param(D("2.5"), ValueKind.BORROWED, {"value_min": D("2.5")}, id="min-equal"),
        pytest.param(D("2.5"), ValueKind.IMPUTED, {"value_max": D("2.5")}, id="max-equal"),
        pytest.param(D(0), ValueKind.MEASURED, {}, id="measured-zero"),
        pytest.param(None, ValueKind.BELOW_LOD, {}, id="below-lod-bez-lod"),
        pytest.param(None, ValueKind.BELOW_LOD, {"lod": D("0.005")}, id="below-lod"),
        pytest.param(D("0.001"), ValueKind.BELOW_LOD, {"lod": D("0.005")}, id="below-lod-hodnota"),
        pytest.param(D("0.005"), ValueKind.TRACE, {"lod": D("0.005")}, id="trace-na-lod"),
        pytest.param(None, ValueKind.TRACE, {}, id="trace"),
    ],
)
def test_nutrient_value_accepts_valid(
    value: Decimal | None, kind: ValueKind, extra: dict[str, Decimal]
) -> None:
    nv = NutrientValue(value, kind, quality=QUALITY, **extra)
    assert nv.kind is kind and nv.value == value


@pytest.mark.parametrize(
    ("value", "kind", "extra"),
    [
        pytest.param(D(1), ValueKind.MISSING, {}, id="missing-s-hodnotou"),
        pytest.param(D(0), ValueKind.MISSING, {}, id="missing-s-nulou"),
        pytest.param(None, ValueKind.MISSING, {"lod": D(1)}, id="missing-s-lod"),
        pytest.param(D(1), ValueKind.ZERO_BY_DEFINITION, {}, id="zero-nenulova"),
        pytest.param(None, ValueKind.ZERO_BY_DEFINITION, {}, id="zero-bez-hodnoty"),
        pytest.param(
            D(0), ValueKind.ZERO_BY_DEFINITION, {"value_max": D(0)}, id="zero-s-intervalem"
        ),
        pytest.param(None, ValueKind.MEASURED, {}, id="measured-bez-hodnoty"),
        pytest.param(D(-1), ValueKind.MEASURED, {}, id="zaporna"),
        pytest.param(D(2), ValueKind.MEASURED, {"value_min": D(3)}, id="min-nad-hodnotou"),
        pytest.param(D(2), ValueKind.MEASURED, {"value_max": D(1)}, id="max-pod-hodnotou"),
        pytest.param(D(2), ValueKind.MEASURED, {"value_min": D(-1)}, id="zaporne-min"),
        pytest.param(D(2), ValueKind.MEASURED, {"lod": D(1)}, id="lod-u-measured"),
        pytest.param(None, ValueKind.BELOW_LOD, {"lod": D(0)}, id="lod-nula"),
        pytest.param(D("0.01"), ValueKind.BELOW_LOD, {"lod": D("0.005")}, id="hodnota-nad-lod"),
        pytest.param(None, ValueKind.TRACE, {"value_max": D(1)}, id="trace-s-intervalem"),
        pytest.param(None, ValueKind.BELOW_LOD, {"value_min": D(0)}, id="lod-s-minimem"),
    ],
)
def test_nutrient_value_rejects_invalid(
    value: Decimal | None, kind: ValueKind, extra: dict[str, Decimal]
) -> None:
    with pytest.raises(ValidationError):
        NutrientValue(value, kind, quality=QUALITY, **extra)


def test_nutrient_value_types_and_coercion() -> None:
    with pytest.raises(TypeError):
        NutrientValue(2.5, ValueKind.MEASURED, quality=QUALITY)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        NutrientValue(D(1), ValueKind.MEASURED)  # type: ignore[call-arg]
    with pytest.raises(InvalidInputError):
        NutrientValue(D(1), "GUESSED", quality=QUALITY)  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        NutrientValue(D(1), ValueKind.MEASURED, quality="E")  # type: ignore[arg-type]
    coerced = NutrientValue("1.5", "MEASURED", quality="A")  # type: ignore[arg-type]
    assert coerced == NutrientValue(D("1.5"), ValueKind.MEASURED, quality=QualityGrade.A)
    with pytest.raises(FrozenInstanceError):
        coerced.value = D(2)  # type: ignore[misc]


def test_missing_value_constant() -> None:
    assert MISSING_VALUE.kind is ValueKind.MISSING and MISSING_VALUE.value is None
    assert MISSING_VALUE.quality is QualityGrade.D


# --- IngredientProfile --------------------------------------------------------------------


def test_profile_values_are_sorted_immutable_and_missing_by_default() -> None:
    source = {"PROTEIN": measured("20"), "CA": measured("1"), "FAT": zero()}
    built = profile("SYN_X", source)
    assert [code for code, _ in built.values] == ["CA", "FAT", "PROTEIN"]
    source["ZN"] = measured("1")  # změna zdroje se do profilu nepropíše
    assert built.get("ZN") is MISSING_VALUE
    assert built.get("CA") == measured("1")
    assert isinstance(built.values, tuple)
    with pytest.raises(TypeError):
        built.values_map["CA"] = zero()  # type: ignore[index]
    assert dict(built.values_map) == {"CA": measured("1"), "FAT": zero(), "PROTEIN": measured("20")}


def test_profile_from_pairs_equals_profile_from_mapping() -> None:
    pairs = (("PROTEIN", measured("20")), ("CA", measured("1")))
    from_pairs = IngredientProfile("SYN_X", "v1", "TEST", ["RAW"], pairs)  # type: ignore[arg-type]
    from_map = IngredientProfile("SYN_X", "v1", "TEST", frozenset({"RAW"}), dict(pairs))  # type: ignore[arg-type]
    assert from_pairs == from_map
    assert hash(from_pairs) == hash(from_map)
    assert from_pairs.safety_flags == frozenset({"RAW"})


def test_profile_survives_copy_and_deepcopy_after_lookup() -> None:
    built = syn_a()
    built.get("PROTEIN")
    assert copy.deepcopy(built) == built
    assert copy.copy(built) == built


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (("", "v1", "TEST", frozenset(), {}), ValidationError),
        (("SYN_X", " ", "TEST", frozenset(), {}), ValidationError),
        (("SYN_X", "v1", "", frozenset(), {}), ValidationError),
        ((1, "v1", "TEST", frozenset(), {}), TypeError),
        (("SYN_X", "v1", "TEST", "RAW", {}), TypeError),
        (("SYN_X", "v1", "TEST", frozenset({""}), {}), ValidationError),
        (("SYN_X", "v1", "TEST", frozenset(), {"CA": D(1)}), TypeError),
        (("SYN_X", "v1", "TEST", frozenset(), {"": zero()}), ValidationError),
        (("SYN_X", "v1", "TEST", frozenset(), (("CA", zero()), ("CA", zero()))), ValidationError),
    ],
)
def test_profile_validation(args: tuple[object, ...], error: type[Exception]) -> None:
    with pytest.raises(error):
        IngredientProfile(*args)  # type: ignore[arg-type]


# --- RecipeItem a validate_items ---------------------------------------------------------------


def test_recipe_item() -> None:
    entry = RecipeItem(syn_a(), "300")  # type: ignore[arg-type]
    assert entry.grams == D(300) and entry.ingredient_code == "SYN_A"
    for grams in (D(0), D("0.000")):
        with pytest.raises(ValidationError):
            RecipeItem(syn_a(), grams)
    with pytest.raises(InvalidInputError):
        RecipeItem(syn_a(), D(-1))
    with pytest.raises(TypeError):
        RecipeItem(syn_a(), 300.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RecipeItem("SYN_A", D(300))  # type: ignore[arg-type]


def test_validate_items_sorts_by_code() -> None:
    first, second = item(syn_b(), "50"), item(syn_a(), "300")
    assert validate_items([first, second]) == (second, first)
    assert validate_items(iter([second, first])) == (second, first)


def test_validate_items_rejects_duplicates_empty_and_wrong_types() -> None:
    other_version = IngredientProfile("SYN_A", "SYN_A@test-2", "TEST", frozenset(), {})
    with pytest.raises(DuplicateItemError, match="SYN_A"):
        validate_items([item(syn_a(), "300"), item(syn_b(), "5"), item(syn_a(), "10")])
    with pytest.raises(DuplicateItemError):
        validate_items([item(syn_a(), "300"), RecipeItem(other_version, D(10))])
    with pytest.raises(ValidationError):
        validate_items([])
    with pytest.raises(TypeError):
        validate_items([syn_a()])  # type: ignore[list-item]


# --- contribution (docs/06 §6.5.1) ----------------------------------------------------


@pytest.mark.parametrize(
    ("nv", "grams", "expected"),
    [
        pytest.param(measured("2"), "50", Contribution(D(1), D(1), D(1), True), id="measured"),
        pytest.param(
            NutrientValue(
                D(2), ValueKind.CALCULATED, value_min=D("1.5"), value_max=D(3), quality=QUALITY
            ),
            "200",
            Contribution(D(3), D(6), D(4), True),
            id="interval",
        ),
        pytest.param(
            NutrientValue(D(2), ValueKind.BORROWED, value_min=D(1), quality=QUALITY),
            "100",
            Contribution(D(1), D(2), D(2), True),
            id="jen-min",
        ),
        pytest.param(
            NutrientValue(D(2), ValueKind.IMPUTED, value_max=D(5), quality=QUALITY),
            "100",
            Contribution(D(2), D(5), D(2), True),
            id="jen-max",
        ),
        pytest.param(
            below_lod("0.005"), "300", Contribution(D(0), D("0.015"), None, True), id="lod"
        ),
        pytest.param(below_lod(), "300", Contribution(D(0), None, None, False), id="lod-bez-meze"),
        pytest.param(
            NutrientValue(None, ValueKind.TRACE, lod=D("0.1"), quality=QUALITY),
            "50",
            Contribution(D(0), D("0.05"), None, True),
            id="trace",
        ),
        pytest.param(
            NutrientValue(None, ValueKind.TRACE, quality=QUALITY),
            "50",
            Contribution(D(0), None, None, False),
            id="trace-bez-meze",
        ),
        pytest.param(zero(), "300", Contribution(D(0), D(0), D(0), True), id="zero"),
        pytest.param(missing(), "300", Contribution(D(0), None, None, False), id="missing"),
    ],
)
def test_contribution_table(nv: NutrientValue, grams: str, expected: Contribution) -> None:
    assert contribution(nv, D(grams)) == expected


def test_contribution_ignores_below_lod_value_for_point() -> None:
    nv = NutrientValue(D("0.001"), ValueKind.BELOW_LOD, lod=D("0.005"), quality=QUALITY)
    assert contribution(nv, D(100)) == Contribution(D(0), D("0.005"), None, True)


def test_contribution_rejects_invalid_arguments() -> None:
    with pytest.raises(ValidationError):
        contribution(measured("1"), D(0))
    with pytest.raises(InvalidInputError):
        contribution(measured("1"), D(-10))
    with pytest.raises(TypeError):
        contribution(measured("1"), 10.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        contribution(D(1), D(10))  # type: ignore[arg-type]


# --- sum_nutrient: referenční příklad docs/06 §6.10 ------------------------------------


def _syn_items(ca: NutrientValue | None = None) -> list[RecipeItem]:
    return [item(syn_a(ca), "300"), item(syn_b(), "50")]


def test_phosphorus_complete_documented_example() -> None:
    total = sum_nutrient(_syn_items(), "P", Unit.G)
    assert total.completeness is Completeness.COMPLETE
    assert total.lower == total.upper == total.point == D("3.1")
    assert total.basis is Basis.PER_DAY and total.unit is Unit.G
    assert total.missing_mass_share == 0
    assert total.contributors == (
        Contributor("SYN_B", D("2.5"), D("2.5")),
        Contributor("SYN_A", D("0.6"), D("0.6")),
    )
    per_1000 = per_day_to_per_1000kcal(total.lower_quantity(), D("506.688"))
    assert abs(per_1000.value - D("6.118")) < D("0.0005")


def test_calcium_partial_documented_example() -> None:
    total = sum_nutrient(_syn_items(), "CA", Unit.G)
    assert total.completeness is Completeness.PARTIAL
    assert total.lower == D("5.0")
    assert total.upper is None and total.point is None
    assert total.missing_mass_share == D(300) / D(350)
    assert abs(total.missing_mass_share - D("0.857")) < D("0.0005")
    assert total.contributors == (Contributor("SYN_B", D("5.0"), D("5.0")),)
    assert total.upper_quantity() is None and total.point_quantity() is None


def test_calcium_below_lod_variant_documented_example() -> None:
    total = sum_nutrient(_syn_items(ca=below_lod("0.005")), "CA", Unit.G)
    assert total.completeness is Completeness.COMPLETE
    assert (total.lower, total.upper) == (D("5.000"), D("5.015"))
    assert total.point is None  # pod mezí detekce není bodová hodnota
    assert total.missing_mass_share == 0
    phosphorus = sum_nutrient(_syn_items(), "P", Unit.G)
    assert phosphorus.upper is not None and total.upper is not None
    ratio_low = total.lower / phosphorus.upper
    ratio_high = total.upper / phosphorus.lower
    assert (round(ratio_low, 3), round(ratio_high, 3)) == (D("1.613"), D("1.618"))


def test_missing_is_never_zero() -> None:
    nothing = sum_nutrient(_syn_items(), "ZN", Unit.MG)
    assert nothing.completeness is Completeness.UNKNOWN
    assert nothing.upper is None and nothing.point is None
    assert nothing.missing_mass_share == 1
    assert nothing.contributors == ()
    zeros = sum_nutrient([item(profile("SYN_Z", {"ZN": zero()}), "100")], "ZN", Unit.MG)
    assert zeros.completeness is Completeness.COMPLETE
    assert zeros.point == zeros.upper == 0


def test_lod_without_limit_counts_as_missing_mass() -> None:
    total = sum_nutrient(_syn_items(ca=below_lod()), "CA", Unit.G)
    assert total.completeness is Completeness.PARTIAL
    assert total.missing_mass_share == D(300) / D(350)


def test_contributors_sorted_by_upper_then_code() -> None:
    items = [
        item(profile("SYN_C", {"ZN": measured("1")}), "100"),
        item(profile("SYN_A", {"ZN": measured("2")}), "50"),
        item(profile("SYN_B", {"ZN": measured("3")}), "100"),
        item(profile("SYN_D", {"ZN": zero()}), "10"),
        item(profile("SYN_E", {}), "10"),
    ]
    total = sum_nutrient(items, "ZN", Unit.MG)
    assert [c.ingredient_code for c in total.contributors] == ["SYN_B", "SYN_A", "SYN_C", "SYN_D"]
    assert total.completeness is Completeness.PARTIAL
    assert total.lower == D(5)
    assert total.missing_mass_share == D(10) / D(270)


def test_interval_totals_are_worst_case_sums() -> None:
    items = [
        item(
            profile(
                "SYN_A",
                {
                    "CU": NutrientValue(
                        D(2), ValueKind.MEASURED, value_min=D(1), value_max=D(4), quality=QUALITY
                    )
                },
            ),
            "100",
        ),
        item(profile("SYN_B", {"CU": measured("3")}), "200"),
    ]
    total = sum_nutrient(items, "CU", Unit.MG)
    assert (total.lower, total.point, total.upper) == (D(7), D(8), D(10))
    assert total.lower_quantity() == Quantity(D(7), Unit.MG, Basis.PER_DAY)
    assert total.upper_quantity() == Quantity(D(10), Unit.MG, Basis.PER_DAY)
    assert total.point_quantity() == Quantity(D(8), Unit.MG, Basis.PER_DAY)


def test_sum_nutrient_is_independent_of_item_order() -> None:
    items = _syn_items(ca=below_lod("0.005"))
    assert sum_nutrient(items, "CA", Unit.G) == sum_nutrient(list(reversed(items)), "CA", Unit.G)


def test_sum_nutrient_argument_errors() -> None:
    with pytest.raises(UnitMismatchError):
        sum_nutrient(_syn_items(), "CA_P", Unit.RATIO)
    with pytest.raises(InvalidInputError):
        sum_nutrient(_syn_items(), "CA", "IU")
    with pytest.raises(ValidationError):
        sum_nutrient(_syn_items(), "", Unit.G)
    with pytest.raises(ValidationError):
        sum_nutrient([], "CA", Unit.G)
    with pytest.raises(DuplicateItemError):
        sum_nutrient([*_syn_items(), item(syn_a(), "1")], "CA", Unit.G)
    assert sum_nutrient(_syn_items(), "P", "g").unit is Unit.G
