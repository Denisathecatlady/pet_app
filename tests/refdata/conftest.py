"""Společné fixtury testů balíčku ``refdata``.

Všechna čísla v testech jsou SYNTETICKÁ (standard ``TESTSTD``), nejde o
hodnoty FEDIAF, NRC ani AAFCO. Jedinou výjimkou je zdokumentovaný příklad
Ca 1.25 g / 1000 kcal ME ↔ 0.50 g / 100 g sušiny (docs/03 §3.3), který
ilustruje převodní faktor 2.5.
"""

import csv
import io
import itertools
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from refdata.catalog import NutrientDef, load_catalog
from refdata.standard_rows import EXPECTED_HEADER, StandardRow, parse_row

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "data" / "reference" / "nutrients.csv"
TEMPLATE_PATH = REPO_ROOT / "data" / "reference" / "standard_import_template.csv"

# Úplný a platný řádek se syntetickou hodnotou (pes, dospělý, 110 kcal/kg^0.75).
VALID_CELLS: Mapping[str, str] = {
    "standard_code": "TESTSTD",
    "edition": "1",
    "species": "DOG",
    "life_stage": "ADULT_MAINTENANCE",
    "reference_energy_k": "110",
    "reference_energy_exponent": "0.75",
    "basis": "PER_1000KCAL_ME",
    "nutrient_code": "ZN",
    "requirement_type": "MIN_RECOMMENDED",
    "value": "10.0",
    "unit": "mg",
    "condition_note": "",
    "source_table": "T-1",
    "source_page": "1",
    "transcriber": "AA",
    "transcribed_at": "2026-01-31",
    "note": "",
}

# Platný řádek pro kočku (dospělá, 100 kcal/kg^0.67).
CAT_CELLS: Mapping[str, str] = {
    "species": "CAT",
    "reference_energy_k": "100",
    "reference_energy_exponent": "0.67",
}


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Kořen repozitáře."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def catalog_path() -> Path:
    """Skutečný katalog živin ``data/reference/nutrients.csv``."""
    return CATALOG_PATH


@pytest.fixture(scope="session")
def template_path() -> Path:
    """Šablona importu ``data/reference/standard_import_template.csv``."""
    return TEMPLATE_PATH


@pytest.fixture(scope="session")
def catalog() -> dict[str, NutrientDef]:
    """Skutečný katalog živin z repozitáře."""
    return load_catalog(CATALOG_PATH)


@pytest.fixture
def cat_cells() -> dict[str, str]:
    """Pole, která z platného psího řádku udělají platný kočičí řádek."""
    return dict(CAT_CELLS)


@pytest.fixture
def make_row() -> Callable[..., StandardRow]:
    """Továrna na řádky: platný syntetický řádek s přepsanými poli.

    Řádky dostávají vzestupná čísla řádků od 2, pokud se nezadá ``line``.
    """
    counter = itertools.count(2)

    def factory(line: int | None = None, **overrides: str) -> StandardRow:
        cells = {**VALID_CELLS, **overrides}
        return parse_row(cells, line if line is not None else next(counter))

    return factory


def _csv_text(rows: Sequence[Mapping[str, str]], header: Sequence[str] = EXPECTED_HEADER) -> str:
    """Vrátí CSV text s hlavičkou a řádky (chybějící pole = platný řádek)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        cells = {**VALID_CELLS, **row}
        writer.writerow([cells.get(column, "") for column in header])
    return buffer.getvalue()


@pytest.fixture
def write_csv(tmp_path: Path) -> Callable[..., Path]:
    """Továrna, která zapíše přepis do dočasného souboru a vrátí cestu."""

    def factory(
        rows: Sequence[Mapping[str, str]],
        name: str = "prepis.csv",
        header: Sequence[str] = EXPECTED_HEADER,
        bom: bool = False,
    ) -> Path:
        path = tmp_path / name
        prefix = "\ufeff" if bom else ""
        path.write_text(prefix + _csv_text(rows, header), encoding="utf-8", newline="")
        return path

    return factory
