"""Kontroly mezi řádky: minimum/maximum, převody bází, dvojice 95/110 a 75/100.

Čísla jsou syntetická (standard TESTSTD). Jedinou výjimkou je zdokumentovaný
příklad Ca 1.25 g / 1000 kcal ME ↔ 0.50 g / 100 g sušiny (docs/03 §3.3).
"""

import random
from collections.abc import Callable, Sequence
from decimal import ROUND_DOWN, localcontext

import pytest

from refdata.catalog import NutrientDef
from refdata.findings import ERROR, WARNING, Finding
from refdata.standard_rows import StandardRow
from refdata.validate import validate_rows
from refdata.vocab import CONFIRM_TOKEN

CAT = {"species": "CAT", "reference_energy_k": "100", "reference_energy_exponent": "0.67"}
DOG_LOW = {"life_stage": "ADULT_MAINTENANCE_LOW", "reference_energy_k": "95"}
CAT_LOW = {**CAT, "life_stage": "ADULT_MAINTENANCE_LOW", "reference_energy_k": "75"}
RATIO = {"nutrient_code": "CA_P", "unit": "ratio"}

RowFactory = Callable[..., StandardRow]


def _found(findings: list[Finding], code: str) -> list[Finding]:
    return [finding for finding in findings if finding.code == code]


def _errors(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.severity == ERROR]


def _rows(make_row: RowFactory, cells: Sequence[dict[str, str]]) -> list[StandardRow]:
    return [make_row(**overrides) for overrides in cells]


# (kód, závažnost, řádky s nálezem na ř. 2 a 3, blízká varianta bez nálezu)
CROSS_CASES = [
    (
        "E_DUPLICATE_KEY",
        ERROR,
        [{}, {"value": "20.0"}],
        [{}, {"condition_note": "suché krmivo", "value": "20.0"}],
    ),
    (
        "E_MIN_NOT_BELOW_MAX",
        ERROR,
        [{"value": "5.0"}, {"requirement_type": "NUTRITIONAL_MAX", "value": "5.0"}],
        [{"value": "4.9"}, {"requirement_type": "NUTRITIONAL_MAX", "value": "5.0"}],
    ),
    (
        "W_NUTRITIONAL_ABOVE_LEGAL",
        WARNING,
        [
            {"requirement_type": "NUTRITIONAL_MAX", "value": "6.0"},
            {"requirement_type": "LEGAL_MAX_EU", "value": "5.0"},
        ],
        [
            {"requirement_type": "NUTRITIONAL_MAX", "value": "5.0"},
            {"requirement_type": "LEGAL_MAX_EU", "value": "5.0"},
        ],
    ),
    (
        "E_BASIS_DM_1000",
        ERROR,
        [{"value": "10.0"}, {"basis": "PER_100G_DM", "value": "4.10"}],
        [{"value": "10.0"}, {"basis": "PER_100G_DM", "value": "4.00"}],
    ),
    (
        "E_BASIS_MJ_1000",
        ERROR,
        [{"value": "8.50"}, {"basis": "PER_MJ_ME", "value": "2.000"}],
        [{"value": "8.37"}, {"basis": "PER_MJ_ME", "value": "2.000"}],
    ),
    (
        "E_BASIS_DM_MJ",
        ERROR,
        [{"basis": "PER_MJ_ME", "value": "2.60"}, {"basis": "PER_100G_DM", "value": "4.184"}],
        [{"basis": "PER_MJ_ME", "value": "2.50"}, {"basis": "PER_100G_DM", "value": "4.184"}],
    ),
    (
        "W_SCALED_PAIR",
        WARNING,
        [{"value": "10.0"}, {**DOG_LOW, "value": "10.0"}],
        [{"value": "10.0"}, {**DOG_LOW, "value": "11.6"}],
    ),
]


@pytest.mark.parametrize(
    ("code", "severity", "positive", "negative"), CROSS_CASES, ids=[c[0] for c in CROSS_CASES]
)
def test_cross_row_code_positive_and_negative(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    code: str,
    severity: str,
    positive: list[dict[str, str]],
    negative: list[dict[str, str]],
) -> None:
    findings = validate_rows(_rows(make_row, positive), catalog)
    assert [(f.code, f.severity, f.lines) for f in findings] == [(code, severity, (2, 3))]
    assert validate_rows(_rows(make_row, negative), catalog) == []


# --- minimum < maximum ---------------------------------------------------------


@pytest.mark.parametrize(
    ("low_type", "low", "high_type", "high", "expected"),
    [
        ("MIN_RECOMMENDED", "5.0", "NUTRITIONAL_MAX", "4.0", True),
        ("MIN_RECOMMENDED", "5.0", "NUTRITIONAL_MAX", "5.0", True),
        ("MIN_RECOMMENDED", "4.0", "NUTRITIONAL_MAX", "5.0", False),
        ("RA", "5.0", "LEGAL_MAX_EU", "5.00", True),
        ("AI", "5.0", "NUTRITIONAL_MAX", "5.0", True),
        ("AI", "4.9", "LEGAL_MAX_EU", "5.0", False),
        ("MR", "9", "SUL", "8", True),
        ("MR", "8", "SUL", "8", True),
        ("MR", "7", "SUL", "8", False),
        ("MIN_RECOMMENDED", "5.0", "LEGAL_MAX_EU", "5.0", True),
        ("MIN_RECOMMENDED", "5.1", "SUL", "5.0", True),
        # nutriční maximum proti zákonnému není chyba (W_NUTRITIONAL_ABOVE_LEGAL)
        ("NUTRITIONAL_MAX", "6.0", "LEGAL_MAX_EU", "5.0", False),
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
    assert [(f.severity, f.lines) for f in found] == ([(ERROR, (2, 3))] if expected else [])


@pytest.mark.parametrize(
    ("nutritional", "legal", "expected"),
    [("6.0", "5.0", True), ("5.01", "5.0", True), ("5.0", "5.00", False), ("4.0", "5.0", False)],
)
def test_nutritional_above_legal_is_only_a_warning(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    nutritional: str,
    legal: str,
    expected: bool,
) -> None:
    rows = [
        make_row(line=2, requirement_type="NUTRITIONAL_MAX", value=nutritional),
        make_row(line=3, requirement_type="LEGAL_MAX_EU", value=legal),
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.code, f.severity, f.lines) for f in findings] == (
        [("W_NUTRITIONAL_ABOVE_LEGAL", WARNING, (2, 3))] if expected else []
    )
    if expected:
        assert "neobvyklé, ale možné" in findings[0].message
        assert "originále" in findings[0].message


def test_legal_max_below_nutritional_max_still_bounds_minima(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    # Zákonné maximum EU pod nutričním maximem: minimum musí být pod oběma.
    rows = [
        make_row(line=2, requirement_type="MIN_RECOMMENDED", value="5.5"),
        make_row(line=3, requirement_type="NUTRITIONAL_MAX", value="6.0"),
        make_row(line=4, requirement_type="LEGAL_MAX_EU", value="5.0"),
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.code, f.severity, f.lines) for f in findings] == [
        ("E_MIN_NOT_BELOW_MAX", ERROR, (2, 4)),
        ("W_NUTRITIONAL_ABOVE_LEGAL", WARNING, (3, 4)),
    ]
    rows[0] = make_row(line=2, requirement_type="MIN_RECOMMENDED", value="4.5")
    assert [(f.code, f.severity) for f in validate_rows(rows, catalog)] == [
        ("W_NUTRITIONAL_ABOVE_LEGAL", WARNING)
    ]


def test_nutritional_above_legal_only_within_same_group(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    nutritional = make_row(requirement_type="NUTRITIONAL_MAX", value="6.0")
    legal = make_row(requirement_type="LEGAL_MAX_EU", value="5.0", basis="PER_100G_DM")
    codes = {f.code for f in validate_rows([nutritional, legal], catalog)}
    assert "W_NUTRITIONAL_ABOVE_LEGAL" not in codes


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
        make_row(line=2, **RATIO, requirement_type="RATIO_MIN", value=ratio_min),
        make_row(line=3, **RATIO, requirement_type="RATIO_MAX", value=ratio_max),
    ]
    found = _found(validate_rows(rows, catalog), "E_MIN_NOT_BELOW_MAX")
    assert [(f.severity, f.lines) for f in found] == ([(ERROR, (2, 3))] if expected else [])


def test_every_minimum_is_compared_with_every_maximum(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(line=2, requirement_type="MIN_RECOMMENDED", value="3.0"),
        make_row(line=3, requirement_type="RA", value="6.0"),
        make_row(line=4, requirement_type="NUTRITIONAL_MAX", value="5.0"),
        make_row(line=5, requirement_type="LEGAL_MAX_EU", value="5.5"),
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.code, f.severity, f.lines) for f in findings] == [
        ("E_MIN_NOT_BELOW_MAX", ERROR, (3, 4)),
        ("E_MIN_NOT_BELOW_MAX", ERROR, (3, 5)),
    ]


# Každá varianta mění právě jedno pole skupiny a sama o sobě je bez chyby.
MIN_MAX_GROUP_DIFFERENCES = [
    pytest.param({"condition_note": "suché krmivo"}, id="jina-podminka"),
    pytest.param({"basis": "PER_100G_DM"}, id="jina-baze"),
    pytest.param({"nutrient_code": "CU"}, id="jina-zivina"),
    pytest.param({"standard_code": "TESTSTD2"}, id="jiny-standard"),
    pytest.param({"edition": "2"}, id="jine-vydani"),
    pytest.param({"species": "CAT", "reference_energy_exponent": "0.67"}, id="jiny-druh-stejne-k"),
    pytest.param({"life_stage": "ADULT_MAINTENANCE_LOW"}, id="jina-faze-stejne-k"),
    pytest.param({"reference_energy_k": "95"}, id="jine-k-stejna-faze"),
    pytest.param(DOG_LOW, id="jiny-sloupec-k"),
]


@pytest.mark.parametrize("difference", MIN_MAX_GROUP_DIFFERENCES)
def test_min_max_only_within_same_group(
    catalog: dict[str, NutrientDef], make_row: RowFactory, difference: dict[str, str]
) -> None:
    minimum = make_row(requirement_type="MIN_RECOMMENDED", value="5.0")
    maximum = {"requirement_type": "NUTRITIONAL_MAX", "value": "4.0"}
    control = validate_rows([minimum, make_row(**maximum)], catalog)
    assert _found(control, "E_MIN_NOT_BELOW_MAX")
    varied = make_row(**maximum, **difference)
    assert _errors(validate_rows([varied], catalog)) == []
    assert not _found(validate_rows([minimum, varied], catalog), "E_MIN_NOT_BELOW_MAX")


def test_min_max_ignores_rows_with_errors(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(requirement_type="MIN_RECOMMENDED", value="5.0"),
        make_row(requirement_type="NUTRITIONAL_MAX", value="4.0", source_page=""),
    ]
    assert not _found(validate_rows(rows, catalog), "E_MIN_NOT_BELOW_MAX")


def test_duplicate_rows_are_left_out_of_cross_row_checks(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(line=2, requirement_type="MIN_RECOMMENDED", value="5.0"),
        make_row(line=3, requirement_type="MIN_RECOMMENDED", value="6.0"),
        make_row(line=4, requirement_type="NUTRITIONAL_MAX", value="4.0"),
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.code, f.severity, f.lines) for f in findings] == [
        ("E_DUPLICATE_KEY", ERROR, (2, 3))
    ]


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


def test_basis_consistency_applies_to_maxima(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    maxima = [
        make_row(requirement_type="NUTRITIONAL_MAX", basis="PER_1000KCAL_ME", value="10.0"),
        make_row(requirement_type="NUTRITIONAL_MAX", basis="PER_100G_DM", value="10.0"),
    ]
    assert [f.code for f in validate_rows(maxima, catalog)] == ["E_BASIS_DM_1000"]


@pytest.mark.parametrize(
    ("requirement_type", "bases", "code"),
    [
        ("RATIO_MAX", (("PER_1000KCAL_ME", "3"), ("PER_100G_DM", "3")), None),
        ("RATIO_MAX", (("PER_1000KCAL_ME", "2.0"), ("PER_100G_DM", "1.2")), "E_BASIS_DM_1000"),
        # 5.0 = 2.0 × 2.5: faktor 2.5 se na poměr nepoužije
        ("RATIO_MAX", (("PER_1000KCAL_ME", "5.0"), ("PER_100G_DM", "2.0")), "E_BASIS_DM_1000"),
        ("RATIO_MIN", (("PER_1000KCAL_ME", "1.5"), ("PER_MJ_ME", "1.50")), None),
        ("RATIO_MIN", (("PER_1000KCAL_ME", "1.5"), ("PER_MJ_ME", "1.7")), "E_BASIS_MJ_1000"),
        ("RATIO_MIN", (("PER_MJ_ME", "1.2"), ("PER_100G_DM", "1.4")), "E_BASIS_DM_MJ"),
    ],
)
def test_ratio_basis_consistency_uses_factor_1(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    requirement_type: str,
    bases: tuple[tuple[str, str], ...],
    code: str | None,
) -> None:
    rows = [
        make_row(**RATIO, requirement_type=requirement_type, basis=basis, value=value)
        for basis, value in bases
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.code, f.severity) for f in findings] == ([(code, ERROR)] if code else [])
    if code:
        assert "poměr na bázi nezávisí" in findings[0].message


# Každá varianta mění právě jedno pole skupiny a sama o sobě je bez chyby.
BASIS_GROUP_DIFFERENCES = [
    pytest.param({"nutrient_code": "CU"}, id="jina-zivina"),
    pytest.param({"requirement_type": "RA"}, id="jiny-typ"),
    pytest.param({"condition_note": "suché krmivo"}, id="jina-podminka"),
    pytest.param({"standard_code": "TESTSTD2"}, id="jiny-standard"),
    pytest.param({"edition": "2"}, id="jine-vydani"),
    pytest.param({"species": "CAT", "reference_energy_exponent": "0.67"}, id="jiny-druh-stejne-k"),
    pytest.param({"life_stage": "ADULT_MAINTENANCE_LOW"}, id="jina-faze-stejne-k"),
    pytest.param({"reference_energy_k": "95"}, id="jine-k-stejna-faze"),
]


@pytest.mark.parametrize("difference", BASIS_GROUP_DIFFERENCES)
def test_basis_consistency_only_within_same_group(
    catalog: dict[str, NutrientDef], make_row: RowFactory, difference: dict[str, str]
) -> None:
    per_1000 = make_row(basis="PER_1000KCAL_ME", value="10.0")
    per_dm = {"basis": "PER_100G_DM", "value": "1.0"}
    control = validate_rows([per_1000, make_row(**per_dm)], catalog)
    assert [f.code for f in control] == ["E_BASIS_DM_1000"]
    varied = make_row(**per_dm, **difference)
    assert _errors(validate_rows([varied], catalog)) == []
    codes = {f.code for f in validate_rows([per_1000, varied], catalog)}
    assert not codes & {"E_BASIS_DM_1000", "E_BASIS_MJ_1000", "E_BASIS_DM_MJ"}


def test_basis_consistency_only_between_rows_with_same_unit(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    vit_d = {"nutrient_code": "VIT_D", "unit": "ug"}
    same_unit = [
        make_row(**vit_d, basis="PER_1000KCAL_ME", value="500"),
        make_row(**vit_d, basis="PER_100G_DM", value="1.0"),
    ]
    assert [f.code for f in validate_rows(same_unit, catalog)] == ["E_BASIS_DM_1000"]
    in_iu = make_row(nutrient_code="VIT_D", unit="IU", basis="PER_100G_DM", value="1.0")
    other_unit = [same_unit[0], in_iu]
    assert [f.code for f in validate_rows(other_unit, catalog)] == ["W_NEEDS_CONVERSION"]


@pytest.mark.parametrize(
    ("notes", "severity"),
    [
        ((CONFIRM_TOKEN, f"ověřeno AA, {CONFIRM_TOKEN}"), WARNING),
        ((f"{CONFIRM_TOKEN} AA 2026-01-31", f"ověřeno: {CONFIRM_TOKEN}."), WARNING),
        ((CONFIRM_TOKEN, ""), ERROR),
        (("", ""), ERROR),
        (("confirmed_as_printed", CONFIRM_TOKEN), ERROR),
        (("NOT_CONFIRMED_AS_PRINTED", CONFIRM_TOKEN), ERROR),
        (("UNCONFIRMED_AS_PRINTED - zatím neověřeno", CONFIRM_TOKEN), ERROR),
        ((f"{CONFIRM_TOKEN}_NE", CONFIRM_TOKEN), ERROR),
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


def test_confirmation_token_does_not_downgrade_other_findings(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        make_row(requirement_type="MIN_RECOMMENDED", value="5.0", note=CONFIRM_TOKEN),
        make_row(requirement_type="NUTRITIONAL_MAX", value="4.0", note=CONFIRM_TOKEN),
    ]
    findings = validate_rows(rows, catalog)
    assert [(f.code, f.severity) for f in findings] == [("E_MIN_NOT_BELOW_MAX", ERROR)]


@pytest.mark.parametrize("column", ["condition_note", "source_table"])
def test_confirmation_token_counts_only_in_note(
    catalog: dict[str, NutrientDef], make_row: RowFactory, column: str
) -> None:
    rows = [
        make_row(basis="PER_1000KCAL_ME", value="10.0", **{column: CONFIRM_TOKEN}),
        make_row(basis="PER_100G_DM", value="9.0", **{column: CONFIRM_TOKEN}),
    ]
    (finding,) = validate_rows(rows, catalog)
    assert (finding.code, finding.severity) == ("E_BASIS_DM_1000", ERROR)


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


@pytest.mark.parametrize("requirement_type", ["MIN_RECOMMENDED", "MR", "AI", "RA"])
def test_scaled_pair_applies_to_all_minimum_types(
    catalog: dict[str, NutrientDef], make_row: RowFactory, requirement_type: str
) -> None:
    rows = [
        make_row(requirement_type=requirement_type, value="10.0"),
        make_row(requirement_type=requirement_type, value="10.0", **DOG_LOW),
    ]
    assert [f.code for f in validate_rows(rows, catalog)] == ["W_SCALED_PAIR"]


@pytest.mark.parametrize(
    ("high_cells", "low_cells"),
    [
        pytest.param({}, {**DOG_LOW, "reference_energy_k": "100"}, id="pes-100-a-110"),
        pytest.param(
            {**CAT, "reference_energy_k": "110"},
            {**CAT_LOW, "reference_energy_k": "95"},
            id="kocka-s-psi-dvojici",
        ),
    ],
)
def test_scaled_pair_needs_the_exact_species_pair(
    catalog: dict[str, NutrientDef],
    make_row: RowFactory,
    high_cells: dict[str, str],
    low_cells: dict[str, str],
) -> None:
    rows = [make_row(value="10.0", **high_cells), make_row(value="10.0", **low_cells)]
    assert validate_rows(rows, catalog) == []


def test_scaled_pair_only_pairs_adult_stages(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    adult = [make_row(value="10.0"), make_row(value="11.6", **DOG_LOW)]
    assert validate_rows(adult, catalog) == []
    growth_high = make_row(life_stage="EARLY_GROWTH_REPRO", reference_energy_k="110", value="20.0")
    assert validate_rows([*adult, growth_high], catalog) == []
    growth_low = make_row(life_stage="LATE_GROWTH", reference_energy_k="95", value="10.0")
    assert validate_rows([adult[0], growth_low], catalog) == []


# Každá varianta mění právě jedno pole skupiny a sama o sobě je bez chyby.
SCALED_GROUP_DIFFERENCES = [
    pytest.param({"basis": "PER_100G_DM"}, id="jina-baze"),
    pytest.param({"requirement_type": "RA"}, id="jiny-typ"),
    pytest.param({"nutrient_code": "CU"}, id="jina-zivina"),
    pytest.param({"condition_note": "suché krmivo"}, id="jina-podminka"),
    pytest.param({"standard_code": "TESTSTD2"}, id="jiny-standard"),
    pytest.param({"edition": "2"}, id="jine-vydani"),
]


@pytest.mark.parametrize("difference", SCALED_GROUP_DIFFERENCES)
def test_scaled_pair_only_within_same_group(
    catalog: dict[str, NutrientDef], make_row: RowFactory, difference: dict[str, str]
) -> None:
    high = make_row(value="10.0")
    low = {**DOG_LOW, "value": "10.0"}
    assert [f.code for f in validate_rows([high, make_row(**low)], catalog)] == ["W_SCALED_PAIR"]
    varied = make_row(**low, **difference)
    assert _errors(validate_rows([varied], catalog)) == []
    assert not _found(validate_rows([high, varied], catalog), "W_SCALED_PAIR")


def test_scaled_pair_only_between_rows_with_same_unit(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    high = make_row(nutrient_code="VIT_D", unit="ug", value="10.0")
    same_unit = make_row(nutrient_code="VIT_D", unit="ug", value="10.0", **DOG_LOW)
    other_unit = make_row(nutrient_code="VIT_D", unit="IU", value="10.0", **DOG_LOW)
    assert [f.code for f in validate_rows([high, same_unit], catalog)] == ["W_SCALED_PAIR"]
    assert [f.code for f in validate_rows([high, other_unit], catalog)] == ["W_NEEDS_CONVERSION"]


# --- velmi rozdílné řády a globální kontext ---------------------------------------


def test_very_different_magnitudes_do_not_crash(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    # očekávaná hodnota by na místa cílové hodnoty potřebovala víc než 28 číslic
    basis = [
        make_row(value="0.00000000000001"),
        make_row(basis="PER_100G_DM", value="999999999999999"),
    ]
    (finding,) = validate_rows(basis, catalog)
    assert finding.code == "E_BASIS_DM_1000" and "≈ 2499999999999997.5 " in finding.message
    scaled = [make_row(value="999999999999999"), make_row(value="0.00000000000001", **DOG_LOW)]
    assert [f.code for f in validate_rows(scaled, catalog)] == ["W_SCALED_PAIR"]


def test_validate_rows_does_not_depend_on_global_decimal_context(
    catalog: dict[str, NutrientDef], make_row: RowFactory
) -> None:
    rows = [
        *_ca_rows(make_row, "1.25", "0.60"),
        # 0.4024 × 2.5 = [1.005875; 1.006125] těsně nad [0.995; 1.005]
        make_row(nutrient_code="CU", basis="PER_1000KCAL_ME", value="1.00"),
        make_row(nutrient_code="CU", basis="PER_100G_DM", value="0.4024"),
        make_row(value="10.0"),
        make_row(value="11.51", **DOG_LOW),  # [11.505; 11.515] × 95 < 9.95 × 110
    ]
    expected = validate_rows(rows, catalog)
    assert [f.code for f in expected] == ["E_BASIS_DM_1000", "E_BASIS_DM_1000", "W_SCALED_PAIR"]
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        assert validate_rows(rows, catalog) == expected


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
        "W_NUTRITIONAL_ABOVE_LEGAL",
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
