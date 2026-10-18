"""Načtení katalogu živin ``data/reference/nutrients.csv``."""

import csv
import io
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Final

from refdata.vocab import CANONICAL_UNITS, RATIO_CATEGORY, Species, Unit

CATALOG_HEADER: Final = (
    "code",
    "name_cs",
    "name_en",
    "category",
    "canonical_unit",
    "relevant_dog",
    "relevant_cat",
    "priority_barf",
    "note",
)
"""Přesná hlavička katalogu živin."""

RELEVANCE_VALUES: Final = frozenset({"yes", "no", "growth", "info", "conditional"})
"""Povolené hodnoty sloupců ``relevant_dog`` a ``relevant_cat``."""

NOT_RELEVANT: Final = "no"


class CatalogError(ValueError):
    """Katalog živin nelze použít (chybná hlavička, duplicitní kód, …)."""


@dataclass(frozen=True)
class NutrientDef:
    """Jedna položka katalogu živin."""

    code: str
    name_cs: str
    category: str
    canonical_unit: str
    relevant_dog: str
    relevant_cat: str
    priority: str

    @property
    def is_ratio(self) -> bool:
        """``True`` pro poměrové živiny (kategorie ``RATIO``)."""
        return self.category == RATIO_CATEGORY

    def is_relevant_for(self, species: Species) -> bool:
        """Vrátí ``False``, pokud katalog pro daný druh uvádí ``no``."""
        relevance = self.relevant_dog if species == Species.DOG else self.relevant_cat
        return relevance != NOT_RELEVANT


def load_catalog(path: str | PathLike[str]) -> dict[str, NutrientDef]:
    """Načte a zkontroluje katalog živin.

    Vstup: cesta k CSV v UTF-8 (BOM povolen) s hlavičkou :data:`CATALOG_HEADER`.

    Výstup: slovník ``kód → NutrientDef`` v pořadí souboru.

    Chyby: :class:`CatalogError` s českou zprávou, pokud soubor není v UTF-8,
    hlavička nesouhlasí, řádek má jiný počet sloupců, kód chybí nebo se
    opakuje, kanonická jednotka není z ``g, mg, ug, kcal, ratio``, hodnota
    relevance není povolená, nebo kategorie ``RATIO`` nesouhlasí s jednotkou
    ``ratio``. ``OSError`` při nedostupném souboru.
    """
    try:
        text = Path(path).read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogError(f"Katalog {path} není v kódování UTF-8. Uložte jej jako UTF-8.") from exc
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        records = list(reader)
    except csv.Error as exc:
        raise CatalogError(f"Katalog {path} není platné CSV ({exc}). Opravte uvozovky.") from exc
    if not records or tuple(records[0]) != CATALOG_HEADER:
        raise CatalogError(f"Katalog {path} nemá očekávanou hlavičku: {','.join(CATALOG_HEADER)}.")
    catalog: dict[str, NutrientDef] = {}
    for line, cells in enumerate(records[1:], start=2):
        if not cells:
            continue
        catalog_entry = _parse_entry(cells, line, path)
        if catalog_entry.code in catalog:
            raise CatalogError(f"Katalog {path}, ř. {line}: kód {catalog_entry.code} se opakuje.")
        catalog[catalog_entry.code] = catalog_entry
    return catalog


def _parse_entry(cells: list[str], line: int, path: str | PathLike[str]) -> NutrientDef:
    where = f"Katalog {path}, ř. {line}"
    if len(cells) != len(CATALOG_HEADER):
        raise CatalogError(
            f"{where}: řádek má {len(cells)} sloupců, očekává se {len(CATALOG_HEADER)}."
        )
    row = dict(zip(CATALOG_HEADER, (cell.strip() for cell in cells), strict=True))
    if not row["code"]:
        raise CatalogError(f"{where}: chybí kód živiny.")
    if row["canonical_unit"] not in CANONICAL_UNITS:
        raise CatalogError(
            f"{where}: kanonická jednotka „{row['canonical_unit']}“ není povolená "
            f"({', '.join(sorted(CANONICAL_UNITS))})."
        )
    for column in ("relevant_dog", "relevant_cat"):
        if row[column] not in RELEVANCE_VALUES:
            raise CatalogError(
                f"{where}: hodnota {column} „{row[column]}“ není povolená "
                f"({', '.join(sorted(RELEVANCE_VALUES))})."
            )
    if (row["category"] == RATIO_CATEGORY) != (row["canonical_unit"] == Unit.RATIO):
        raise CatalogError(f"{where}: kategorie RATIO a jednotka ratio musí být použity společně.")
    return NutrientDef(
        code=row["code"],
        name_cs=row["name_cs"],
        category=row["category"],
        canonical_unit=row["canonical_unit"],
        relevant_dog=row["relevant_dog"],
        relevant_cat=row["relevant_cat"],
        priority=row["priority_barf"],
    )
