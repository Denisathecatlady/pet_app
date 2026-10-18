"""Nálezy kontrol: jednotná struktura, řazení a souhrn podle závažnosti."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Severity = Literal["ERROR", "WARNING", "INFO"]

ERROR: Severity = "ERROR"
WARNING: Severity = "WARNING"
INFO: Severity = "INFO"
SEVERITIES: tuple[Severity, ...] = (ERROR, WARNING, INFO)


@dataclass(frozen=True)
class Finding:
    """Jeden nález kontroly.

    ``severity``: ``ERROR`` (brání předání dat), ``WARNING`` (nutné ručně
    ověřit), ``INFO`` (pro informaci).
    ``code``: stabilní kód nálezu (např. ``E_DUPLICATE_KEY``).
    ``message``: česká zpráva, která říká, co je špatně a co udělat.
    ``lines``: čísla řádků souboru (hlavička = řádek 1); u porovnání dvou
    souborů zpráva uvádí, ke kterému souboru se který řádek vztahuje.
    ``key``: klíč řádku nebo skupiny řádků, jinak ``None``.
    """

    severity: Severity
    code: str
    message: str
    lines: tuple[int, ...] = ()
    key: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"Neznámá závažnost nálezu: {self.severity!r}.")


def count_by_severity(findings: Iterable[Finding]) -> dict[str, int]:
    """Spočítá nálezy podle závažnosti.

    Vstup: nálezy. Výstup: slovník ``{"ERROR": n, "WARNING": n, "INFO": n}``
    (vždy se všemi třemi klíči).
    """
    counts: dict[str, int] = dict.fromkeys(SEVERITIES, 0)
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def has_errors(findings: Iterable[Finding]) -> bool:
    """Vrátí ``True``, pokud je mezi nálezy alespoň jeden ``ERROR``."""
    return any(finding.severity == ERROR for finding in findings)


def _sort_key(finding: Finding) -> tuple[int, str, tuple[int, ...], str, str, tuple[str, ...]]:
    first_line = finding.lines[0] if finding.lines else 0
    return (
        first_line,
        finding.code,
        finding.lines,
        finding.severity,
        finding.message,
        finding.key or (),
    )


def sorted_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Seřadí nálezy deterministicky: první řádek, kód, pak ostatní pole.

    Vstup: nálezy v libovolném pořadí. Výstup: nový seřazený seznam.
    """
    return sorted(findings, key=_sort_key)


def merge_findings(*groups: Iterable[Finding]) -> list[Finding]:
    """Spojí skupiny nálezů, odstraní přesné duplicity a seřadí je.

    Načtení souboru i kontrola řádků hlásí stejnou chybu parsování stejným
    nálezem; po spojení zůstane jen jeden.

    Vstup: libovolný počet skupin nálezů. Výstup: seřazený seznam bez duplicit.
    """
    unique = dict.fromkeys(finding for group in groups for finding in group)
    return sorted_findings(unique)
