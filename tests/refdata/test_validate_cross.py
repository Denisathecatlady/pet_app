"""Kontroly mezi řádky: minimum/maximum, převody bází, dvojice 95/110 a 75/100.

Čísla jsou syntetická (standard TESTSTD). Jedinou výjimkou je zdokumentovaný
příklad Ca 1.25 g / 1000 kcal ME ↔ 0.50 g / 100 g sušiny (docs/03 §3.3).
"""

import random
from collections.abc import Callable

import pytest

from refdata.catalog import NutrientDef
from refdata.findings import ERROR, WARNING, Finding
from refdata.standard_rows import StandardRow
from refdata.validate import validate_rows
from refdata.vocab import CONFIRM_TOKEN

CAT = {"species": "CAT", "reference_energy_k": "100", "reference_energy_exponent": "0.67"}
DOG_LOW = {"life_stage": "ADULT_MAINTENANCE_LOW", "reference_energy_k": "95"}
CAT_LOW = {**CAT, "life_stage": "ADULT_MAINTENANCE_LOW", "reference_energy_k": "75"}

RowFactory = Callable[..., StandardRow]


def _found(findings: list[Finding], code: str) -> list[Finding]:
    return [finding for finding in findings if finding.code == code]


# --- minimum < maximum ---------------------------------------------------------


@pytest.mark.parametrize(
    ("low_type", "low", "high_type", "high", "expected"),
    [
        ("MIN_RECOMMENDED", "5.0", "NUTRITIONAL_MAX", "4.0", True),
        ("MIN_RECOMMENDED", "5.0", "NUTRITIONAL_MAX", "5.0", True),
        ("MIN_RECOMMENDED", "4.0", "NUTRITIONAL_MAX", "5.0", False),
        ("RA", "5.0", "LEGAL_MAX_EU", "5.00", True),
        ("AI", "4.9", "LEGAL_MAX_EU", "5.0", False),
        ("MR", "9", "SUL", "8", True),
        ("MR", "7", "SUL", "8", False),
        ("NUTRITIONAL_MAX", "6.0", "LEGAL_MAX_EU", "5.0", True),
        ("NUTRITIONAL_MAX", "5.0", "LEGAL_MAX_EU", "5.0", False),
        ("NUTRITIONAL_MAX", "4.0", "LEGAL_MAX_EU", "5.0", False),
    ],
)
def test_min_not_below_max(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    low_type: str,
    low: str,
    high_type: str,
    high: str,
    expected: bool,
) -> None:
    rows = [
        make_row(line=2, requirement_type=low_type, value=low),
        make_row(line=3, requirement_type=high_type, value=high),
    ]
    found = _found(validate_rows(rows, catalog), "E_MIN_NOT_BELOW_MAX")
    assert bool(found) is expected
    if expected:
        assert found[0].severity == ERROR and found[0].lines == (2, 3)


@pytest.mark.parametrize(
    ("ratio_min", "ratio_max", "expected"), [("2", "2", True), ("3", "2", True), ("1", "2", False)]
)
def test_ratio_min_must_be_below_ratio_max(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    ratio_min: str,
    ratio_max: str,
    expected: bool,
) -> None:
    rows = [
        make_row(nutrient_code="CA_P", unit="ratio", requirement_type="RATIO_MIN", value=ratio_min),
        make_row(nutrient_code="CA_P", unit="ratio", requirement_type="RATIO_MAX", value=ratio_max),
    ]
    assert bool(_found(validate_rows(rows, catalog), "E_MIN_NOT_BELOW_MAX")) is expected


@pytest.mark.parametrize(
    "difference",
    [
        pytest.param({"condition_note": "suché krmivo"}, id="jina-podminka"),
        pytest.param({"basis": "PER_100G_DM"}, id="jina-baze"),
        pytest.param(DOG_LOW, id="jiny-sloupec-k"),
        pytest.param({"standard_code": "TESTSTD2"}, id="jiny-standard"),
        pytest.param({"source_page": ""}, id="radek-s-chybou"),
    ],
)
def test_min_max_only_within_same_profile_and_clean_rows(
    catalog: dict[str, NutrientDef], make_row: RowFactory, difference: dict[str, str]
) -> None:
    rows = [
        make_row(requirement_type="MIN_RECOMMENDED", value="5.0"),
        make_row(requirement_type="NUTRITIONAL_MAX", value="4.0", **difference),
    ]
    assert not _found(validate_rows(rows, catalog), "E_MIN_NOT_BELOW_MAX")


def test_min_max_only_between_rows_with_same_unit(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(nutrient_code="VIT_D", unit="IU", requirement_type="MIN_RECOMMENDED", value="50"),
        make_row(nutrient_code="VIT_D", unit="ug", requirement_type="NUTRITIONAL_MAX", value="10"),
    ]
    findings = validate_rows(rows, catalog)
    assert {f.code for f in findings} == {"W_NEEDS_CONVERSION"}


# --- převody mezi bázemi --------------------------------------------------------


def _ca_rows(make_row: RowFactory, per_1000: str, per_dm: str, note: str = "") -> list[StandardRow]:
    common = {
        "standard_code": "FEDIAF",
        "edition": "2025",
        "nutrient_code": "CA",
        "unit": "g",
        "note": note,
    }
    return [
        make_row(line=2, basis="PER_1000KCAL_ME", value=per_1000, **common),
        make_row(line=3, basis="PER_100G_DM", value=per_dm, **common),
    ]


def test_documented_calcium_example_passes(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    assert validate_rows(_ca_rows(make_row, "1.25", "0.50"), catalog) == []


def test_documented_calcium_example_detects_wrong_dm_value(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    findings = validate_rows(_ca_rows(make_row, "1.25", "0.60"), catalog)
    assert [(f.severity, f.code, f.lines) for f in findings] == [(ERROR, "E_BASIS_DM_1000", (2, 3))]
    assert "1.500" in findings[0].message and CONFIRM_TOKEN in findings[0].message


@pytest.mark.parametrize(
    ("bases", "code"),
    [
        ((("PER_1000KCAL_ME", "8.37"), ("PER_MJ_ME", "2.000")), None),  # 2 × 4.184 = 8.368
        ((("PER_1000KCAL_ME", "8.50"), ("PER_MJ_ME", "2.000")), "E_BASIS_MJ_1000"),
        ((("PER_MJ_ME", "2.50"), ("PER_100G_DM", "4.184")), None),  # 4.184 × 2.5 / 4.184
        ((("PER_MJ_ME", "2.60"), ("PER_100G_DM", "4.184")), "E_BASIS_DM_MJ"),
        ((("PER_1000KCAL_ME", "10.0"), ("PER_100G_DM", "4.00")), None),
        ((("PER_1000KCAL_ME", "10.0"), ("PER_100G_DM", "4.10")), "E_BASIS_DM_1000"),
    ],
)
def test_basis_consistency(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    bases: tuple[tuple[str, str], ...],
    code: str | None,
) -> None:
    rows = [make_row(basis=basis, value=value) for basis, value in bases]
    codes = [f.code for f in validate_rows(rows, catalog)]
    assert codes == ([code] if code else [])


def test_basis_consistency_all_three_bases(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    consistent = [
        make_row(basis="PER_100G_DM", value="4.00"),
        make_row(basis="PER_1000KCAL_ME", value="10.0"),
        make_row(basis="PER_MJ_ME", value="2.39"),  # 10 / 4.184 = 2.390…
    ]
    assert validate_rows(consistent, catalog) == []
    wrong_mj = [*consistent[:2], make_row(basis="PER_MJ_ME", value="2.10")]
    assert sorted(f.code for f in validate_rows(wrong_mj, catalog)) == [
        "E_BASIS_DM_MJ",
        "E_BASIS_MJ_1000",
    ]


def test_basis_consistency_applies_to_maxima_but_not_ratios(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    maxima = [
        make_row(requirement_type="NUTRITIONAL_MAX", basis="PER_1000KCAL_ME", value="10.0"),
        make_row(requirement_type="NUTRITIONAL_MAX", basis="PER_100G_DM", value="10.0"),
    ]
    assert [f.code for f in validate_rows(maxima, catalog)] == ["E_BASIS_DM_1000"]
    ratios = [
        make_row(
            nutrient_code="CA_P",
            unit="ratio",
            requirement_type="RATIO_MAX",
            basis="PER_1000KCAL_ME",
            value="3",
        ),
        make_row(
            nutrient_code="CA_P",
            unit="ratio",
            requirement_type="RATIO_MAX",
            basis="PER_100G_DM",
            value="3",
        ),
    ]
    assert validate_rows(ratios, catalog) == []


def test_basis_consistency_only_within_same_requirement(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(basis="PER_1000KCAL_ME", value="10.0"),
        make_row(basis="PER_100G_DM", value="9.0", requirement_type="RA"),
    ]
    assert validate_rows(rows, catalog) == []


@pytest.mark.parametrize(
    ("notes", "severity"),
    [
        ((CONFIRM_TOKEN, f"ověřeno AA, {CONFIRM_TOKEN}"), WARNING),
        ((CONFIRM_TOKEN, ""), ERROR),
        (("", ""), ERROR),
        (("confirmed_as_printed", CONFIRM_TOKEN), ERROR),
    ],
)
def test_confirmation_token_downgrades_only_when_on_all_rows(
    catalog: dict[str, NutrientDef], make_row: RowFactory, notes: tuple[str, str], severity: str
) -> None:
    rows = [
        make_row(basis="PER_1000KCAL_ME", value="10.0", note=notes[0]),
        make_row(basis="PER_100G_DM", value="9.0", note=notes[1]),
    ]
    (finding,) = validate_rows(rows, catalog)
    assert (finding.code, finding.severity) == ("E_BASIS_DM_1000", severity)


# --- dvojice sloupců s nižší a vyšší referenční energií ----------------------------


@pytest.mark.parametrize(
    ("low_cells", "high_cells", "value_low", "value_high", "warned"),
    [
        # pes: hodnota(95) ≈ hodnota(110) × 110/95, sloupec 95 musí být VĚTŠÍ
        (DOG_LOW, {}, "11.6", "10.0", False),
        (DOG_LOW, {}, "10.0", "11.6", True),
        (DOG_LOW, {}, "10.0", "10.0", True),
        # kočka: hodnota(75) ≈ hodnota(100) × 100/75
        (CAT_LOW, CAT, "4.00", "3.00", False),
        (CAT_LOW, CAT, "3.00", "4.00", True),
    ],
)
def test_scaled_pair_direction(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    low_cells: dict[str, str],
    high_cells: dict[str, str],
    value_low: str,
    value_high: str,
    warned: bool,
) -> None:
    rows = [
        make_row(line=2, value=value_high, **high_cells),
        make_row(line=3, value=value_low, **low_cells),
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.severity, f.code, f.lines) for f in findings] == (
        [(WARNING, "W_SCALED_PAIR", (2, 3))] if warned else []
    )


def test_scaled_pair_ignores_life_stage_name(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(life_stage="ADULT_MAINTENANCE_LOW", reference_energy_k="110", value="10.0"),
        make_row(life_stage="ADULT_MAINTENANCE", reference_energy_k="95", value="10.0"),
    ]
    assert [f.code for f in validate_rows(rows, catalog)] == ["W_SCALED_PAIR"]


@pytest.mark.parametrize(
    "cells",
    [
        pytest.param({"requirement_type": "NUTRITIONAL_MAX"}, id="nutricni-maximum"),
        pytest.param({"requirement_type": "LEGAL_MAX_EU"}, id="zakonne-maximum"),
        pytest.param({"requirement_type": "SUL"}, id="sul"),
        pytest.param(
            {"nutrient_code": "CA_P", "unit": "ratio", "requirement_type": "RATIO_MAX"}, id="pomer"
        ),
        pytest.param({"basis": "PER_KG_BW075"}, id="baze-metabolicka-hmotnost"),
    ],
)
def test_scaled_pair_never_applies_to_maxima_ratios_or_bw_basis(
    catalog: dict[str, NutrientDef], make_row: RowFactory, cells: dict[str, str]
) -> None:
    rows = [make_row(value="10.0", **cells), make_row(value="10.0", **DOG_LOW, **cells)]
    assert validate_rows(rows, catalog) == []


@pytest.mark.parametrize("basis", ["PER_100G_DM", "PER_1000KCAL_ME", "PER_MJ_ME"])
def test_scaled_pair_applies_to_all_energy_bases(
    catalog: dict[str, NutrientDef], make_row: RowFactory, basis: str
) -> None:
    rows = [make_row(basis=basis, value="10.0"), make_row(basis=basis, value="10.0", **DOG_LOW)]
    assert [f.code for f in validate_rows(rows, catalog)] == ["W_SCALED_PAIR"]


# --- determinismus ----------------------------------------------------------------


def test_findings_do_not_depend_on_row_order(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(requirement_type="MIN_RECOMMENDED", value="5.0"),
        make_row(requirement_type="NUTRITIONAL_MAX", value="4.0"),
        make_row(requirement_type="LEGAL_MAX_EU", value="3.0"),
        make_row(basis="PER_100G_DM", value="9.0"),
        make_row(basis="PER_MJ_ME", value="1.0"),
        make_row(value="5.0", **DOG_LOW),
        make_row(nutrient_code="CU", value="1.0"),
        make_row(nutrient_code="CU", value="2.0"),
        make_row(nutrient_code="VIT_D", unit="IU", value="1"),
        make_row(species="HORSE"),
        make_row(nutrient_code="P", unit="g", value="", source_page=""),
    ]
    expected = validate_rows(rows, catalog)
    assert {f.code for f in expected} >= {
        "E_MIN_NOT_BELOW_MAX",
        "E_BASIS_DM_1000",
        "E_BASIS_MJ_1000",
        "E_BASIS_DM_MJ",
        "W_SCALED_PAIR",
        "E_DUPLICATE_KEY",
        "W_NEEDS_CONVERSION",
        "E_UNKNOWN_SPECIES",
        "E_EMPTY_VALUE",
    }
    first_lines = [(f.lines[0], f.code) for f in expected]
    assert first_lines == sorted(first_lines)
    shuffler = random.Random(20261018)
    for _ in range(20):
        shuffled = rows[:]
        shuffler.shuffle(shuffled)
        assert validate_rows(shuffled, catalog) == expected
