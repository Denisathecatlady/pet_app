"""Načtení katalogu živin."""

from codecs import BOM_UTF8
from pathlib import Path

import pytest

from refdata.catalog import CATALOG_HEADER, CatalogError, load_catalog
from refdata.vocab import CANONICAL_UNITS, Species

HEADER = ",".join(CATALOG_HEADER)
ROW_ZN = "ZN,Zinek,Zinc,TRACE,mg,yes,yes,A,"
ROW_RATIO = "CA_P,Poměr Ca:P,Ca:P ratio,RATIO,ratio,yes,yes,A,"


def _write(tmp_path: Path, *lines: str, prefix: bytes = b"") -> Path:
    path = tmp_path / "nutrients.csv"
    path.write_bytes(prefix + ("\n".join(lines) + "\n").encode("utf-8"))
    return path


def test_real_catalog_has_52_unique_codes(catalog_path: Path) -> None:
    catalog = load_catalog(catalog_path)
    assert len(catalog) == 52
    assert len(set(catalog)) == 52
    assert all(entry.canonical_unit in CANONICAL_UNITS for entry in catalog.values())
    assert [code for code, entry in catalog.items() if entry.is_ratio] == ["CA_P"]
    assert catalog["CA"].canonical_unit == "g"
    assert not catalog["ARA"].is_relevant_for(Species.DOG)
    assert catalog["ARA"].is_relevant_for(Species.CAT)
    assert catalog["TAURINE"].is_relevant_for(Species.DOG)  # „info“ není „no“


def test_small_catalog_and_bom(tmp_path: Path) -> None:
    catalog = load_catalog(_write(tmp_path, HEADER, ROW_ZN, "", ROW_RATIO, prefix=BOM_UTF8))
    assert list(catalog) == ["ZN", "CA_P"]
    assert catalog["ZN"].name_cs == "Zinek"
    assert catalog["ZN"].priority == "A"


@pytest.mark.parametrize(
    "lines",
    [
        pytest.param((), id="prazdny-soubor"),
        pytest.param(("code,name_cs", ROW_ZN), id="hlavicka"),
        pytest.param((HEADER, ROW_ZN, ROW_ZN), id="duplicitni-kod"),
        pytest.param((HEADER, "ZN,Zinek,Zinc,TRACE,IU,yes,yes,A,"), id="jednotka"),
        pytest.param((HEADER, "ZN,Zinek,Zinc,TRACE,mg,maybe,yes,A,"), id="relevance"),
        pytest.param((HEADER, "ZN,Zinek,Zinc,TRACE,ratio,yes,yes,A,"), id="ratio-bez-kategorie"),
        pytest.param((HEADER, "CA_P,Poměr,Ratio,RATIO,g,yes,yes,A,"), id="kategorie-bez-ratio"),
        pytest.param((HEADER, "ZN,Zinek,Zinc,TRACE,mg,yes,yes"), id="pocet-sloupcu"),
        pytest.param((HEADER, ",Bez kódu,No code,TRACE,mg,yes,yes,A,"), id="chybi-kod"),
        pytest.param((HEADER, 'ZN,"Zinek,Zinc,TRACE,mg,yes,yes,A,'), id="uvozovky"),
    ],
)
def test_invalid_catalog_raises(tmp_path: Path, lines: tuple[str, ...]) -> None:
    path = tmp_path / "nutrients.csv"
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(path)


def test_non_utf8_catalog_raises(tmp_path: Path) -> None:
    path = tmp_path / "nutrients.csv"
    path.write_bytes(f"{HEADER}\nZN,Žinek,Zinc,TRACE,mg,yes,yes,A,\n".encode("cp1250"))
    with pytest.raises(CatalogError, match="UTF-8"):
        load_catalog(path)


def test_missing_catalog_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_catalog(tmp_path / "neexistuje.csv")
