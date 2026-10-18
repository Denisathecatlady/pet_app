"""Načtení přepisu ze šablony importu. Čísla jsou syntetická."""

from codecs import BOM_UTF8
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest

from refdata.standard_rows import (
    EXPECTED_HEADER,
    KEY_FIELDS,
    StandardRow,
    describe_key,
    find_duplicate_keys,
    load_standard_csv,
    parse_row,
    row_parse_findings,
)

HEADER_LINE = ",".join(EXPECTED_HEADER)
VALID_LINE = (
    "TESTSTD,1,DOG,ADULT_MAINTENANCE,110,0.75,PER_1000KCAL_ME,ZN,MIN_RECOMMENDED,10.0,mg,,"
    "T-1,1,AA,2026-01-31,"
)


def _write_lines(tmp_path: Path, *lines: str, prefix: bytes = b"") -> Path:
    path = tmp_path / "prepis.csv"
    path.write_bytes(prefix + "".join(f"{line}\n" for line in lines).encode("utf-8"))
    return path


def _codes(findings: list) -> list[str]:
    return [finding.code for finding in findings]


def test_expected_header_matches_template(template_path: Path) -> None:
    first_line = template_path.read_text(encoding="utf-8").splitlines()[0]
    assert tuple(first_line.split(",")) == EXPECTED_HEADER


def test_template_loads_without_findings(template_path: Path) -> None:
    rows, findings = load_standard_csv(template_path)
    assert findings == []
    assert [row.line for row in rows] == [2, 3, 4]
    assert all(row.value == "" and row.value_decimal is None for row in rows)
    assert rows[0].k_decimal == Decimal("110")


def test_valid_file_loads_parsed_fields(tmp_path: Path) -> None:
    rows, findings = load_standard_csv(_write_lines(tmp_path, HEADER_LINE, VALID_LINE))
    assert findings == []
    (row,) = rows
    assert row.line == 2
    assert row.value == "10.0" and row.value_decimal == Decimal("10.0")
    assert row.exponent_decimal == Decimal("0.75")
    assert row.transcribed_on is not None and row.transcribed_on.isoformat() == "2026-01-31"


def test_bom_is_accepted(tmp_path: Path) -> None:
    rows, findings = load_standard_csv(
        _write_lines(tmp_path, HEADER_LINE, VALID_LINE, prefix=BOM_UTF8)
    )
    assert findings == [] and len(rows) == 1


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(HEADER_LINE.replace(",note", ""), id="chybi-sloupec"),
        pytest.param(HEADER_LINE + ",extra", id="sloupec-navic"),
        pytest.param(HEADER_LINE.replace("value,unit", "unit,value"), id="poradi"),
        pytest.param(HEADER_LINE.replace("species", "Species"), id="velikost-pismen"),
        pytest.param(HEADER_LINE.replace("species", " species"), id="mezera"),
    ],
)
def test_header_mismatch_gives_single_error_and_no_rows(tmp_path: Path, header: str) -> None:
    rows, findings = load_standard_csv(_write_lines(tmp_path, header, VALID_LINE))
    assert rows == []
    assert _codes(findings) == ["E_HEADER"]
    assert findings[0].severity == "ERROR" and findings[0].lines == (1,)


def test_empty_file_gives_header_error(tmp_path: Path) -> None:
    path = tmp_path / "prazdny.csv"
    path.write_bytes(b"")
    rows, findings = load_standard_csv(path)
    assert rows == [] and _codes(findings) == ["E_HEADER"]


def test_non_utf8_gives_encoding_error_with_line(tmp_path: Path) -> None:
    path = tmp_path / "cp1250.csv"
    path.write_bytes(
        f"{HEADER_LINE}\n{VALID_LINE}\n{VALID_LINE.replace('T-1', 'Tabulka č. 1')}\n".encode(
            "cp1250"
        )
    )
    rows, findings = load_standard_csv(path)
    assert rows == []
    assert _codes(findings) == ["E_ENCODING"] and findings[0].lines == (3,)


def test_wrong_column_count_skips_row(tmp_path: Path) -> None:
    path = _write_lines(tmp_path, HEADER_LINE, VALID_LINE + ",navic", VALID_LINE)
    rows, findings = load_standard_csv(path)
    assert [row.line for row in rows] == [3]
    assert _codes(findings) == ["E_COLUMN_COUNT"] and findings[0].lines == (2,)


def test_broken_quotes_give_csv_syntax_error(tmp_path: Path) -> None:
    path = _write_lines(tmp_path, HEADER_LINE, VALID_LINE, VALID_LINE + '"x"y')
    rows, findings = load_standard_csv(path)
    assert [row.line for row in rows] == [2]
    assert _codes(findings) == ["E_CSV_SYNTAX"] and findings[0].lines == (3,)


def test_blank_rows_are_skipped_and_lines_stay_physical(tmp_path: Path) -> None:
    empty_cells = "," * (len(EXPECTED_HEADER) - 1)
    path = _write_lines(tmp_path, HEADER_LINE, "", empty_cells, VALID_LINE)
    rows, findings = load_standard_csv(path)
    assert findings == [] and [row.line for row in rows] == [4]


def test_multiline_quoted_cell_keeps_start_line(tmp_path: Path) -> None:
    multiline = VALID_LINE[:-1] + ',"první řádek\ndruhý řádek"'
    path = _write_lines(tmp_path, HEADER_LINE, multiline, VALID_LINE.replace("ZN", "CU"))
    rows, findings = load_standard_csv(path)
    assert findings == []
    assert [row.line for row in rows] == [2, 4]
    assert rows[0].note == "první řádek\ndruhý řádek"


@pytest.mark.parametrize(
    ("field", "text", "code"),
    [
        ("value", "1,25", "E_PARSE_DECIMAL"),
        ("value", "-1", "E_PARSE_DECIMAL"),
        ("reference_energy_k", "110 kcal", "E_PARSE_DECIMAL"),
        ("reference_energy_exponent", "0,75", "E_PARSE_DECIMAL"),
        ("transcribed_at", "2026-02-30", "E_BAD_DATE"),
        ("transcribed_at", "31.01.2026", "E_BAD_DATE"),
        ("transcribed_at", "20260131", "E_BAD_DATE"),
    ],
)
def test_parse_problems_become_findings(
    make_row: Callable[..., StandardRow],
    write_csv: Callable[..., Path],
    field: str,
    text: str,
    code: str,
) -> None:
    assert _codes(row_parse_findings(make_row(**{field: text}))) == [code]
    rows, findings = load_standard_csv(write_csv([{field: text}]))
    assert len(rows) == 1 and _codes(findings) == [code]
    assert findings[0].lines == (2,) and findings[0].key == rows[0].key


def test_valid_and_empty_fields_are_not_parse_problems(
    make_row: Callable[..., StandardRow],
) -> None:
    assert row_parse_findings(make_row()) == []
    assert row_parse_findings(make_row(value="", reference_energy_k="", transcribed_at="")) == []


def test_key_normalizes_numbers_and_whitespace(make_row: Callable[..., StandardRow]) -> None:
    plain = make_row(reference_energy_k="110", reference_energy_exponent="0.75")
    padded = make_row(
        reference_energy_k="110.0", reference_energy_exponent=" 0.750 ", species=" DOG "
    )
    assert plain.key == padded.key
    assert len(plain.key) == len(KEY_FIELDS)
    assert plain.key[4:6] == ("110", "0.75")
    assert make_row(condition_note="vlhké krmivo").key != plain.key
    # neplatné číslo zůstává v klíči jako text
    assert make_row(reference_energy_k="1l0").key[4] == "1l0"


def test_value_and_unit_are_not_part_of_key(make_row: Callable[..., StandardRow]) -> None:
    assert make_row(value="10.0").key == make_row(value="20.0", unit="ug").key


def test_find_duplicate_keys_and_describe_key(make_row: Callable[..., StandardRow]) -> None:
    rows = [
        make_row(line=5),
        make_row(line=2, reference_energy_k="110.0"),
        make_row(line=3, nutrient_code="CU"),
    ]
    assert find_duplicate_keys(rows) == {rows[0].key: (2, 5)}
    description = describe_key(rows[0].key)
    assert "standard_code=TESTSTD" in description and "condition_note" not in description


def test_parse_row_rejects_unknown_column() -> None:
    with pytest.raises(ValueError):
        parse_row({"valeu": "1"}, 2)


def test_row_is_frozen(make_row: Callable[..., StandardRow]) -> None:
    with pytest.raises(FrozenInstanceError):
        make_row().value = "1"  # type: ignore[misc]
