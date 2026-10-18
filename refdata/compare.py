"""Porovnání dvou nezávislých přepisů téže tabulky (dvojí přepis).

Řádky se párují podle klíče (:attr:`refdata.standard_rows.StandardRow.key`).
U nálezů, které se týkají obou souborů, je ``lines = (řádek v A, řádek v B)``
a zpráva vždy uvádí, ke kterému souboru se které číslo řádku vztahuje.
"""

from collections.abc import Sequence

from refdata.findings import ERROR, WARNING, Finding, Severity, sorted_findings
from refdata.standard_rows import Key, StandardRow, describe_key, find_duplicate_keys

LABEL_A = "A"
LABEL_B = "B"


def compare_transcriptions(
    rows_a: Sequence[StandardRow], rows_b: Sequence[StandardRow]
) -> list[Finding]:
    """Porovná přepis A s přepisem B.

    Vstup: řádky souboru A a souboru B (každý soubor zvlášť načtený).

    Výstup: seřazené nálezy:
    ``E_ONLY_IN_A`` / ``E_ONLY_IN_B`` (klíč jen v jednom souboru),
    ``E_VALUE_MISMATCH`` (číselně různé hodnoty; prázdná hodnota proti
    vyplněné je také neshoda), ``W_PRECISION_DIFFERS`` (číselně shodné, ale
    jiný počet vytištěných desetinných míst), ``E_UNIT_MISMATCH``,
    ``W_PROVENANCE_DIFFERS`` (jiná tabulka nebo strana),
    ``E_SAME_TRANSCRIBER`` (oba soubory uvádějí stejné iniciály; dvojí přepis
    musí být nezávislý) a ``E_DUPLICATE_KEY`` (klíč se opakuje v jednom
    souboru; porovná se jeho první výskyt). Výjimky nevyhazuje.
    """
    findings = [
        *_duplicate_findings(rows_a, LABEL_A),
        *_duplicate_findings(rows_b, LABEL_B),
    ]
    index_a = _first_by_key(rows_a)
    index_b = _first_by_key(rows_b)
    for key in sorted(index_a.keys() - index_b.keys()):
        findings.append(_only_in(index_a[key], LABEL_A, LABEL_B, "E_ONLY_IN_A"))
    for key in sorted(index_b.keys() - index_a.keys()):
        findings.append(_only_in(index_b[key], LABEL_B, LABEL_A, "E_ONLY_IN_B"))
    for key in sorted(index_a.keys() & index_b.keys()):
        findings.extend(_pair_findings(index_a[key], index_b[key]))
    return sorted_findings(findings)


def _first_by_key(rows: Sequence[StandardRow]) -> dict[Key, StandardRow]:
    index: dict[Key, StandardRow] = {}
    for row in sorted(rows, key=lambda row: row.line):
        index.setdefault(row.key, row)
    return index


def _duplicate_findings(rows: Sequence[StandardRow], label: str) -> list[Finding]:
    return [
        Finding(
            ERROR,
            "E_DUPLICATE_KEY",
            f"Soubor {label}: klíč ({describe_key(key)}) je na řádcích "
            f"{', '.join(str(line) for line in lines)}. Porovnává se jen první výskyt; "
            f"duplicitu v souboru {label} odstraňte.",
            lines,
            key,
        )
        for key, lines in find_duplicate_keys(rows).items()
    ]


def _only_in(row: StandardRow, present: str, missing: str, code: str) -> Finding:
    message = (
        f"Řádek {row.line} souboru {present} ({describe_key(row.key)}) nemá v souboru "
        f"{missing} protějšek se stejným klíčem. Dohledejte buňku v originále: chybí-li "
        f"řádek v souboru {missing}, doplňte ho; jinak opravte klíčová pole (druh, fáze, k, "
        f"báze, živina, typ, podmínka) v chybném souboru."
    )
    return Finding(ERROR, code, message, (row.line,), row.key)


def _pair_findings(row_a: StandardRow, row_b: StandardRow) -> list[Finding]:
    where = f"soubor A ř. {row_a.line}, soubor B ř. {row_b.line}"
    findings = []

    def add(severity: Severity, code: str, message: str) -> None:
        findings.append(
            Finding(
                severity,
                code,
                f"{message} ({where}; {describe_key(row_a.key)})",
                (row_a.line, row_b.line),
                row_a.key,
            )
        )

    value_finding = _value_difference(row_a, row_b)
    if value_finding is not None:
        add(*value_finding)
    if row_a.unit != row_b.unit:
        add(
            ERROR,
            "E_UNIT_MISMATCH",
            f"Jednotky se liší: A „{row_a.unit}“, B „{row_b.unit}“. Ověřte jednotku v "
            "originále a opravte chybný soubor.",
        )
    if (row_a.source_table, row_a.source_page) != (row_b.source_table, row_b.source_page):
        add(
            WARNING,
            "W_PROVENANCE_DIFFERS",
            f"Původ se liší: A tabulka „{row_a.source_table}“ strana „{row_a.source_page}“, "
            f"B tabulka „{row_b.source_table}“ strana „{row_b.source_page}“. Ověřte, odkud "
            "hodnota v originále pochází, a sjednoťte údaje.",
        )
    transcriber = row_a.transcriber.casefold()
    if transcriber and transcriber == row_b.transcriber.casefold():
        add(
            ERROR,
            "E_SAME_TRANSCRIBER",
            f"Oba soubory uvádějí stejného přepisovatele „{row_a.transcriber}“. Dvojí přepis "
            "musí pořídit dvě různé osoby nezávisle na sobě; nechte řádek přepsat druhou "
            "osobou.",
        )
    return findings


def _value_difference(row_a: StandardRow, row_b: StandardRow) -> tuple[Severity, str, str] | None:
    value_a, value_b = row_a.value_decimal, row_b.value_decimal
    if value_a is not None and value_b is not None:
        if value_a != value_b:
            return (
                ERROR,
                "E_VALUE_MISMATCH",
                f"Hodnoty se liší: A {row_a.value}, B {row_b.value}. Dohledejte buňku v "
                "originále a opravte chybný soubor.",
            )
        if value_a.as_tuple().exponent != value_b.as_tuple().exponent:
            return (
                WARNING,
                "W_PRECISION_DIFFERS",
                f"Hodnoty jsou číselně stejné, ale liší se počet desetinných míst: A "
                f"„{row_a.value}“, B „{row_b.value}“. Přesnost určuje toleranci kontrol; "
                "zapište hodnotu se stejným počtem míst jako v originále.",
            )
        return None
    if row_a.value != row_b.value:
        return (
            ERROR,
            "E_VALUE_MISMATCH",
            f"Hodnoty se liší: A „{row_a.value}“, B „{row_b.value}“ (prázdná nebo neplatná "
            "hodnota se nerovná vyplněné). Dohledejte buňku v originále a opravte chybný "
            "soubor.",
        )
    return None
