"""Metabolizovatelná energie krmiva a dávky (docs/06 §6.3, §6.10).

Kontrolní příklad docs/06 §6.3: 100 g s B 20, T 10, BNLV 0, V 0 → GE 208,0,
DE 189,696, ME 168,896 (NRC pes) a 155,0 (mod. Atwater). Ostatní suroviny
SYN_* jsou SYNTETICKÉ fixtury.
"""

from decimal import Decimal

import pytest

from nutricalc.composition import NutrientValue, RecipeItem
from nutricalc.errors import (
    DuplicateItemError,
    InvalidInputError,
    MissingDataError,
    SpeciesMismatchError,
    UnsupportedMethodError,
    ValidationError,
)
from nutricalc.flags import Flag
from nutricalc.me import (
    ItemMe,
    MeResult,
    energy_digestibility_pct,
    fibre_percent_of_dm,
    mod_atwater_me_kcal,
    nrc2006_dog_energy,
    nrc_gross_energy_kcal,
    ration_me,
)
from nutricalc.vocab import Completeness, MeMethod, Species, ValueKind, WarningLevel
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
CF = MeMethod.NRC2006_DOG_CF
TDF = MeMethod.NRC2006_DOG_TDF
ATWATER = MeMethod.MOD_ATWATER
DOG = Species.DOG

# SYNTETICKÉ suroviny (na 100 g):
# SYN_W = SYN_A s vodou 70 g; SYN_D s vlákninou; SYN_F „vlákninový doplněk“.
SYN_W = {
    "WATER": measured("70"),
    "PROTEIN": measured("20"),
    "FAT": measured("10"),
    "NFE": zero(),
    "CRUDE_FIBRE": zero(),
    "TDF": zero(),
}
SYN_D = {
    "WATER": measured("50"),
    "PROTEIN": measured("20"),
    "FAT": measured("10"),
    "NFE": measured("10"),
    "CRUDE_FIBRE": measured("5"),
    "TDF": measured("8"),
}
SYN_F = {
    "WATER": measured("10"),
    "PROTEIN": zero(),
    "FAT": zero(),
    "NFE": zero(),
    "CRUDE_FIBRE": measured("80"),
}


def one(
    values: dict[str, NutrientValue], grams: str = "100", code: str = "SYN_X"
) -> list[RecipeItem]:
    return [item(profile(code, values), grams)]


def codes(result: MeResult) -> list[str]:
    return [flag.code for flag in result.flags]


def flag(result: MeResult, code: str) -> Flag:
    return next(f for f in result.flags if f.code == code)


# --- rovnice a kontrolní příklad docs/06 §6.3 --------------------------------------------------


def test_nrc_dog_cf_golden() -> None:
    energy = nrc2006_dog_energy(
        method=CF, protein_g=20, fat_g=10, nfe_g=0, crude_fibre_g=0, fibre_dm_pct=0
    )
    assert energy.ge_kcal == D("208.0")
    assert energy.digestibility_pct == D("91.2")
    assert energy.de_kcal == D("189.696")
    assert energy.me_kcal == D("168.896")


def test_mod_atwater_golden() -> None:
    assert mod_atwater_me_kcal(20, 10, 0) == D("155.0")


def test_nrc_dog_tdf_uses_tdf_only_for_digestibility() -> None:
    energy = nrc2006_dog_energy(
        method=TDF, protein_g=20, fat_g=10, nfe_g=0, crude_fibre_g=0, fibre_dm_pct=0
    )
    assert (energy.ge_kcal, energy.digestibility_pct) == (D("208.0"), D("96.6"))
    assert energy.me_kcal == D("180.128")
    with_fibre = nrc2006_dog_energy(
        method=TDF, protein_g=20, fat_g=10, nfe_g=10, crude_fibre_g=5, fibre_dm_pct=16
    )
    assert with_fibre.ge_kcal == nrc_gross_energy_kcal(20, 10, 10, 5) == D("269.5")
    assert with_fibre.digestibility_pct == D("81.4")
    assert with_fibre.me_kcal == D("198.573")


def test_energy_digestibility() -> None:
    assert energy_digestibility_pct(CF, D(10)) == D("76.9")
    assert energy_digestibility_pct("NRC2006_DOG_TDF", D(16)) == D("81.4")
    with pytest.raises(UnsupportedMethodError):
        energy_digestibility_pct(ATWATER, D(0))
    with pytest.raises(UnsupportedMethodError):
        nrc2006_dog_energy(
            method=MeMethod.NRC2006_CAT,
            protein_g=1,
            fat_g=1,
            nfe_g=0,
            crude_fibre_g=0,
            fibre_dm_pct=0,
        )
    with pytest.raises(InvalidInputError):
        energy_digestibility_pct(CF, D(-1))


def test_fibre_percent_of_dm() -> None:
    assert fibre_percent_of_dm(D(5), D(100), D(50)) == D(10)
    assert fibre_percent_of_dm(D(0), D(100), None) == 0  # bez vlákniny voda není potřeba
    with pytest.raises(MissingDataError):
        fibre_percent_of_dm(D(5), D(100), None)
    with pytest.raises(ValidationError):
        fibre_percent_of_dm(D(5), D(100), D(100))


@pytest.mark.parametrize("value", [1.5, True])
def test_equations_reject_float_and_bool(value: object) -> None:
    with pytest.raises(TypeError):
        nrc_gross_energy_kcal(value, 1, 1, 1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        mod_atwater_me_kcal(1, value, 1)  # type: ignore[arg-type]


def test_equations_reject_negative_amounts() -> None:
    with pytest.raises(InvalidInputError):
        nrc_gross_energy_kcal(-1, 1, 1, 1)
    with pytest.raises(InvalidInputError):
        mod_atwater_me_kcal(1, 1, -1)


# --- ration_me: kontrolní příklady --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "expected"), [(CF, "168.896"), (TDF, "180.128"), (ATWATER, "155.0")]
)
def test_ration_me_golden_100g(method: MeMethod, expected: str) -> None:
    values = {
        "PROTEIN": measured("20"),
        "FAT": measured("10"),
        "NFE": zero(),
        "CRUDE_FIBRE": zero(),
        "TDF": zero(),
    }
    result = ration_me(one(values), method, DOG)
    assert result.kcal == D(expected)
    assert result.completeness is Completeness.COMPLETE
    assert result.per_item == (ItemMe("SYN_X", D(expected)),)
    assert result.flags == ()
    assert result.method is method


def test_ration_me_documented_syn_example() -> None:
    # docs/06 §6.10: SYN_A 168,896 kcal/100 g × 3 = 506,688 kcal; SYN_B 0 kcal
    result = ration_me([item(syn_b(), "50"), item(syn_a(), "300")], CF, DOG)
    assert result.kcal == D("506.688")
    assert result.completeness is Completeness.COMPLETE
    assert result.per_item == (ItemMe("SYN_A", D("506.688")), ItemMe("SYN_B", D(0)))


def test_ration_me_uses_ration_totals_not_sum_of_items() -> None:
    items = [item(profile("SYN_W", SYN_W), "100"), item(profile("SYN_D", SYN_D), "100")]
    result = ration_me(items, CF, DOG)
    # součty: B 40, T 20, BNLV 10, V 5, hmotnost 200, voda 120 → V 6,25 % sušiny
    assert result.kcal == D("351.2034375")
    assert result.per_item == (ItemMe("SYN_D", D("186.4455")), ItemMe("SYN_W", D("168.896")))
    item_sum = sum((entry.kcal for entry in result.per_item if entry.kcal is not None), D(0))
    assert item_sum != result.kcal
    # bez vlákniny jsou rovnice lineární a součet se shoduje
    linear = ration_me([item(syn_a(), "300"), item(syn_b(), "50")], CF, DOG)
    assert sum((e.kcal for e in linear.per_item if e.kcal is not None), D(0)) == linear.kcal


def test_ration_me_tdf_and_atwater_with_fibre() -> None:
    items = one(SYN_D)
    assert ration_me(items, TDF, DOG).kcal == D("198.573")
    assert ration_me(items, ATWATER, DOG).kcal == D("190.0")
    assert ration_me(items, CF, DOG).kcal == D("186.4455")


def test_ration_me_scales_with_grams() -> None:
    assert ration_me(one(SYN_D, "250"), CF, DOG).kcal == D("186.4455") * D("2.5")


# --- dopočet a chybějící BNLV ------------------------------------------------------------------


def _nfe_source(**changes: NutrientValue) -> dict[str, NutrientValue]:
    values = {
        "WATER": measured("70"),
        "PROTEIN": measured("20"),
        "FAT": measured("5"),
        "ASH": measured("1"),
        "CRUDE_FIBRE": zero(),
    }
    values.update(changes)
    return values


def test_nfe_calculated_by_difference() -> None:
    result = ration_me(one(_nfe_source()), ATWATER, DOG)
    # BNLV = 100 − (70 + 20 + 5 + 1 + 0) = 4 → 3,5·20 + 8,5·5 + 3,5·4
    assert result.kcal == D("126.5")
    assert result.completeness is Completeness.COMPLETE
    assert codes(result) == ["ME_NFE_CALCULATED"]
    assert flag(result, "ME_NFE_CALCULATED").level is WarningLevel.INFO
    assert flag(result, "ME_NFE_CALCULATED").subject == "SYN_X"


def test_negative_nfe_is_clamped_to_zero() -> None:
    result = ration_me(one(_nfe_source(WATER=measured("80"))), ATWATER, DOG)
    assert result.kcal == D("112.5")  # BNLV = −6 → 0
    assert result.completeness is Completeness.COMPLETE
    assert codes(result) == ["ME_NFE_CALCULATED", "ME_NFE_NEGATIVE_CLAMPED"]


@pytest.mark.parametrize("lacking", ["ASH", "WATER", "CRUDE_FIBRE"])
def test_nfe_missing_is_partial(lacking: str) -> None:
    source = _nfe_source()
    del source[lacking]
    result = ration_me(one(source), ATWATER, DOG)
    assert result.kcal == D("112.5")  # BNLV jako 0
    assert result.completeness is Completeness.PARTIAL
    assert codes(result) == ["ME_NFE_MISSING"]
    assert flag(result, "ME_NFE_MISSING").level is WarningLevel.NUTRITION_WARNING
    assert lacking in flag(result, "ME_NFE_MISSING").message_cs


def test_explicit_nfe_wins_over_calculation() -> None:
    result = ration_me(one(_nfe_source(NFE=measured("2"))), ATWATER, DOG)
    assert result.kcal == D("119.5")
    assert codes(result) == []


def test_below_lod_macronutrients_count_as_zero_with_info() -> None:
    values = {
        "PROTEIN": measured("20"),
        "FAT": below_lod("0.1"),
        "NFE": zero(),
        "CRUDE_FIBRE": zero(),
    }
    result = ration_me(one(values), ATWATER, DOG)
    assert result.kcal == D("70.0")
    assert result.completeness is Completeness.COMPLETE
    assert codes(result) == ["ME_BELOW_LOD_AS_ZERO"]
    trace = {**values, "FAT": NutrientValue(None, ValueKind.TRACE, quality=QUALITY)}
    assert ration_me(one(trace), ATWATER, DOG).kcal == D("70.0")


def test_below_lod_component_in_nfe_difference_is_reported_once() -> None:
    result = ration_me(one(_nfe_source(ASH=below_lod())), ATWATER, DOG)
    # BNLV = 100 − (70 + 20 + 5 + 0 + 0) = 5
    assert result.kcal == D("130.0")
    assert codes(result) == ["ME_BELOW_LOD_AS_ZERO", "ME_NFE_CALCULATED"]


# --- vláknina a voda ---------------------------------------------------------------------------


def test_missing_crude_fibre_is_partial_and_may_overestimate() -> None:
    values = {
        "WATER": measured("50"),
        "PROTEIN": measured("20"),
        "FAT": measured("10"),
        "NFE": zero(),
    }
    result = ration_me(one(values), CF, DOG)
    assert result.kcal == D("168.896")
    assert result.completeness is Completeness.PARTIAL
    assert codes(result) == ["ME_FIBRE_MISSING"]
    assert "nadhodnocen" in flag(result, "ME_FIBRE_MISSING").message_cs
    assert ration_me(one(values), ATWATER, DOG).completeness is Completeness.COMPLETE


def test_tdf_method_reports_each_missing_fibre() -> None:
    no_tdf = {key: value for key, value in SYN_D.items() if key != "TDF"}
    result = ration_me(one(no_tdf), TDF, DOG)
    assert result.completeness is Completeness.PARTIAL
    assert "TDF" in flag(result, "ME_FIBRE_MISSING").message_cs
    no_cf = {key: value for key, value in SYN_D.items() if key != "CRUDE_FIBRE"}
    result = ration_me(one(no_cf), TDF, DOG)
    assert result.completeness is Completeness.PARTIAL
    assert "podhodnocen" in flag(result, "ME_FIBRE_MISSING").message_cs


def test_fibre_without_water_makes_me_unknown() -> None:
    values = {key: value for key, value in SYN_D.items() if key != "WATER"}
    result = ration_me(one(values), CF, DOG)
    assert result.kcal is None
    assert result.completeness is Completeness.UNKNOWN
    assert result.per_item == (ItemMe("SYN_X", None),)
    water_flags = [f for f in result.flags if f.code == "ME_WATER_MISSING"]
    assert {f.subject for f in water_flags} == {"SYN_X", None}
    assert ration_me(one(values), ATWATER, DOG).kcal == D("190.0")  # Atwater vodu nepotřebuje


def test_missing_water_matters_only_when_ration_has_fibre() -> None:
    no_water = {key: value for key, value in SYN_W.items() if key != "WATER"}
    assert ration_me(one(no_water), CF, DOG).completeness is Completeness.COMPLETE
    items = [item(profile("SYN_D", SYN_D), "100"), item(profile("SYN_N", no_water), "100")]
    result = ration_me(items, CF, DOG)
    assert result.kcal is None and result.completeness is Completeness.UNKNOWN
    assert result.per_item == (ItemMe("SYN_D", D("186.4455")), ItemMe("SYN_N", D("168.896")))
    ration_flag = next(f for f in result.flags if f.code == "ME_WATER_MISSING")
    assert ration_flag.subject is None and "SYN_N" in ration_flag.message_cs


@pytest.mark.parametrize("lacking", ["PROTEIN", "FAT"])
def test_missing_protein_or_fat_makes_me_unknown(lacking: str) -> None:
    values = {key: value for key, value in SYN_D.items() if key != lacking}
    items = [item(profile("SYN_X", values), "100"), item(profile("SYN_D", SYN_D), "100")]
    result = ration_me(items, CF, DOG)
    assert result.kcal is None
    assert result.completeness is Completeness.UNKNOWN
    assert result.per_item == (ItemMe("SYN_D", D("186.4455")), ItemMe("SYN_X", None))
    missing_flag = flag(result, "ME_MACRONUTRIENT_MISSING")
    assert missing_flag.subject == "SYN_X" and lacking in missing_flag.message_cs
    explicit = {**values, lacking: missing()}
    assert ration_me(one(explicit), ATWATER, DOG).kcal is None


def test_equation_out_of_range_for_item_and_ration() -> None:
    fibre_only = ration_me(one(SYN_F, code="SYN_F"), CF, DOG)
    assert fibre_only.kcal is None and fibre_only.completeness is Completeness.UNKNOWN
    levels = {f.subject: f.level for f in fibre_only.flags if f.code == "ME_EQUATION_OUT_OF_RANGE"}
    assert levels == {None: WarningLevel.EXPERT_REQUIRED, "SYN_F": WarningLevel.INFO}
    mixed = ration_me(
        [item(profile("SYN_W", SYN_W), "1000"), item(profile("SYN_F", SYN_F), "10")], CF, DOG
    )
    assert mixed.kcal is not None and mixed.kcal > 0
    assert mixed.completeness is Completeness.COMPLETE
    assert mixed.per_item[0] == ItemMe("SYN_F", None)
    assert [f.subject for f in mixed.flags] == ["SYN_F"]


def test_inconsistent_water_raises() -> None:
    with pytest.raises(ValidationError):
        ration_me(one({**SYN_W, "WATER": measured("101")}), ATWATER, DOG)
    with pytest.raises(ValidationError):
        ration_me(one({**SYN_D, "WATER": measured("100")}), CF, DOG)
    pure_water = {
        "WATER": measured("100"),
        "PROTEIN": zero(),
        "FAT": zero(),
        "NFE": zero(),
        "CRUDE_FIBRE": zero(),
    }
    assert ration_me(one(pure_water), CF, DOG).kcal == 0


# --- metoda, druh, položky --------------------------------------------------------------------


def test_nrc_dog_methods_are_rejected_for_cats() -> None:
    for method in (CF, TDF):
        with pytest.raises(SpeciesMismatchError):
            ration_me(one(SYN_D), method, Species.CAT)
    assert ration_me(one(SYN_D), ATWATER, "CAT").kcal == D("190.0")  # type: ignore[arg-type]


@pytest.mark.parametrize("species", [Species.DOG, Species.CAT])
def test_cat_method_is_unsupported(species: Species) -> None:
    with pytest.raises(UnsupportedMethodError):
        ration_me(one(SYN_D), MeMethod.NRC2006_CAT, species)


def test_unknown_method_and_species() -> None:
    with pytest.raises(UnsupportedMethodError):
        ration_me(one(SYN_D), "ATWATER_4_9_4", DOG)
    with pytest.raises(InvalidInputError):
        ration_me(one(SYN_D), CF, "HORSE")  # type: ignore[arg-type]


def test_items_are_validated() -> None:
    with pytest.raises(DuplicateItemError):
        ration_me([item(syn_a(), "100"), item(syn_a(), "50")], CF, DOG)
    with pytest.raises(ValidationError):
        ration_me([], CF, DOG)


def test_result_does_not_depend_on_item_order() -> None:
    items = [
        item(profile("SYN_W", SYN_W), "120"),
        item(profile("SYN_D", SYN_D), "80"),
        item(profile("SYN_N", _nfe_source()), "40"),
    ]
    expected = ration_me(items, CF, DOG)
    assert ration_me(list(reversed(items)), CF, DOG) == expected
    assert ration_me([items[1], items[2], items[0]], CF, DOG) == expected
    assert [entry.ingredient_code for entry in expected.per_item] == ["SYN_D", "SYN_N", "SYN_W"]
