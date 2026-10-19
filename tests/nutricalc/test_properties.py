"""Vlastnostní testy (hypothesis) a nezávislost na globálním kontextu Decimal.

Generované suroviny jsou SYNTETICKÉ (kódy SYN_00…SYN_05, živina SYN_N).
Čísla mají omezený počet číslic, takže součiny i součty jsou v přesnosti 28
přesné a linearitu lze ověřit rovností.
"""

from decimal import ROUND_DOWN, Decimal, localcontext

from hypothesis import given
from hypothesis import strategies as st

from nutricalc.composition import NutrientValue, RecipeItem, sum_nutrient
from nutricalc.energy import estimate_energy, nrc_kitten_me_kcal, nrc_puppy_me_kcal, rer_kcal
from nutricalc.me import ration_me
from nutricalc.units import Quantity, as_fed_to_dm, per_day_to_per_1000kcal
from nutricalc.vocab import Basis, MeMethod, Species, Unit, ValueKind
from tests.nutricalc.synthetic import (
    QUALITY,
    dog_factor,
    energy_input,
    item,
    measured,
    profile,
    zero,
)

D = Decimal
NUTRIENT = "SYN_N"

amounts = st.integers(min_value=0, max_value=10**6).map(lambda n: D(n).scaleb(-3))
positive_amounts = st.integers(min_value=1, max_value=10**6).map(lambda n: D(n).scaleb(-3))
grams = st.integers(min_value=1, max_value=10**5).map(lambda n: D(n).scaleb(-1))
factors = st.integers(min_value=1, max_value=10**4).map(lambda n: D(n).scaleb(-2))


@st.composite
def nutrient_values(draw: st.DrawFn) -> NutrientValue:
    kind = draw(st.sampled_from(list(ValueKind)))
    if kind == ValueKind.MISSING:
        return NutrientValue(None, kind, quality=QUALITY)
    if kind == ValueKind.ZERO_BY_DEFINITION:
        return zero()
    if kind in (ValueKind.BELOW_LOD, ValueKind.TRACE):
        lod = draw(st.none() | positive_amounts)
        return NutrientValue(None, kind, lod=lod, quality=QUALITY)
    value = draw(amounts)
    low = draw(st.none() | st.integers(0, 1000).map(lambda n: value * D(n) / D(1000)))
    high = draw(st.none() | st.integers(0, 1000).map(lambda n: value + D(n).scaleb(-3)))
    return NutrientValue(value, kind, value_min=low, value_max=high, quality=QUALITY)


@st.composite
def recipes(draw: st.DrawFn) -> list[RecipeItem]:
    count = draw(st.integers(min_value=1, max_value=6))
    values = draw(st.lists(nutrient_values(), min_size=count, max_size=count))
    weights = draw(st.lists(grams, min_size=count, max_size=count))
    return [
        RecipeItem(profile(f"SYN_{index:02d}", {NUTRIENT: value}), weight)
        for index, (value, weight) in enumerate(zip(values, weights, strict=True))
    ]


def _scaled(items: list[RecipeItem], factor: Decimal) -> list[RecipeItem]:
    return [RecipeItem(entry.profile, entry.grams * factor) for entry in items]


def _times(value: Decimal | None, factor: Decimal) -> Decimal | None:
    return None if value is None else value * factor


@given(recipes(), factors)
def test_scaling_grams_scales_daily_totals_linearly(
    items: list[RecipeItem], factor: Decimal
) -> None:
    base = sum_nutrient(items, NUTRIENT, Unit.MG)
    scaled = sum_nutrient(_scaled(items, factor), NUTRIENT, Unit.MG)
    assert scaled.lower == base.lower * factor
    assert scaled.upper == _times(base.upper, factor)
    assert scaled.point == _times(base.point, factor)
    assert scaled.completeness == base.completeness
    assert scaled.missing_mass_share == base.missing_mass_share
    assert [(c.ingredient_code, c.lower, c.upper) for c in scaled.contributors] == [
        (c.ingredient_code, c.lower * factor, c.upper * factor) for c in base.contributors
    ]


@given(recipes(), st.randoms(use_true_random=False))
def test_item_order_does_not_change_totals(items: list[RecipeItem], shuffler: object) -> None:
    shuffled = items[:]
    shuffler.shuffle(shuffled)  # type: ignore[attr-defined]
    assert sum_nutrient(shuffled, NUTRIENT, Unit.MG) == sum_nutrient(items, NUTRIENT, Unit.MG)


@given(recipes(), recipes())
def test_daily_lower_bounds_are_additive(first: list[RecipeItem], second: list[RecipeItem]) -> None:
    renamed = [
        RecipeItem(profile(f"SYN_B{index:02d}", dict(entry.profile.values)), entry.grams)
        for index, entry in enumerate(second)
    ]
    combined = sum_nutrient(first + renamed, NUTRIENT, Unit.MG)
    left = sum_nutrient(first, NUTRIENT, Unit.MG)
    right = sum_nutrient(renamed, NUTRIENT, Unit.MG)
    assert combined.lower == left.lower + right.lower
    if left.upper is not None and right.upper is not None:
        assert combined.upper == left.upper + right.upper


@st.composite
def macro_recipes(draw: st.DrawFn) -> list[RecipeItem]:
    count = draw(st.integers(min_value=1, max_value=4))
    result = []
    for index in range(count):
        protein = draw(st.integers(0, 300))
        fat = draw(st.integers(0, 300))
        fibre = draw(st.integers(0, 50))
        water = draw(st.integers(400, 700))
        values = {
            "PROTEIN": measured(str(D(protein).scaleb(-1))),
            "FAT": measured(str(D(fat).scaleb(-1))),
            "NFE": zero(),
            "CRUDE_FIBRE": measured(str(D(fibre).scaleb(-1))),
            "WATER": measured(str(D(water).scaleb(-1))),
        }
        result.append(item(profile(f"SYN_M{index}", values), str(draw(grams))))
    return result


@given(macro_recipes(), factors)
def test_ration_me_and_density_scale_with_grams(items: list[RecipeItem], factor: Decimal) -> None:
    base = ration_me(items, MeMethod.NRC2006_DOG_CF, Species.DOG)
    scaled = ration_me(_scaled(items, factor), MeMethod.NRC2006_DOG_CF, Species.DOG)
    assert base.kcal is not None and scaled.kcal is not None
    tolerance = D("1e-18") * (abs(base.kcal) * factor + 1)
    assert abs(scaled.kcal - base.kcal * factor) <= tolerance
    if base.kcal > 0:
        protein = sum_nutrient(items, "PROTEIN", Unit.G).lower_quantity()
        protein_scaled = sum_nutrient(_scaled(items, factor), "PROTEIN", Unit.G).lower_quantity()
        density = per_day_to_per_1000kcal(protein, base.kcal).value
        density_scaled = per_day_to_per_1000kcal(protein_scaled, scaled.kcal).value
        assert abs(density_scaled - density) <= D("1e-15") * (density + 1)


@given(macro_recipes(), st.randoms(use_true_random=False))
def test_ration_me_does_not_depend_on_item_order(items: list[RecipeItem], shuffler: object) -> None:
    shuffled = items[:]
    shuffler.shuffle(shuffled)  # type: ignore[attr-defined]
    for method in (MeMethod.NRC2006_DOG_CF, MeMethod.MOD_ATWATER):
        assert ration_me(shuffled, method, Species.DOG) == ration_me(items, method, Species.DOG)


@given(amounts)
def test_mass_unit_round_trip_is_exact(value: Decimal) -> None:
    quantity = Quantity(value, Unit.G, Basis.PER_DAY)
    assert quantity.to_unit(Unit.UG).to_unit(Unit.G) == quantity
    assert quantity.to_unit(Unit.MG).to_unit(Unit.UG).to_unit(Unit.G) == quantity


# --- nezávislost na globálním kontextu --------------------------------------------------------


def _results() -> tuple[object, ...]:
    items = [
        item(
            profile(
                "SYN_A",
                {
                    "PROTEIN": measured("20"),
                    "FAT": measured("10"),
                    "NFE": zero(),
                    "CRUDE_FIBRE": measured("1.7"),
                    "WATER": measured("61.3"),
                    "ZN": measured("1.234"),
                },
            ),
            "333.3",
        ),
        item(
            profile(
                "SYN_B",
                {
                    "PROTEIN": zero(),
                    "FAT": zero(),
                    "NFE": zero(),
                    "CRUDE_FIBRE": zero(),
                    "WATER": measured("3"),
                    "ZN": measured("7"),
                },
            ),
            "7.7",
        ),
    ]
    return (
        rer_kcal(D("13.7")),
        nrc_puppy_me_kcal(D("7.3"), D("31")),
        nrc_kitten_me_kcal(D("1.9"), D("4.1")),
        estimate_energy(
            energy_input(body_weight_kg=D("23.45"), factor=dog_factor("110", k_low="95"))
        ),
        sum_nutrient(items, "ZN", Unit.MG),
        ration_me(items, MeMethod.NRC2006_DOG_CF, Species.DOG),
        ration_me(items, MeMethod.NRC2006_DOG_TDF, Species.DOG),
        as_fed_to_dm(Quantity(D("1.1"), Unit.G, Basis.PER_100G_AS_FED), D("61.3")),
        Quantity(D(1), Unit.KJ, Basis.PER_DAY).to_unit(Unit.KCAL),
        per_day_to_per_1000kcal(Quantity(D("3.1"), Unit.G, Basis.PER_DAY), D("506.688")),
    )


def test_results_do_not_depend_on_global_decimal_context() -> None:
    expected = _results()
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps = dict.fromkeys(context.traps, False)  # type: ignore[assignment]
        assert _results() == expected
    assert _results() == expected
