"""Příkazová řádka ``python -m refdata``. Čísla jsou syntetická."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from refdata.catalog import CATALOG_HEADER
from refdata.cli import DEFAULT_CATALOG, main

WriteCsv = Callable[..., Path]


def _json_codes(output: str) -> list[str]:
    return [finding["code"] for finding in json.loads(output)["findings"]]


def test_default_catalog_is_resolved_from_package_location(catalog_path: Path) -> None:
    assert DEFAULT_CATALOG == catalog_path


def test_validate_clean_file_exits_0(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", str(write_csv([{}]))]) == 0
    output = capsys.readouterr().out
    assert "Žádné nálezy." in output and "Souhrn: chyby (ERROR) 0" in output


def test_validate_with_errors_exits_1(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", str(write_csv([{"value": "1,5"}]))]) == 1
    assert "E_PARSE_DECIMAL" in capsys.readouterr().out


def test_validate_reports_parse_error_once(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv([{"value": "1,5", "transcribed_at": "2026-13-01"}])
    assert main(["validate", str(path), "--json"]) == 1
    assert sorted(_json_codes(capsys.readouterr().out)) == ["E_BAD_DATE", "E_PARSE_DECIMAL"]


def test_validate_warnings_only_exit_0(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv([{"nutrient_code": "VIT_D", "unit": "IU"}])
    assert main(["validate", str(path), "--json"]) == 0
    assert _json_codes(capsys.readouterr().out) == ["W_NEEDS_CONVERSION"]


def test_validate_template_with_and_without_allow_empty(
    template_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", str(template_path), "--allow-empty"]) == 0
    assert "informace (INFO) 3" in capsys.readouterr().out
    assert main(["validate", str(template_path)]) == 1


def test_validate_header_error_exits_1(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv([{}], header=("species", "value"))
    assert main(["validate", str(path), "--json"]) == 1
    assert _json_codes(capsys.readouterr().out) == ["E_HEADER"]


def test_non_utf8_transcription_is_a_data_error_exit_1(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv([{"note": "poznámka é"}])
    path.write_bytes(path.read_text(encoding="utf-8").encode("latin-1"))
    assert main(["validate", str(path), "--json"]) == 1
    assert _json_codes(capsys.readouterr().out) == ["E_ENCODING"]


def test_number_with_too_many_digits_is_a_finding_not_a_crash(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(
        [{"value": "1.0000000001"}, {"basis": "PER_100G_DM", "value": "100000000000000000000"}]
    )
    assert main(["validate", str(path), "--json"]) == 1
    assert _json_codes(capsys.readouterr().out) == ["E_PARSE_DECIMAL"]


def test_validate_json_output(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(write_csv([{"source_page": ""}])), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"] == {"ERROR": 1, "INFO": 0, "WARNING": 0}
    assert payload["findings"][0]["code"] == "E_MISSING_PROVENANCE"
    assert payload["findings"][0]["lines"] == [2]


def test_validate_does_not_depend_on_working_directory(
    write_csv: WriteCsv,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = write_csv([{}])
    elsewhere = tmp_path / "jinde"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["validate", str(path)]) == 0


def test_validate_custom_catalog(write_csv: WriteCsv, tmp_path: Path) -> None:
    catalog = tmp_path / "katalog.csv"
    catalog.write_text(
        ",".join(CATALOG_HEADER) + "\nCU,Měď,Copper,TRACE,mg,yes,yes,A,\n", encoding="utf-8"
    )
    assert (
        main(["validate", str(write_csv([{"nutrient_code": "CU"}])), "--catalog", str(catalog)])
        == 0
    )
    assert main(["validate", str(write_csv([{}])), "--catalog", str(catalog)]) == 1  # ZN chybí


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="bez-prikazu"),
        pytest.param(["validate"], id="bez-cesty"),
        pytest.param(["frobnicate", "x.csv"], id="neznamy-prikaz"),
        pytest.param(["compare", "a.csv"], id="compare-bez-b"),
        pytest.param(["validate", "x.csv", "--strict"], id="neznamy-prepinac"),
    ],
)
def test_usage_errors_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "usage" in capsys.readouterr().err


def test_help_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "validate" in capsys.readouterr().out


def test_missing_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(tmp_path / "neexistuje.csv")]) == 2
    assert "Chyba:" in capsys.readouterr().err


def test_missing_or_invalid_catalog_exits_2(write_csv: WriteCsv, tmp_path: Path) -> None:
    path = str(write_csv([{}]))
    assert main(["validate", path, "--catalog", str(tmp_path / "chybi.csv")]) == 2
    broken = tmp_path / "rozbity.csv"
    broken.write_text("code,name\nZN,Zinek\n", encoding="utf-8")
    assert main(["validate", path, "--catalog", str(broken)]) == 2


def test_compare_independent_transcriptions_exit_0(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path_a = write_csv([{}], name="a.csv")
    path_b = write_csv([{"transcriber": "BB"}], name="b.csv")
    assert main(["compare", str(path_a), str(path_b)]) == 0
    assert "Žádné nálezy." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("row_b", "code"),
    [
        ({"transcriber": "BB", "value": "11.0"}, "E_VALUE_MISMATCH"),
        ({"transcriber": "AA"}, "E_SAME_TRANSCRIBER"),
        ({"transcriber": "BB", "nutrient_code": "CU"}, "E_ONLY_IN_A"),
    ],
)
def test_compare_with_errors_exits_1(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], row_b: dict[str, str], code: str
) -> None:
    path_a = write_csv([{}], name="a.csv")
    path_b = write_csv([row_b], name="b.csv")
    assert main(["compare", str(path_a), str(path_b), "--json"]) == 1
    assert code in _json_codes(capsys.readouterr().out)


def test_compare_includes_parse_findings_of_both_files(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path_a = write_csv([{"value": "1,5"}], name="a.csv")
    path_b = write_csv([{"transcriber": "BB", "transcribed_at": "2026-02-30"}], name="b.csv")
    assert main(["compare", str(path_a), str(path_b), "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    labelled = {(f["code"], f["message"].split(":")[0]) for f in findings}
    assert ("E_PARSE_DECIMAL", "Soubor A") in labelled
    assert ("E_BAD_DATE", "Soubor B") in labelled
    assert "E_VALUE_MISMATCH" in {f["code"] for f in findings}


# (kód, soubor A s nálezem, soubor A bez nálezu); soubor B je vždy platný
COMPARE_SKIP_CASES = [
    ("I_COMPARE_SKIPPED", {"header": ("species", "value")}, {}),
]


@pytest.mark.parametrize(
    ("code", "broken_a", "fine_a"), COMPARE_SKIP_CASES, ids=[c[0] for c in COMPARE_SKIP_CASES]
)
def test_compare_skips_comparison_when_file_cannot_be_read_completely(
    write_csv: WriteCsv,
    capsys: pytest.CaptureFixture[str],
    code: str,
    broken_a: dict[str, tuple[str, ...]],
    fine_a: dict[str, tuple[str, ...]],
) -> None:
    path_b = str(write_csv([{"transcriber": "BB"}], name="b.csv"))
    path_a = str(write_csv([{}], name="a.csv", **broken_a))
    assert main(["compare", path_a, path_b, "--json"]) == 1
    assert _json_codes(capsys.readouterr().out) == [code, "E_HEADER"]
    path_a = str(write_csv([{}], name="a.csv", **fine_a))
    assert main(["compare", path_a, path_b, "--json"]) == 0
    assert _json_codes(capsys.readouterr().out) == []


def test_compare_missing_file_exits_2(write_csv: WriteCsv, tmp_path: Path) -> None:
    assert main(["compare", str(write_csv([{}])), str(tmp_path / "b.csv")]) == 2


def test_module_entry_point_runs_from_any_directory(
    write_csv: WriteCsv, tmp_path: Path, repo_root: Path
) -> None:
    path = write_csv([{}])
    environment = {**os.environ, "PYTHONPATH": str(repo_root)}
    result = subprocess.run(
        [sys.executable, "-m", "refdata", "validate", str(path)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Souhrn" in result.stdout
