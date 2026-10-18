"""Načtení přepisu tabulek standardu ze šablony importu.

Formát odpovídá ``data/reference/standard_import_template.csv``: jedna buňka
tabulky standardu = jeden řádek CSV. Problémy se souborem a s parsováním
čísel a dat se vracejí jako nálezy (:class:`~refdata.findings.Finding`),
nikdy jako výjimky.
"""

import csv
import io
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from os import PathLike
from pathlib import Path
from typing import Final

from refdata.decimal_utils import DECIMAL_CONTEXT, DecimalParseError, parse_decimal
from refdata.findings import ERROR, Finding

EXPECTED_HEADER: Final = (
    "standard_code",
    "edition",
    "species",
    "life_stage",
    "reference_energy_k",
    "reference_energy_exponent",
    "basis",
    "nutrient_code",
    "requirement_type",
    "value",
    "unit",
    "condition_note",
    "source_table",
    "source_page",
    "transcriber",
    "transcribed_at",
    "note",
)
"""Přesná hlavička šablony importu (řádek 1 souboru)."""

KEY_FIELDS: Final = (
    "standard_code",
    "edition",
    "species",
    "life_stage",
    "reference_energy_k",
    "reference_energy_exponent",
    "basis",
    "nutrient_code",
    "requirement_type",
    "condition_note",
)
"""Pole, která společně identifikují jednu buňku tabulky standardu."""

DECIMAL_FIELDS: Final = ("value", "reference_energy_k", "reference_energy_exponent")
"""Pole parsovaná jako ``Decimal`` (:func:`refdata.decimal_utils.parse_decimal`)."""

FILE_LEVEL_CODES: Final = frozenset({"E_ENCODING", "E_HEADER", "E_CSV_SYNTAX"})
"""Kódy nálezů, po kterých nejsou načtené řádky úplné."""

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

Key = tuple[str, ...]


@dataclass(frozen=True)
class StandardRow:
    """Jeden řádek přepisu (jedna buňka tabulky standardu).

    Textová pole jsou ve tvaru ze souboru bez okolních mezer. Parsovaná pole
    jsou ``None``, pokud je text prázdný nebo neplatný (rozliší se podle
    textového pole). ``line`` je číslo řádku v souboru (hlavička = 1).
    """

    line: int
    standard_code: str
    edition: str
    species: str
    life_stage: str
    reference_energy_k: str
    reference_energy_exponent: str
    basis: str
    nutrient_code: str
    requirement_type: str
    value: str
    unit: str
    condition_note: str
    source_table: str
    source_page: str
    transcriber: str
    transcribed_at: str
    note: str
    value_decimal: Decimal | None
    k_decimal: Decimal | None
    exponent_decimal: Decimal | None
    transcribed_on: date | None

    def normalized(self, field: str) -> str:
        """Vrátí normalizovaný text pole pro klíče a seskupování.

        Vstup: název sloupce z :data:`EXPECTED_HEADER`. Referenční energie a
        exponent s platnou hodnotou se normalizují přes ``Decimal`` (``"110"``
        i ``"110.0"`` → ``"110"``), ostatní pole se vrací tak, jak jsou.
        Chyby: ``ValueError`` pro název, který není sloupcem přepisu.
        """
        if field not in EXPECTED_HEADER:
            raise ValueError(f"Neznámý sloupec přepisu: {field}.")
        parsed = {
            "reference_energy_k": self.k_decimal,
            "reference_energy_exponent": self.exponent_decimal,
        }.get(field)
        if parsed is not None:
            return format(parsed.normalize(DECIMAL_CONTEXT), "f")
        text: str = getattr(self, field)
        return text

    @property
    def key(self) -> Key:
        """Klíč řádku: normalizovaná pole :data:`KEY_FIELDS`."""
        return tuple(self.normalized(field) for field in KEY_FIELDS)


def parse_row(cells: Mapping[str, str], line: int) -> StandardRow:
    """Vytvoří :class:`StandardRow` z hodnot sloupců.

    Vstup: slovník ``sloupec → text`` (chybějící sloupce = prázdný text) a
    číslo řádku. Neplatná čísla a data se neohlásí výjimkou, ale zůstanou
    jako ``None``; nálezy k nim vrací :func:`row_parse_findings`.

    Chyby: ``ValueError`` pro sloupec, který není v :data:`EXPECTED_HEADER`
    (chyba programu, ne dat).
    """
    unknown = set(cells) - set(EXPECTED_HEADER)
    if unknown:
        raise ValueError(f"Neznámé sloupce přepisu: {', '.join(sorted(unknown))}.")
    text = {field: cells.get(field, "").strip() for field in EXPECTED_HEADER}
    return StandardRow(
        line=line,
        **text,
        value_decimal=_try_decimal(text["value"]),
        k_decimal=_try_decimal(text["reference_energy_k"]),
        exponent_decimal=_try_decimal(text["reference_energy_exponent"]),
        transcribed_on=_try_iso_date(text["transcribed_at"]),
    )


def row_parse_findings(row: StandardRow) -> list[Finding]:
    """Vrátí nálezy k neplatným číslům a datu jednoho řádku.

    Vstup: řádek. Výstup: ``E_PARSE_DECIMAL`` pro každé neprázdné neplatné
    číselné pole a ``E_BAD_DATE`` pro neprázdné neplatné datum přepisu.
    Prázdná pole hlásí až :func:`refdata.validate.validate_rows`.
    """
    findings = []
    for field in DECIMAL_FIELDS:
        raw = getattr(row, field)
        if not raw:
            continue
        try:
            parse_decimal(raw)
        except DecimalParseError as exc:
            findings.append(
                Finding(ERROR, "E_PARSE_DECIMAL", f"Sloupec {field}: {exc}", (row.line,), row.key)
            )
    if row.transcribed_at and row.transcribed_on is None:
        findings.append(
            Finding(
                ERROR,
                "E_BAD_DATE",
                f"Datum přepisu „{row.transcribed_at}“ není skutečné datum ve tvaru "
                "RRRR-MM-DD. Zapište je např. jako 2026-01-31.",
                (row.line,),
                row.key,
            )
        )
    return findings


def find_duplicate_keys(rows: Iterable[StandardRow]) -> dict[Key, tuple[int, ...]]:
    """Najde klíče, které se v řádcích opakují.

    Vstup: řádky jednoho souboru. Výstup: ``klíč → vzestupně seřazená čísla
    řádků`` jen pro klíče s více než jedním řádkem.
    """
    lines_by_key: defaultdict[Key, list[int]] = defaultdict(list)
    for row in rows:
        lines_by_key[row.key].append(row.line)
    return {key: tuple(sorted(lines)) for key, lines in lines_by_key.items() if len(lines) > 1}


def describe_key(key: Key) -> str:
    """Vrátí čitelný popis klíče řádku pro zprávy nálezů.

    Vstup: klíč ve tvaru :attr:`StandardRow.key`. Výstup: text typu
    ``standard_code=…, edition=…, …`` (prázdná pole se vynechají).
    """
    return ", ".join(
        f"{name}={value}" for name, value in zip(KEY_FIELDS, key, strict=True) if value
    )


def load_standard_csv(path: str | PathLike[str]) -> tuple[list[StandardRow], list[Finding]]:
    """Načte přepis tabulek standardu z CSV.

    Vstup: cesta k souboru v UTF-8 (BOM povolen), oddělovač čárka,
    hlavička přesně :data:`EXPECTED_HEADER`.

    Výstup: ``(řádky, nálezy)``. Nálezy (vždy ``ERROR``):
    ``E_ENCODING`` (soubor není UTF-8; žádné řádky), ``E_HEADER`` (chybí nebo
    nesouhlasí hlavička; žádné řádky), ``E_CSV_SYNTAX`` (chybné uvozovky;
    vrátí se řádky před chybou), ``E_COLUMN_COUNT`` (řádek s jiným počtem
    sloupců se vynechá) a nálezy :func:`row_parse_findings`. Zcela prázdné
    řádky se přeskočí.

    Chyby: ``OSError``, pokud soubor nelze přečíst (nejde o problém dat).
    """
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        line = data.count(b"\n", 0, exc.start) + 1
        message = "Soubor není v kódování UTF-8. Uložte jej znovu jako „CSV UTF-8“."
        return [], [Finding(ERROR, "E_ENCODING", message, (line,))]
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows: list[StandardRow] = []
    findings: list[Finding] = []
    try:
        header = next(reader, None)
        if header is None or tuple(header) != EXPECTED_HEADER:
            return [], [_header_finding(header)]
        while True:
            start_line = reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if not any(cell.strip() for cell in cells):
                continue
            if len(cells) != len(EXPECTED_HEADER):
                findings.append(_column_count_finding(len(cells), start_line))
                continue
            row = parse_row(dict(zip(EXPECTED_HEADER, cells, strict=True)), start_line)
            rows.append(row)
            findings.extend(row_parse_findings(row))
    except csv.Error as exc:
        message = (
            f"Chybný zápis CSV ({exc}). Zkontrolujte uvozovky na řádku a uložte soubor "
            "znovu jako CSV s oddělovačem čárka."
        )
        findings.append(Finding(ERROR, "E_CSV_SYNTAX", message, (reader.line_num,)))
    return rows, findings


def _try_decimal(text: str) -> Decimal | None:
    try:
        return parse_decimal(text)
    except DecimalParseError:
        return None


def _try_iso_date(text: str) -> date | None:
    if not _ISO_DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _header_finding(header: list[str] | None) -> Finding:
    found = "soubor je prázdný" if header is None else f"nalezeno: {','.join(header)}"
    message = (
        f"Hlavička souboru nesouhlasí se šablonou ({found}). Zkopírujte první řádek "
        f"přesně ze šablony data/reference/standard_import_template.csv: "
        f"{','.join(EXPECTED_HEADER)}"
    )
    return Finding(ERROR, "E_HEADER", message, (1,))


def _column_count_finding(count: int, line: int) -> Finding:
    message = (
        f"Řádek má {count} sloupců, očekává se {len(EXPECTED_HEADER)}. Řádek byl vynechán. "
        "Zkontrolujte čárky v textu (text s čárkou dejte do uvozovek) a chybějící sloupce."
    )
    return Finding(ERROR, "E_COLUMN_COUNT", message, (line,))
