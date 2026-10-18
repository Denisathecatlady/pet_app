"""Kontroly přepisu tabulek standardu: řádkové kontroly a kontroly mezi řádky.

Řádkové kontroly ověří slovníky, čísla, jednotky a původ hodnoty. Kontroly
mezi řádky (minimum < maximum, převody mezi bázemi, dvojice sloupců 95/110
a 75/100) běží jen nad řádky, které prošly řádkovými kontrolami bez chyby,
mají vyplněnou hodnotu, nemají duplicitní klíč a sdílejí jednotku. Tolerance
převodů se odvozuje z vytištěné přesnosti (:mod:`refdata.decimal_utils`).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import StrEnum

from refdata.catalog import NutrientDef
from refdata.decimal_utils import DECIMAL_CONTEXT, consistent_with_factor
from refdata.findings import ERROR, INFO, WARNING, Finding, Severity, sorted_findings
from refdata.standard_rows import (
    Key,
    StandardRow,
    describe_key,
    find_duplicate_keys,
    row_parse_findings,
)
from refdata.vocab import (
    ADULT_STAGES,
    BASIS_LABELS,
    BASIS_ONLY_FOR_SPECIES,
    CONFIRM_TOKEN,
    DM_TO_1000KCAL_FACTOR,
    ENERGY_NUTRIENT,
    IU_ALLOWED_NUTRIENTS,
    LIFE_STAGES,
    MAXIMUM_TYPES,
    METABOLIC_EXPONENT,
    MINIMUM_TYPES,
    MJ_TO_1000KCAL_FACTOR,
    RATIO_TYPES,
    SCALED_PAIRS,
    Basis,
    LifeStage,
    RequirementType,
    Species,
    Unit,
)

PROVENANCE_FIELDS = ("source_table", "source_page", "transcriber")

_MIN_MAX_GROUP = (
    "standard_code",
    "edition",
    "species",
    "life_stage",
    "reference_energy_k",
    "basis",
    "nutrient_code",
    "condition_note",
    "unit",
)
_BASIS_GROUP = (
    "standard_code",
    "edition",
    "species",
    "life_stage",
    "reference_energy_k",
    "nutrient_code",
    "requirement_type",
    "condition_note",
    "unit",
)
_SCALED_GROUP = (
    "standard_code",
    "edition",
    "species",
    "basis",
    "nutrient_code",
    "requirement_type",
    "condition_note",
    "unit",
)
_SCALED_BASES = frozenset({Basis.PER_100G_DM, Basis.PER_1000KCAL_ME, Basis.PER_MJ_ME})


@dataclass(frozen=True)
class _BasisCheck:
    """Očekávaný vztah ``hodnota(target) = hodnota(source) × factor / divisor``."""

    code: str
    target: Basis
    source: Basis
    factor: Decimal
    divisor: Decimal
    rule: str


_BASIS_CHECKS = (
    _BasisCheck(
        "E_BASIS_DM_1000",
        Basis.PER_1000KCAL_ME,
        Basis.PER_100G_DM,
        DM_TO_1000KCAL_FACTOR,
        Decimal(1),
        "na 1000 kcal ME = na 100 g sušiny × 2.5",
    ),
    _BasisCheck(
        "E_BASIS_MJ_1000",
        Basis.PER_1000KCAL_ME,
        Basis.PER_MJ_ME,
        MJ_TO_1000KCAL_FACTOR,
        Decimal(1),
        "na 1000 kcal ME = na MJ ME × 4.184",
    ),
    _BasisCheck(
        "E_BASIS_DM_MJ",
        Basis.PER_MJ_ME,
        Basis.PER_100G_DM,
        DM_TO_1000KCAL_FACTOR,
        MJ_TO_1000KCAL_FACTOR,
        "na MJ ME = na 100 g sušiny × 2.5 / 4.184",
    ),
)


def validate_rows(
    rows: Sequence[StandardRow],
    catalog: Mapping[str, NutrientDef],
    allow_empty: bool = False,
) -> list[Finding]:
    """Zkontroluje řádky přepisu jednoho souboru.

    Vstup: řádky (z :func:`refdata.standard_rows.load_standard_csv` nebo
    :func:`refdata.standard_rows.parse_row`), katalog živin a příznak
    ``allow_empty`` pro rozpracovaný přepis (řádek bez hodnoty je jen
    ``I_NOT_FILLED`` a jeho prázdný původ ani datum nejsou chybou; řádek
    s hodnotou musí mít úplný původ vždy).

    Kontroly mezi řádky: ``E_MIN_NOT_BELOW_MAX``; převody bází
    ``E_BASIS_DM_1000``, ``E_BASIS_MJ_1000``, ``E_BASIS_DM_MJ`` (``ERROR``,
    nebo ``WARNING``, když poznámky obou řádků obsahují
    :data:`~refdata.vocab.CONFIRM_TOKEN`; u typů RATIO_MIN/RATIO_MAX se
    nepoužijí, protože poměr na bázi nezávisí); ``W_SCALED_PAIR`` jen pro
    požadavky typu minimum.

    Výstup: nálezy seřazené podle prvního řádku a kódu (nezávisle na pořadí
    vstupních řádků). Výjimky nevyhazuje.
    """
    duplicates = find_duplicate_keys(rows)
    findings: list[Finding] = []
    clean_rows: list[StandardRow] = []
    for row in rows:
        row_findings = _row_findings(row, catalog, allow_empty)
        findings.extend(row_findings)
        if (
            row.value_decimal is not None
            and row.key not in duplicates
            and not any(finding.severity == ERROR for finding in row_findings)
        ):
            clean_rows.append(row)
    findings.extend(_duplicate_findings(duplicates))
    clean_rows.sort(key=lambda row: row.line)
    findings.extend(_min_max_findings(clean_rows))
    findings.extend(_basis_findings(clean_rows))
    findings.extend(_scaled_pair_findings(clean_rows))
    return sorted_findings(findings)


# --- řádkové kontroly -------------------------------------------------------


def _row_findings(
    row: StandardRow, catalog: Mapping[str, NutrientDef], allow_empty: bool
) -> list[Finding]:
    species = _member(Species, row.species)
    life_stage = _member(LifeStage, row.life_stage)
    requirement_type = _member(RequirementType, row.requirement_type)
    basis = _member(Basis, row.basis)
    unit = _member(Unit, row.unit)
    nutrient = catalog.get(row.nutrient_code)
    return [
        *_vocabulary_findings(row, species, life_stage, requirement_type, basis, unit, nutrient),
        *row_parse_findings(row),
        *_number_findings(row, species, life_stage, basis),
        *_nutrient_findings(row, nutrient, species, requirement_type, unit),
        *_value_and_provenance_findings(row, allow_empty),
    ]


def _vocabulary_findings(
    row: StandardRow,
    species: Species | None,
    life_stage: LifeStage | None,
    requirement_type: RequirementType | None,
    basis: Basis | None,
    unit: Unit | None,
    nutrient: NutrientDef | None,
) -> list[Finding]:
    findings = []
    if species is None:
        findings.append(
            _row_finding(
                row,
                "E_UNKNOWN_SPECIES",
                f"Neznámý druh „{row.species}“. Zapište DOG nebo CAT podle tabulky originálu.",
            )
        )
    allowed_stages = LIFE_STAGES[species] if species is not None else frozenset(LifeStage)
    if life_stage not in allowed_stages:
        scope = f" pro druh {species}" if species is not None else ""
        findings.append(
            _row_finding(
                row,
                "E_UNKNOWN_LIFE_STAGE",
                f"Životní fáze „{row.life_stage}“ neplatí{scope}. Použijte jednu z: "
                f"{_listing(allowed_stages)} (docs/03 §3.1).",
            )
        )
    if requirement_type is None:
        findings.append(
            _row_finding(
                row,
                "E_UNKNOWN_REQ_TYPE",
                f"Neznámý typ požadavku „{row.requirement_type}“. Použijte jeden z: "
                f"{_listing(RequirementType)}.",
            )
        )
    if basis is None:
        findings.append(
            _row_finding(
                row,
                "E_UNKNOWN_BASIS",
                f"Neznámá báze „{row.basis}“. Použijte jednu z: {_listing(Basis)} "
                "podle hlavičky tabulky originálu.",
            )
        )
    if unit is None:
        findings.append(
            _row_finding(
                row,
                "E_UNKNOWN_UNIT",
                f"Neznámá jednotka „{row.unit}“. Použijte jednu z: {_listing(Unit)} "
                "(µg pište jako ug, poměr jako ratio).",
            )
        )
    if nutrient is None:
        findings.append(
            _row_finding(
                row,
                "E_UNKNOWN_NUTRIENT",
                f"Živina „{row.nutrient_code}“ není v katalogu živin. Použijte kód z "
                "data/reference/nutrients.csv; chybí-li živina v katalogu, obraťte se na "
                "kurátora dat.",
            )
        )
    return findings


def _number_findings(
    row: StandardRow,
    species: Species | None,
    life_stage: LifeStage | None,
    basis: Basis | None,
) -> list[Finding]:
    findings = []
    if row.value_decimal is not None and row.value_decimal <= 0:
        findings.append(
            _row_finding(
                row,
                "E_NONPOSITIVE_VALUE",
                f"Hodnota {row.value} musí být větší než 0. Ověřte buňku v originále; buňku "
                "bez hodnoty nepřepisujte jako 0, řádek pro ni nevytvářejte.",
            )
        )
    if species is not None:
        expected = METABOLIC_EXPONENT[species]
        if not row.reference_energy_exponent:
            findings.append(
                _row_finding(
                    row,
                    "E_SPECIES_EXPONENT",
                    f"Chybí exponent metabolické hmotnosti. Pro druh {species} zapište {expected}.",
                )
            )
        elif row.exponent_decimal is not None and row.exponent_decimal != expected:
            findings.append(
                _row_finding(
                    row,
                    "E_SPECIES_EXPONENT",
                    f"Exponent {row.reference_energy_exponent} neodpovídá druhu {species} "
                    f"(očekává se {expected}). Opravte druh nebo exponent.",
                )
            )
        required_species = BASIS_ONLY_FOR_SPECIES.get(basis) if basis is not None else None
        if required_species is not None and required_species != species:
            findings.append(
                _row_finding(
                    row,
                    "E_BASIS_SPECIES",
                    f"Báze {basis} platí jen pro druh {required_species}, řádek je pro "
                    f"{species}. Opravte bázi nebo druh podle originálu.",
                )
            )
    if life_stage in ADULT_STAGES and not row.reference_energy_k:
        findings.append(
            _row_finding(
                row,
                "E_MISSING_REF_ENERGY",
                f"Dospělá fáze {life_stage} vyžaduje referenční energii reference_energy_k "
                "(kcal ME/kg metabolické hmotnosti). Doplňte ji z hlavičky tabulky originálu.",
            )
        )
    return findings


def _nutrient_findings(
    row: StandardRow,
    nutrient: NutrientDef | None,
    species: Species | None,
    requirement_type: RequirementType | None,
    unit: Unit | None,
) -> list[Finding]:
    findings = []
    if unit == Unit.KCAL and row.nutrient_code != ENERGY_NUTRIENT:
        findings.append(
            _row_finding(
                row,
                "E_KCAL_UNIT",
                f"Jednotka kcal je povolena jen u {ENERGY_NUTRIENT}. Opravte jednotku podle "
                "originálu.",
            )
        )
    if nutrient is None:
        return findings
    if species is not None and not nutrient.is_relevant_for(species):
        findings.append(
            _row_finding(
                row,
                "W_SPECIES_NOT_RELEVANT",
                f"Katalog uvádí, že živina {nutrient.code} se u druhu {species} nesleduje. "
                "Ověřte v originále druh a živinu; pokud řádek sedí, upozorněte kurátora "
                "katalogu.",
                WARNING,
            )
        )
    unit_conflicts_ratio = unit is not None and (unit == Unit.RATIO) != nutrient.is_ratio
    type_conflicts_ratio = (
        requirement_type is not None and (requirement_type in RATIO_TYPES) != nutrient.is_ratio
    )
    if unit_conflicts_ratio or type_conflicts_ratio:
        findings.append(_ratio_type_finding(row, nutrient))
    if unit is None or unit_conflicts_ratio or unit == Unit.KCAL or unit == nutrient.canonical_unit:
        return findings
    if unit == Unit.IU and nutrient.code in IU_ALLOWED_NUTRIENTS:
        findings.append(
            _row_finding(
                row,
                "W_NEEDS_CONVERSION",
                f"Hodnota je v IU, kanonická jednotka {nutrient.code} je "
                f"{nutrient.canonical_unit}. Ponechte IU tak, jak je vytištěno, a nic "
                "nepřepočítávejte: převod se převezme z přílohy standardu jako samostatný "
                "ověřený záznam.",
                WARNING,
            )
        )
    else:
        iu_hint = " Jednotka IU je povolena jen u VIT_A, VIT_D a VIT_E." if unit == Unit.IU else ""
        findings.append(
            _row_finding(
                row,
                "E_UNIT_NOT_CANONICAL",
                f"Jednotka {unit} se liší od kanonické jednotky {nutrient.canonical_unit} "
                f"živiny {nutrient.code}.{iu_hint} Ověřte jednotku v originále. Hodnotu sami "
                "nepřepočítávejte; pokud originál opravdu používá jinou jednotku, uveďte to "
                "v poznámce a předejte řádek kurátorovi dat.",
            )
        )
    return findings


def _ratio_type_finding(row: StandardRow, nutrient: NutrientDef) -> Finding:
    if nutrient.is_ratio:
        message = (
            f"Živina {nutrient.code} je poměr: použijte typ RATIO_MIN nebo RATIO_MAX a "
            "jednotku ratio (poměr a:1 zapište jako a)."
        )
    else:
        message = (
            f"Živina {nutrient.code} není poměr: typy RATIO_MIN/RATIO_MAX a jednotku ratio "
            "použijte jen u poměrových živin z katalogu. Opravte typ požadavku nebo jednotku."
        )
    return _row_finding(row, "E_RATIO_TYPE", message)


def _value_and_provenance_findings(row: StandardRow, allow_empty: bool) -> list[Finding]:
    findings = []
    if not row.value:
        if allow_empty:
            return [
                _row_finding(
                    row,
                    "I_NOT_FILLED",
                    "Řádek zatím není vyplněn. Před odevzdáním doplňte hodnotu a údaje o "
                    "původu, nebo řádek smažte, pokud tabulka hodnotu neuvádí.",
                    INFO,
                )
            ]
        findings.append(
            _row_finding(
                row,
                "E_EMPTY_VALUE",
                "Chybí hodnota (value). Doplňte číslo přesně podle originálu, nebo řádek "
                "smažte, pokud tabulka hodnotu neuvádí. Během rozpracovaného přepisu "
                "spouštějte kontrolu s --allow-empty.",
            )
        )
    missing = [field for field in PROVENANCE_FIELDS if not getattr(row, field)]
    if missing:
        findings.append(
            _row_finding(
                row,
                "E_MISSING_PROVENANCE",
                f"Chybí povinné údaje o původu: {', '.join(missing)}. Doplňte tabulku a "
                "stranu originálního PDF a své iniciály.",
            )
        )
    if not row.transcribed_at:
        findings.append(
            _row_finding(
                row,
                "E_BAD_DATE",
                "Chybí datum přepisu (transcribed_at). Doplňte je ve tvaru RRRR-MM-DD.",
            )
        )
    return findings


def _duplicate_findings(duplicates: Mapping[Key, tuple[int, ...]]) -> list[Finding]:
    return [
        Finding(
            ERROR,
            "E_DUPLICATE_KEY",
            f"Stejný klíč ({describe_key(key)}) je na řádcích {_lines_text(lines)}. Každá "
            "buňka tabulky smí být v souboru jen jednou: smažte duplicitu, nebo řádky "
            "rozlište ve sloupci condition_note podle poznámky v originále.",
            lines,
            key,
        )
        for key, lines in duplicates.items()
    ]


# --- kontroly mezi řádky ----------------------------------------------------


def _min_max_findings(rows: Sequence[StandardRow]) -> list[Finding]:
    findings = []
    for key, group in _grouped(rows, _MIN_MAX_GROUP):
        by_type: defaultdict[str, list[StandardRow]] = defaultdict(list)
        for row in group:
            by_type[row.requirement_type].append(row)
        minima = [row for row in group if row.requirement_type in MINIMUM_TYPES]
        maxima = [row for row in group if row.requirement_type in MAXIMUM_TYPES]
        pairs = [
            *((low, high, "menší než") for low in minima for high in maxima if not _lt(low, high)),
            *(
                (low, high, "nejvýše rovno")
                for low in by_type[RequirementType.NUTRITIONAL_MAX]
                for high in by_type[RequirementType.LEGAL_MAX_EU]
                if not _le(low, high)
            ),
            *(
                (low, high, "menší než")
                for low in by_type[RequirementType.RATIO_MIN]
                for high in by_type[RequirementType.RATIO_MAX]
                if not _lt(low, high)
            ),
        ]
        for low, high, relation in pairs:
            findings.append(
                Finding(
                    ERROR,
                    "E_MIN_NOT_BELOW_MAX",
                    f"{low.requirement_type} {low.value} {low.unit} (ř. {low.line}) musí být "
                    f"{relation} {high.requirement_type} {high.value} {high.unit} "
                    f"(ř. {high.line}) pro {low.nutrient_code} {BASIS_LABELS[Basis(low.basis)]}. "
                    "Ověřte obě buňky v originále (záměna řádku, sloupce nebo typu požadavku).",
                    _pair_lines(low, high),
                    key,
                )
            )
    return findings


def _basis_findings(rows: Sequence[StandardRow]) -> list[Finding]:
    findings = []
    convertible = [row for row in rows if row.requirement_type not in RATIO_TYPES]
    for key, group in _grouped(convertible, _BASIS_GROUP):
        for check in _BASIS_CHECKS:
            targets = [row for row in group if row.basis == check.target]
            sources = [row for row in group if row.basis == check.source]
            for target in targets:
                for source in sources:
                    if consistent_with_factor(
                        _value(target), _value(source), check.factor, check.divisor
                    ):
                        continue
                    findings.append(_basis_finding(check, target, source, key))
    return findings


def _basis_finding(
    check: _BasisCheck, target: StandardRow, source: StandardRow, key: Key
) -> Finding:
    expected = _expected_text(source, check.factor, check.divisor, target)
    message = (
        f"Hodnoty {target.nutrient_code} ({target.requirement_type}) na různých bázích si "
        f"neodpovídají: {target.value} {target.unit} {BASIS_LABELS[check.target]} "
        f"(ř. {target.line}) a {source.value} {source.unit} {BASIS_LABELS[check.source]} "
        f"(ř. {source.line}), podle pravidla {check.rule} se očekává ≈ {expected} "
        "(tolerance podle vytištěných desetinných míst). Ověřte obě buňky v originále."
    )
    confirmed = all(CONFIRM_TOKEN in row.note for row in (target, source))
    severity: Severity = WARNING if confirmed else ERROR
    if confirmed:
        message += f" Oba řádky nesou {CONFIRM_TOKEN}: neshodu posoudí specialista při revizi."
    else:
        message += (
            f" Jsou-li hodnoty v originále vytištěny přesně takto, připište do poznámky "
            f"(note) obou řádků {CONFIRM_TOKEN}."
        )
    return Finding(severity, check.code, message, _pair_lines(target, source), key)


def _scaled_pair_findings(rows: Sequence[StandardRow]) -> list[Finding]:
    findings = []
    candidates = [
        row for row in rows if row.requirement_type in MINIMUM_TYPES and row.basis in _SCALED_BASES
    ]
    for key, group in _grouped(candidates, _SCALED_GROUP):
        k_low, k_high = SCALED_PAIRS[Species(group[0].species)]
        lows = [row for row in group if row.k_decimal == k_low]
        highs = [row for row in group if row.k_decimal == k_high]
        for low in lows:
            for high in highs:
                if consistent_with_factor(_value(low), _value(high), k_high, k_low):
                    continue
                expected = _expected_text(high, k_high, k_low, low)
                findings.append(
                    Finding(
                        WARNING,
                        "W_SCALED_PAIR",
                        f"{low.nutrient_code} ({low.requirement_type}, "
                        f"{BASIS_LABELS[Basis(low.basis)]}): hodnota pro k={_fmt(k_low)} "
                        f"{low.value} (ř. {low.line}) neodpovídá přepočtu hodnoty pro "
                        f"k={_fmt(k_high)} {high.value} (ř. {high.line}) × "
                        f"{_fmt(k_high)}/{_fmt(k_low)} ≈ {expected}. FEDIAF nemusí všechny "
                        "řádky odvozovat přepočtem: ověřte obě buňky ručně v originále a "
                        "výsledek kontroly zapište do poznámky.",
                        _pair_lines(low, high),
                        key,
                    )
                )
    return findings


# --- pomocné funkce ---------------------------------------------------------


def _member[E: StrEnum](enum_type: type[E], text: str) -> E | None:
    try:
        return enum_type(text)
    except ValueError:
        return None


def _row_finding(row: StandardRow, code: str, message: str, severity: Severity = ERROR) -> Finding:
    return Finding(severity, code, message, (row.line,), row.key)


def _grouped(
    rows: Iterable[StandardRow], fields: tuple[str, ...]
) -> list[tuple[Key, list[StandardRow]]]:
    groups: defaultdict[Key, list[StandardRow]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.normalized(field) for field in fields)].append(row)
    return sorted(groups.items())


def _lt(low: StandardRow, high: StandardRow) -> bool:
    return _value(low) < _value(high)


def _le(low: StandardRow, high: StandardRow) -> bool:
    return _value(low) <= _value(high)


def _value(row: StandardRow) -> Decimal:
    if row.value_decimal is None:
        raise ValueError(f"Řádek {row.line} nemá platnou hodnotu.")
    return row.value_decimal


def _pair_lines(first: StandardRow, second: StandardRow) -> tuple[int, ...]:
    return tuple(sorted((first.line, second.line)))


def _expected_text(
    source: StandardRow, factor: Decimal, divisor: Decimal, like: StandardRow
) -> str:
    """Hodnota ``source × factor / divisor`` na o jedno místo víc, než má ``like``."""
    exponent = _value(like).as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError(f"Řádek {like.line} nemá konečnou hodnotu.")
    with localcontext(DECIMAL_CONTEXT):
        expected = _value(source) * factor / divisor
        return _fmt(expected.quantize(Decimal((0, (1,), exponent - 1))))


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _listing(values: Iterable[str]) -> str:
    return ", ".join(sorted(values))


def _lines_text(lines: Iterable[int]) -> str:
    return ", ".join(str(line) for line in lines)
