"""Příkazová řádka: ``python -m refdata validate`` a ``python -m refdata compare``.

Návratové kódy: 0 = žádná chyba (ERROR), 1 = alespoň jedna chyba,
2 = chybné použití nebo nečitelný soubor či katalog.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from refdata.catalog import CatalogError, load_catalog
from refdata.compare import LABEL_A, LABEL_B, compare_transcriptions
from refdata.findings import INFO, Finding, has_errors, merge_findings
from refdata.report import format_text, to_json
from refdata.standard_rows import FILE_LEVEL_CODES, load_standard_csv
from refdata.validate import validate_rows

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 2

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "reference" / "nutrients.csv"
"""Katalog živin v repozitáři (určený podle umístění balíčku, ne podle CWD)."""


def main(argv: Sequence[str] | None = None) -> int:
    """Spustí příkaz a vrátí návratový kód.

    Vstup: argumenty bez názvu programu (``None`` = ``sys.argv[1:]``).
    Výstup: 0, 1 nebo 2 (viz modul). Výsledek se tiskne na stdout, chyby
    použití a čtení souborů na stderr.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        if args.command == "validate":
            return _run_validate(args.path, args.catalog, args.allow_empty, args.json)
        return _run_compare(args.path_a, args.path_b, args.json)
    except (OSError, CatalogError) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m refdata",
        description="Kontrola dvojího přepisu tabulek nutričního standardu.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="zkontroluje jeden soubor přepisu")
    validate.add_argument("path", type=Path, help="CSV podle šablony importu")
    validate.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="katalog živin (výchozí: data/reference/nutrients.csv v repozitáři)",
    )
    validate.add_argument(
        "--allow-empty",
        action="store_true",
        help="rozpracovaný přepis: nevyplněné řádky hlásit jen jako INFO",
    )
    validate.add_argument("--json", action="store_true", help="výstup ve formátu JSON")
    compare = commands.add_parser("compare", help="porovná přepis A s přepisem B")
    compare.add_argument("path_a", type=Path, help="přepis A")
    compare.add_argument("path_b", type=Path, help="přepis B")
    compare.add_argument("--json", action="store_true", help="výstup ve formátu JSON")
    return parser


def _run_validate(path: Path, catalog_path: Path, allow_empty: bool, as_json: bool) -> int:
    catalog = load_catalog(catalog_path)
    rows, load_findings = load_standard_csv(path)
    findings = merge_findings(load_findings, validate_rows(rows, catalog, allow_empty))
    return _emit(findings, f"Kontrola přepisu: {path}", as_json)


def _run_compare(path_a: Path, path_b: Path, as_json: bool) -> int:
    rows_a, findings_a = load_standard_csv(path_a)
    rows_b, findings_b = load_standard_csv(path_b)
    findings = [
        *(_labelled(finding, LABEL_A) for finding in findings_a),
        *(_labelled(finding, LABEL_B) for finding in findings_b),
    ]
    if any(finding.code in FILE_LEVEL_CODES for finding in (*findings_a, *findings_b)):
        findings.append(
            Finding(
                INFO,
                "I_COMPARE_SKIPPED",
                "Porovnání neproběhlo, protože alespoň jeden soubor nelze celý načíst. "
                "Opravte chyby souboru a spusťte porovnání znovu.",
            )
        )
    else:
        findings.extend(compare_transcriptions(rows_a, rows_b))
    title = f"Porovnání přepisů: A = {path_a}, B = {path_b}"
    return _emit(merge_findings(findings), title, as_json)


def _labelled(finding: Finding, label: str) -> Finding:
    return replace(finding, message=f"Soubor {label}: {finding.message}")


def _emit(findings: list[Finding], title: str, as_json: bool) -> int:
    sys.stdout.write(to_json(findings) + "\n" if as_json else format_text(findings, title))
    return EXIT_ERRORS if has_errors(findings) else EXIT_OK
