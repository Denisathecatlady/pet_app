"""Řádkové kontroly :func:`refdata.validate.validate_rows`.

Každý kód má pozitivní případ (nález vznikne) a negativní případ (blízká
platná varianta bez nálezu). Čísla jsou syntetická.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from refdata.catalog import NutrientDef
from refdata.findings import ERROR, INFO, WARNING
from refdata.standard_rows import StandardRow, load_standard_csv
from refdata.validate import validate_rows

CAT = {"species": "CAT", "reference_energy_k": "100", "reference_energy_exponent": "0.67"}

# (kód, závažnost, pole pozitivního případu, pole negativního případu, allow_empty)
ROW_CASES = [
    ("E_UNKNOWN_SPECIES", ERROR, {"species": "HORSE"}, {"species": "DOG"}, False),
    ("E_UNKNOWN_SPECIES", ERROR, {"species": "dog"}, CAT, False),
    (
        "E_UNKNOWN_LIFE_STAGE",
        ERROR,
        {"life_stage": "GROWTH_REPRO"},
        {"life_stage": "LATE_GROWTH"},
        False,
    ),
    (
        "E_UNKNOWN_LIFE_STAGE",
        ERROR,
        {**CAT, "life_stage": "LATE_GROWTH"},
        {**CAT, "life_stage": "GROWTH_REPRO"},
        False,
    ),
    (
        "E_UNKNOWN_LIFE_STAGE",
        ERROR,
        {"life_stage": "SENIOR"},
        {"life_stage": "ADULT_MAINTENANCE_LOW", "reference_energy_k": "95"},
        False,
    ),
    (
        "E_UNKNOWN_REQ_TYPE",
        ERROR,
        {"requirement_type": "MINIMUM"},
        {"requirement_type": "RA"},
        False,
    ),
    ("E_UNKNOWN_BASIS", ERROR, {"basis": "PER_100G_AS_FED"}, {"basis": "PER_100G_DM"}, False),
    (
        "E_UNKNOWN_UNIT",
        ERROR,
        {"unit": "µg", "nutrient_code": "SE"},
        {"unit": "ug", "nutrient_code": "SE"},
        False,
    ),
    ("E_UNKNOWN_UNIT", ERROR, {"unit": ""}, {"unit": "mg"}, False),
    ("E_UNKNOWN_NUTRIENT", ERROR, {"nutrient_code": "UNOBTAINIUM"}, {"nutrient_code": "CU"}, False),
    ("E_PARSE_DECIMAL", ERROR, {"value": "1,25"}, {"value": "1.25"}, False),
    (
        "E_PARSE_DECIMAL",
        ERROR,
        {"reference_energy_k": "110 kcal"},
        {"reference_energy_k": "110.0"},
        False,
    ),
    (
        "E_PARSE_DECIMAL",
        ERROR,
        {"reference_energy_exponent": "0,75"},
        {"reference_energy_exponent": "0.750"},
        False,
    ),
    ("E_NONPOSITIVE_VALUE", ERROR, {"value": "0"}, {"value": "0.01"}, False),
    ("E_NONPOSITIVE_VALUE", ERROR, {"value": "0.00"}, {"value": "7"}, False),
    (
        "E_SPECIES_EXPONENT",
        ERROR,
        {"reference_energy_exponent": "0.67"},
        {"reference_energy_exponent": "0.75"},
        False,
    ),
    ("E_SPECIES_EXPONENT", ERROR, {**CAT, "reference_energy_exponent": "0.75"}, CAT, False),
    (
        "E_SPECIES_EXPONENT",
        ERROR,
        {"reference_energy_exponent": ""},
        {"reference_energy_exponent": "0.750"},
        False,
    ),
    ("E_BASIS_SPECIES", ERROR, {"basis": "PER_KG_BW067"}, {"basis": "PER_KG_BW075"}, False),
    (
        "E_BASIS_SPECIES",
        ERROR,
        {**CAT, "basis": "PER_KG_BW075"},
        {**CAT, "basis": "PER_KG_BW067"},
        False,
    ),
    (
        "E_MISSING_REF_ENERGY",
        ERROR,
        {"reference_energy_k": ""},
        {"reference_energy_k": "110"},
        False,
    ),
    (
        "E_MISSING_REF_ENERGY",
        ERROR,
        {**CAT, "life_stage": "ADULT_MAINTENANCE_LOW", "reference_energy_k": ""},
        {**CAT, "life_stage": "GROWTH_REPRO", "reference_energy_k": ""},
        False,
    ),
    (
        "E_MISSING_REF_ENERGY",
        ERROR,
        {"reference_energy_k": ""},
        {"life_stage": "EARLY_GROWTH_REPRO", "reference_energy_k": ""},
        False,
    ),
    (
        "E_RATIO_TYPE",
        ERROR,
        {"nutrient_code": "CA_P", "requirement_type": "MIN_RECOMMENDED", "unit": "ratio"},
        {"nutrient_code": "CA_P", "requirement_type": "RATIO_MAX", "unit": "ratio"},
        False,
    ),
    (
        "E_RATIO_TYPE",
        ERROR,
        {"nutrient_code": "CA_P", "requirement_type": "RATIO_MIN", "unit": "g"},
        {"nutrient_code": "CA_P", "requirement_type": "RATIO_MIN", "unit": "ratio"},
        False,
    ),
    (
        "E_RATIO_TYPE",
        ERROR,
        {"requirement_type": "RATIO_MAX"},
        {"requirement_type": "NUTRITIONAL_MAX"},
        False,
    ),
    ("E_RATIO_TYPE", ERROR, {"unit": "ratio"}, {"unit": "mg"}, False),
    ("E_UNIT_NOT_CANONICAL", ERROR, {"unit": "g"}, {"unit": "mg"}, False),
    (
        "E_UNIT_NOT_CANONICAL",
        ERROR,
        {"unit": "IU"},
        {"nutrient_code": "VIT_E", "unit": "mg"},
        False,
    ),
    (
        "E_UNIT_NOT_CANONICAL",
        ERROR,
        {"nutrient_code": "VIT_D", "unit": "mg"},
        {"nutrient_code": "VIT_D", "unit": "ug"},
        False,
    ),
    (
        "E_UNIT_NOT_CANONICAL",
        ERROR,
        {"nutrient_code": "VIT_B12", "unit": "IU"},
        {"nutrient_code": "VIT_B12", "unit": "ug"},
        False,
    ),
    (
        "W_NEEDS_CONVERSION",
        WARNING,
        {"nutrient_code": "VIT_D", "unit": "IU"},
        {"nutrient_code": "VIT_D", "unit": "ug"},
        False,
    ),
    (
        "W_NEEDS_CONVERSION",
        WARNING,
        {"nutrient_code": "VIT_A", "unit": "IU"},
        {"nutrient_code": "VIT_A", "unit": "ug"},
        False,
    ),
    (
        "W_NEEDS_CONVERSION",
        WARNING,
        {"nutrient_code": "VIT_E", "unit": "IU"},
        {"nutrient_code": "VIT_E", "unit": "mg"},
        False,
    ),
    ("E_KCAL_UNIT", ERROR, {"unit": "kcal"}, {"nutrient_code": "ENERGY_ME", "unit": "kcal"}, False),
    (
        "W_SPECIES_NOT_RELEVANT",
        WARNING,
        {"nutrient_code": "ARA", "unit": "g"},
        {**CAT, "nutrient_code": "ARA", "unit": "g"},
        False,
    ),
    (
        "W_SPECIES_NOT_RELEVANT",
        WARNING,
        {**CAT, "nutrient_code": "BETA_CAROTENE", "unit": "ug"},
        {"nutrient_code": "BETA_CAROTENE", "unit": "ug"},
        False,
    ),
    ("E_MISSING_PROVENANCE", ERROR, {"source_page": ""}, {"source_page": "12"}, False),
    ("E_MISSING_PROVENANCE", ERROR, {"source_table": ""}, {"source_table": "T-2"}, False),
    ("E_MISSING_PROVENANCE", ERROR, {"transcriber": ""}, {"transcriber": "BB"}, False),
    ("E_MISSING_PROVENANCE", ERROR, {"transcriber": ""}, {"value": "", "transcriber": ""}, True),
    (
        "E_BAD_DATE",
        ERROR,
        {"transcribed_at": "2026-02-30"},
        {"transcribed_at": "2026-02-28"},
        False,
    ),
    (
        "E_BAD_DATE",
        ERROR,
        {"transcribed_at": "2025-02-29"},
        {"transcribed_at": "2024-02-29"},
        False,
    ),
    ("E_BAD_DATE", ERROR, {"transcribed_at": "2026-1-5"}, {"transcribed_at": "2026-01-05"}, False),
    ("E_BAD_DATE", ERROR, {"transcribed_at": ""}, {"value": "", "transcribed_at": ""}, True),
    (
        "E_BAD_DATE",
        ERROR,
        {"value": "", "transcribed_at": "31.1.2026"},
        {"value": "", "transcribed_at": ""},
        True,
    ),
    ("E_EMPTY_VALUE", ERROR, {"value": ""}, {"value": "3.5"}, False),
    ("E_EMPTY_VALUE", ERROR, {"value": "  "}, {"value": " 3.5 "}, False),
    ("I_NOT_FILLED", INFO, {"value": ""}, {"value": "3.5"}, True),
]


def _ids(case: tuple) -> str:
    return case[0]


@pytest.mark.parametrize(
    ("code", "severity", "positive", "negative", "allow_empty"),
    ROW_CASES,
    ids=[_ids(case) for case in ROW_CASES],
)
def test_row_level_code_positive_and_negative(
    catalog: dict[str, NutrientDef],
    make_row: Callable[..., StandardRow],
    code: str,
    severity: str,
    positive: dict[str, str],
    negative: dict[str, str],
    allow_empty: bool,
) -> None:
    triggered = [
        f for f in validate_rows([make_row(**positive)], catalog, allow_empty) if f.code == code
    ]
    assert len(triggered) == 1
    assert triggered[0].severity == severity
    assert triggered[0].lines == (2,)
    assert triggered[0].message
    near_miss = validate_rows([make_row(**negative)], catalog, allow_empty)
    assert code not in {finding.code for finding in near_miss}


def test_valid_rows_have_no_findings(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    rows = [
        make_row(),
        make_row(**CAT, nutrient_code="TAURINE", unit="g", value="0.5"),
        make_row(nutrient_code="CA_P", requirement_type="RATIO_MAX", unit="ratio", value="3"),
        make_row(life_stage="LATE_GROWTH", reference_energy_k="", basis="PER_100G_DM"),
        make_row(basis="PER_KG_BW075", nutrient_code="CU"),
    ]
    assert validate_rows(rows, catalog) == []


def test_iu_vitamin_is_only_a_warning(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    findings = validate_rows([make_row(nutrient_code="VIT_D", unit="IU")], catalog)
    assert [(f.severity, f.code) for f in findings] == [(WARNING, "W_NEEDS_CONVERSION")]


@pytest.mark.parametrize(
    "cells",
    [
        pytest.param({"nutrient_code": "VIT_D", "unit": "mg"}, id="vitamin-d-v-mg"),
        pytest.param({"nutrient_code": "VIT_A", "unit": "mg"}, id="vitamin-a-v-mg"),
        pytest.param({"nutrient_code": "VIT_B12", "unit": "IU"}, id="iu-u-jineho-vitaminu"),
        pytest.param({"nutrient_code": "BETA_CAROTENE", "unit": "IU"}, id="iu-u-beta-karotenu"),
    ],
)
def test_iu_exception_covers_only_iu_for_vitamins_a_d_e(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow], cells: dict[str, str]
) -> None:
    findings = validate_rows([make_row(**cells)], catalog)
    assert [(f.severity, f.code) for f in findings] == [(ERROR, "E_UNIT_NOT_CANONICAL")]


def test_ratio_and_kcal_problems_are_not_double_reported_as_unit_problems(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    codes = {f.code for f in validate_rows([make_row(unit="ratio")], catalog)}
    assert codes == {"E_RATIO_TYPE"}
    codes = {f.code for f in validate_rows([make_row(unit="kcal")], catalog)}
    assert codes == {"E_KCAL_UNIT"}


def test_unknown_species_skips_species_dependent_checks(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    codes = {
        f.code for f in validate_rows([make_row(species="HORSE", basis="PER_KG_BW067")], catalog)
    }
    assert codes == {"E_UNKNOWN_SPECIES"}


def test_allow_empty_reports_unfilled_row_only_as_info(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    unfilled = make_row(value="", source_page="", transcriber="", transcribed_at="")
    lenient = validate_rows([unfilled], catalog, allow_empty=True)
    assert [(f.severity, f.code) for f in lenient] == [(INFO, "I_NOT_FILLED")]
    strict = validate_rows([unfilled], catalog)
    assert [f.code for f in strict] == ["E_BAD_DATE", "E_EMPTY_VALUE", "E_MISSING_PROVENANCE"]


def test_allow_empty_still_requires_provenance_for_filled_rows(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    filled = make_row(source_page="", transcriber="", transcribed_at="")
    codes = [f.code for f in validate_rows([filled], catalog, allow_empty=True)]
    assert codes == ["E_BAD_DATE", "E_MISSING_PROVENANCE"]


def test_missing_provenance_lists_all_missing_fields(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    (finding,) = validate_rows([make_row(source_table="", source_page="", transcriber="")], catalog)
    assert finding.code == "E_MISSING_PROVENANCE"
    assert "source_table, source_page, transcriber" in finding.message


def test_duplicate_key_reports_all_lines(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    rows = [
        make_row(line=2),
        make_row(line=3, nutrient_code="CU"),
        make_row(line=4, reference_energy_k="110.0", value="20.0"),
        make_row(line=7, value="30.0"),
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.code, f.severity, f.lines) for f in findings] == [
        ("E_DUPLICATE_KEY", ERROR, (2, 4, 7))
    ]
    assert findings[0].key == rows[0].key


def test_condition_note_distinguishes_otherwise_equal_keys(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow]
) -> None:
    rows = [make_row(condition_note="vlhké krmivo"), make_row(condition_note="suché krmivo")]
    assert validate_rows(rows, catalog) == []


@pytest.mark.parametrize(
    "variant",
    [
        pytest.param("for dry  food", id="dvojita-mezera"),
        pytest.param("for dry\nfood", id="zalomeni-radku"),
        pytest.param("for dry\u00a0food", id="nezlomitelna-mezera"),
    ],
)
def test_condition_note_copy_variants_are_one_cell(
    catalog: dict[str, NutrientDef], make_row: Callable[..., StandardRow], variant: str
) -> None:
    duplicates = [
        make_row(line=2, condition_note="for dry food"),
        make_row(line=3, condition_note=variant, value="20.0"),
    ]
    findings = validate_rows(duplicates, catalog)
    assert [(f.code, f.lines) for f in findings] == [("E_DUPLICATE_KEY", (2, 3))]
    min_max = [
        make_row(line=2, condition_note="for dry food", value="5.0"),
        make_row(line=3, condition_note=variant, requirement_type="NUTRITIONAL_MAX", value="4.0"),
    ]
    assert [f.code for f in validate_rows(min_max, catalog)] == ["E_MIN_NOT_BELOW_MAX"]


def test_template_validates_only_with_allow_empty(
    catalog: dict[str, NutrientDef], template_path: Path
) -> None:
    rows, load_findings = load_standard_csv(template_path)
    assert load_findings == []
    lenient = validate_rows(rows, catalog, allow_empty=True)
    assert not [f for f in lenient if f.severity == ERROR]
    assert {f.code for f in lenient} == {"I_NOT_FILLED"}
    strict = validate_rows(rows, catalog)
    assert {f.code for f in strict if f.severity == ERROR} >= {
        "E_EMPTY_VALUE",
        "E_MISSING_PROVENANCE",
    }
