"""Porovnání dvou nezávislých přepisů. Čísla jsou syntetická."""

import random
from collections.abc import Callable

import pytest

from refdata.compare import compare_transcriptions
from refdata.findings import ERROR, WARNING
from refdata.standard_rows import StandardRow

RowFactory = Callable[..., StandardRow]


def _pair(
    make_row: RowFactory, a: dict[str, str], b: dict[str, str]
) -> tuple[list[StandardRow], list[StandardRow]]:
    return [make_row(line=2, **a)], [make_row(line=5, **{"transcriber": "BB", **b})]


def test_identical_values_from_two_transcribers_have_no_findings(make_row: RowFactory) -> None:
    rows_a = [make_row(line=2), make_row(line=3, nutrient_code="CU", value="1.5")]
    rows_b = [
        make_row(line=3, transcriber="BB"),
        make_row(line=2, nutrient_code="CU", value="1.5", transcriber="BB"),
    ]
    assert compare_transcriptions(rows_a, rows_b) == []


# (kód, závažnost, pole v A, pole v B pro pozitivní případ, pole v B pro negativní případ)
PAIR_CASES = [
    ("E_VALUE_MISMATCH", ERROR, {"value": "10.0"}, {"value": "10.5"}, {"value": "10.0"}),
    ("E_VALUE_MISMATCH", ERROR, {"value": "10.0"}, {"value": ""}, {"value": " 10.0 "}),
    ("E_VALUE_MISMATCH", ERROR, {"value": ""}, {"value": "10.0"}, {"value": ""}),
    ("E_VALUE_MISMATCH", ERROR, {"value": "10,0"}, {"value": "10.0"}, {"value": "10,0"}),
    ("W_PRECISION_DIFFERS", WARNING, {"value": "1.0"}, {"value": "1.00"}, {"value": "1.0"}),
    ("W_PRECISION_DIFFERS", WARNING, {"value": "2"}, {"value": "2.0"}, {"value": "02"}),
    ("E_UNIT_MISMATCH", ERROR, {"unit": "mg"}, {"unit": "ug"}, {"unit": "mg"}),
    ("E_UNIT_MISMATCH", ERROR, {"unit": "mg"}, {"unit": "MG"}, {"unit": " mg "}),
    (
        "W_PROVENANCE_DIFFERS",
        WARNING,
        {"source_page": "12"},
        {"source_page": "13"},
        {"source_page": "12"},
    ),
    (
        "W_PROVENANCE_DIFFERS",
        WARNING,
        {"source_table": "T-1"},
        {"source_table": "T-2"},
        {"source_table": "T-1"},
    ),
    (
        "E_SAME_TRANSCRIBER",
        ERROR,
        {"transcriber": "AA"},
        {"transcriber": "aa"},
        {"transcriber": "BB"},
    ),
    (
        "E_SAME_TRANSCRIBER",
        ERROR,
        {"transcriber": "AA"},
        {"transcriber": "AA"},
        {"transcriber": ""},
    ),
    (
        "E_SAME_TRANSCRIBER",
        ERROR,
        {"transcriber": "A.A."},
        {"transcriber": "a a"},
        {"transcriber": "A.B."},
    ),
]


@pytest.mark.parametrize(
    ("code", "severity", "a", "b_positive", "b_negative"),
    PAIR_CASES,
    ids=[c[0] for c in PAIR_CASES],
)
def test_pair_code_positive_and_negative(
    make_row: RowFactory,
    code: str,
    severity: str,
    a: dict[str, str],
    b_positive: dict[str, str],
    b_negative: dict[str, str],
) -> None:
    findings = compare_transcriptions(*_pair(make_row, a, b_positive))
    assert [(f.code, f.severity) for f in findings] == [(code, severity)]
    assert findings[0].lines == (2, 5)
    assert "soubor A ř. 2" in findings[0].message and "soubor B ř. 5" in findings[0].message
    assert compare_transcriptions(*_pair(make_row, a, b_negative)) == []


def _rows(make_row: RowFactory, cells: list[dict[str, str]], **common: str) -> list[StandardRow]:
    return [make_row(**{**common, **overrides}) for overrides in cells]


# (kód, řádky A, řádky B s nálezem, řádky B bez nálezu); B přepisuje „BB“
KEY_CASES = [
    ("E_ONLY_IN_A", [{}, {"nutrient_code": "CU"}], [{}], [{}, {"nutrient_code": "CU"}]),
    ("E_ONLY_IN_B", [{}], [{}, {"nutrient_code": "MN"}], [{}]),
    ("E_DUPLICATE_KEY", [{}], [{}, {"value": "99.0"}], [{}]),
]


@pytest.mark.parametrize(
    ("code", "a", "b_positive", "b_negative"), KEY_CASES, ids=[c[0] for c in KEY_CASES]
)
def test_key_code_positive_and_negative(
    make_row: RowFactory,
    code: str,
    a: list[dict[str, str]],
    b_positive: list[dict[str, str]],
    b_negative: list[dict[str, str]],
) -> None:
    rows_a = _rows(make_row, a)
    findings = compare_transcriptions(rows_a, _rows(make_row, b_positive, transcriber="BB"))
    assert [(f.code, f.severity) for f in findings] == [(code, ERROR)]
    assert compare_transcriptions(rows_a, _rows(make_row, b_negative, transcriber="BB")) == []


def test_same_transcriber_is_reported_together_with_value_mismatch(make_row: RowFactory) -> None:
    rows = _pair(make_row, {"value": "10.0"}, {"value": "10.5", "transcriber": "AA"})
    findings = compare_transcriptions(*rows)
    assert [(f.code, f.severity) for f in findings] == [
        ("E_SAME_TRANSCRIBER", ERROR),
        ("E_VALUE_MISMATCH", ERROR),
    ]


def test_condition_note_copy_variants_are_paired(make_row: RowFactory) -> None:
    rows_a = [make_row(condition_note="for dry food")]
    rows_b = [make_row(condition_note="for dry\u00a0 food\n", transcriber="BB")]
    assert compare_transcriptions(rows_a, rows_b) == []
    rows_b = [make_row(condition_note="For dry food", transcriber="BB")]
    codes = [f.code for f in compare_transcriptions(rows_a, rows_b)]
    assert codes == ["E_ONLY_IN_A", "E_ONLY_IN_B"]


def test_precision_difference_is_not_a_value_mismatch(make_row: RowFactory) -> None:
    codes = [
        f.code
        for f in compare_transcriptions(*_pair(make_row, {"value": "1.0"}, {"value": "1.00"}))
    ]
    assert codes == ["W_PRECISION_DIFFERS"]


def test_both_transcribers_empty_is_not_same_transcriber(make_row: RowFactory) -> None:
    assert compare_transcriptions(*_pair(make_row, {"transcriber": ""}, {"transcriber": ""})) == []


def test_only_in_a_and_only_in_b(make_row: RowFactory) -> None:
    rows_a = [make_row(line=2), make_row(line=3, nutrient_code="CU")]
    rows_b = [
        make_row(line=2, transcriber="BB"),
        make_row(line=4, nutrient_code="MN", transcriber="BB"),
    ]
    findings = compare_transcriptions(rows_a, rows_b)
    assert [(f.code, f.lines) for f in findings] == [("E_ONLY_IN_A", (3,)), ("E_ONLY_IN_B", (4,))]
    assert "Řádek 3 souboru A" in findings[0].message
    assert "Řádek 4 souboru B" in findings[1].message
    assert all(f.severity == ERROR for f in findings)
    assert compare_transcriptions(rows_a[:1], rows_b[:1]) == []


def test_keys_match_after_numeric_normalization(make_row: RowFactory) -> None:
    rows_a = [make_row(reference_energy_k="110")]
    rows_b = [
        make_row(reference_energy_k="110.0", reference_energy_exponent="0.750", transcriber="BB")
    ]
    assert compare_transcriptions(rows_a, rows_b) == []


def test_duplicate_key_inside_one_file_is_reported(make_row: RowFactory) -> None:
    rows_a = [make_row(line=2), make_row(line=6, value="99.0")]
    rows_b = [make_row(line=2, transcriber="BB")]
    findings = compare_transcriptions(rows_a, rows_b)
    assert [(f.code, f.severity, f.lines) for f in findings] == [("E_DUPLICATE_KEY", ERROR, (2, 6))]
    assert findings[0].message.startswith("Soubor A:")


def test_duplicate_key_in_file_b_is_reported(make_row: RowFactory) -> None:
    rows_a = [make_row(line=2)]
    rows_b = [make_row(line=3, transcriber="BB"), make_row(line=8, value="99.0", transcriber="BB")]
    findings = compare_transcriptions(rows_a, rows_b)
    assert [(f.code, f.severity, f.lines) for f in findings] == [("E_DUPLICATE_KEY", ERROR, (3, 8))]
    assert findings[0].message.startswith("Soubor B:")


def test_compare_is_independent_of_row_order(make_row: RowFactory) -> None:
    rows_a = [
        make_row(line=2),
        make_row(line=3, nutrient_code="CU", value="1.0"),
        make_row(line=4, nutrient_code="MN", unit="ug"),
        make_row(line=5, nutrient_code="FE"),
        make_row(line=6, nutrient_code="FE", value="11.0"),
    ]
    rows_b = [
        make_row(line=2, transcriber="BB", value="10.00"),
        make_row(line=3, nutrient_code="CU", value="1.1", transcriber="BB"),
        make_row(line=4, nutrient_code="MN", transcriber="AA"),
        make_row(line=5, nutrient_code="I", transcriber="BB"),
    ]
    expected = compare_transcriptions(rows_a, rows_b)
    assert {f.code for f in expected} == {
        "W_PRECISION_DIFFERS",
        "E_VALUE_MISMATCH",
        "E_UNIT_MISMATCH",
        "E_SAME_TRANSCRIBER",
        "E_ONLY_IN_A",
        "E_ONLY_IN_B",
        "E_DUPLICATE_KEY",
    }
    shuffler = random.Random(7)
    for _ in range(20):
        shuffled_a, shuffled_b = rows_a[:], rows_b[:]
        shuffler.shuffle(shuffled_a)
        shuffler.shuffle(shuffled_b)
        assert compare_transcriptions(shuffled_a, shuffled_b) == expected
