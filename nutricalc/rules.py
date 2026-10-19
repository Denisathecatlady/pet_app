"""Deklarativní pravidla upozornění (docs/06 §6.7, docs/09 §9.2).

Pravidla jsou **data** (:class:`WarningRule`: podmínka, závažnost, text,
zdroj), která schvaluje specialista a předává volající. Jádro neobsahuje
žádné vestavěné pravidlo ani práh: zná jen typy podmínek
(:class:`Always`, :class:`IngredientFlagPresent`,
:class:`CategoryMassShareAbove`, :class:`NutrientStatusIn`) a umí je
deterministicky vyhodnotit (:func:`evaluate_rules`).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from nutricalc.composition import RecipeItem, validate_items
from nutricalc.decimal_ctx import calc_context, to_decimal
from nutricalc.errors import InvalidInputError, ValidationError
from nutricalc.evaluation import NutrientStatus
from nutricalc.flags import check_code
from nutricalc.vocab import WARNING_LEVEL_RANK, Species, WarningLevel, as_member, require_text

# --- podmínky -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Always:
    """Podmínka, která platí vždy (např. trvalé upozornění na syrovou stravu)."""

    kind: str = field(default="ALWAYS", init=False)


@dataclass(frozen=True)
class IngredientFlagPresent:
    """Platí, když má některá surovina dávky bezpečnostní příznak ``flag``.

    Příklad dat: ``THYROID_TISSUE`` nebo příznak toxicity pro druh.
    Chyby: ``TypeError``; :class:`~nutricalc.errors.ValidationError` pro prázdný text.
    """

    flag: str
    kind: str = field(default="INGREDIENT_FLAG_PRESENT", init=False)

    def __post_init__(self) -> None:
        require_text(self.flag, "Bezpečnostní příznak")


@dataclass(frozen=True)
class CategoryMassShareAbove:
    """Platí, když je podíl gramů surovin kategorie ``category`` **větší** než ``share``.

    ``share`` je podíl celkové hmotnosti dávky 0–1 (``Decimal``; práh je data).
    Chyby: ``TypeError`` pro ``float``; :class:`~nutricalc.errors.InvalidInputError`
    pro podíl mimo 0–1; :class:`~nutricalc.errors.ValidationError` pro prázdnou kategorii.
    """

    category: str
    share: Decimal
    kind: str = field(default="CATEGORY_MASS_SHARE_ABOVE", init=False)

    def __post_init__(self) -> None:
        require_text(self.category, "Kategorie suroviny")
        share = to_decimal(self.share, name="Podíl hmotnosti kategorie")
        if share > 1:
            raise InvalidInputError(f"Podíl hmotnosti musí být 0 až 1 (zadáno {share}).")
        object.__setattr__(self, "share", share)


@dataclass(frozen=True)
class NutrientStatusIn:
    """Platí, když má živina (nebo poměr) některý ze stavů ``statuses``.

    Porovnávají se všechny stavy živiny (``all_statuses``), nejen hlavní stav.
    Živina bez vyhodnocení (např. při blokaci) podmínku nesplní.
    Chyby: ``TypeError``; :class:`~nutricalc.errors.ValidationError` pro
    prázdný kód nebo prázdnou množinu stavů.
    """

    nutrient_code: str
    statuses: frozenset[NutrientStatus]
    kind: str = field(default="NUTRIENT_STATUS_IN", init=False)

    def __post_init__(self) -> None:
        require_text(self.nutrient_code, "Kód živiny podmínky")
        if isinstance(self.statuses, str) or not isinstance(self.statuses, Iterable):
            raise TypeError("statuses musí být kolekce NutrientStatus.")
        statuses = frozenset(
            as_member(NutrientStatus, status, "stav živiny") for status in self.statuses
        )
        if not statuses:
            raise ValidationError(f"Podmínka pro {self.nutrient_code} nemá žádný stav.")
        object.__setattr__(self, "statuses", statuses)


Condition = Always | IngredientFlagPresent | CategoryMassShareAbove | NutrientStatusIn
"""Podmínka pravidla."""

_CONDITION_TYPES = (Always, IngredientFlagPresent, CategoryMassShareAbove, NutrientStatusIn)


# --- pravidlo, kontext a upozornění ----------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class WarningRule:
    """Pravidlo upozornění (data, docs/06 §6.7).

    Pole (jen jako pojmenované argumenty):
        ``code`` – stabilní kód (velká písmena, číslice, _).
        ``level`` – :class:`~nutricalc.vocab.WarningLevel` (``BLOCKED`` a
        ``EXPERT_REQUIRED`` vstupují do bezpečnostní brány).
        ``message_cs`` – český text upozornění.
        ``source_key`` – klíč zdroje z ``docs/zdroje.md``.
        ``species`` – druhy, pro které pravidlo platí, nebo ``None`` = všechny.
        ``condition`` – podmínka (:data:`Condition`).

    Chyby: ``TypeError`` pro nesprávné typy;
    :class:`~nutricalc.errors.ValidationError` pro neplatný kód, prázdný text
    nebo prázdnou množinu druhů.
    """

    code: str
    level: WarningLevel
    message_cs: str
    source_key: str
    species: frozenset[Species] | None = None
    condition: Condition

    def __post_init__(self) -> None:
        check_code(self.code, "Kód pravidla")
        object.__setattr__(self, "level", as_member(WarningLevel, self.level, "úroveň pravidla"))
        require_text(self.message_cs, f"Text pravidla {self.code}")
        require_text(self.source_key, f"Zdroj pravidla {self.code}")
        if self.species is not None:
            if isinstance(self.species, str) or not isinstance(self.species, Iterable):
                raise TypeError("WarningRule.species musí být kolekce druhů nebo None.")
            species = frozenset(
                as_member(Species, value, "druh pravidla") for value in self.species
            )
            if not species:
                raise ValidationError(
                    f"Pravidlo {self.code}: prázdná množina druhů; pro všechny druhy použijte None."
                )
            object.__setattr__(self, "species", species)
        if not isinstance(self.condition, _CONDITION_TYPES):
            allowed = ", ".join(kind.__name__ for kind in _CONDITION_TYPES)
            raise TypeError(f"Pravidlo {self.code}: podmínka musí být jedna z {allowed}.")


@dataclass(frozen=True, kw_only=True)
class RuleContext:
    """Data, nad kterými se pravidla vyhodnocují.

    ``species`` – druh zvířete. ``items`` – položky receptu (seřadí se podle
    kódu suroviny). ``nutrient_statuses`` – kód živiny nebo poměru → všechny
    jeho stavy (prázdné mapování, když se požadavky nevyhodnocovaly).
    """

    species: Species
    items: tuple[RecipeItem, ...]
    nutrient_statuses: Mapping[str, frozenset[NutrientStatus]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "species", as_member(Species, self.species, "druh"))
        object.__setattr__(self, "items", validate_items(self.items))
        if not isinstance(self.nutrient_statuses, Mapping):
            raise TypeError("nutrient_statuses musí být mapování kód → stavy.")
        statuses = {
            require_text(code, "Kód živiny"): frozenset(
                as_member(NutrientStatus, status, "stav živiny") for status in values
            )
            for code, values in self.nutrient_statuses.items()
        }
        object.__setattr__(self, "nutrient_statuses", MappingProxyType(statuses))


@dataclass(frozen=True, kw_only=True)
class RuleWarning:
    """Upozornění vzniklé z pravidla.

    (Pojmenováno ``RuleWarning``, aby nezastínilo vestavěnou třídu ``Warning``.)

    ``level``, ``code``, ``message_cs``, ``source_key`` – z pravidla.
    ``ingredient_codes`` – suroviny, které podmínku spustily (seřazené; prázdné
    u podmínek, které se surovin netýkají).
    """

    level: WarningLevel
    code: str
    message_cs: str
    source_key: str
    ingredient_codes: tuple[str, ...]


def _matches(condition: Condition, context: RuleContext) -> tuple[bool, tuple[str, ...]]:
    if isinstance(condition, Always):
        return True, ()
    if isinstance(condition, IngredientFlagPresent):
        codes = tuple(
            entry.ingredient_code
            for entry in context.items
            if condition.flag in entry.profile.safety_flags
        )
        return bool(codes), codes
    if isinstance(condition, CategoryMassShareAbove):
        members = [entry for entry in context.items if entry.profile.category == condition.category]
        with calc_context():
            total = sum((entry.grams for entry in context.items), Decimal(0))
            category = sum((entry.grams for entry in members), Decimal(0))
            above = category > condition.share * total
        return above, tuple(entry.ingredient_code for entry in members) if above else ()
    statuses = context.nutrient_statuses.get(condition.nutrient_code, frozenset())
    return bool(statuses & condition.statuses), ()


def _warning_key(warning: RuleWarning) -> tuple[int, str, tuple[str, ...], str]:
    return (
        -WARNING_LEVEL_RANK[warning.level],
        warning.code,
        warning.ingredient_codes,
        warning.message_cs,
    )


def evaluate_rules(rules: Iterable[WarningRule], context: RuleContext) -> tuple[RuleWarning, ...]:
    """Vyhodnotí pravidla nad kontextem rozboru.

    Pravidlo se uplatní, když platí pro druh zvířete (``species`` je ``None``
    nebo druh obsahuje) a jeho podmínka je splněna.

    Vstup: pravidla (libovolné pořadí) a :class:`RuleContext`.
    Výstup: upozornění seřazená od nejzávažnější úrovně, dále podle kódu a
    surovin (nezávisle na pořadí pravidel i položek).
    Chyby: ``TypeError`` pro jiné typy;
    :class:`~nutricalc.errors.ValidationError`, je-li kód pravidla uveden vícekrát.
    """
    if not isinstance(context, RuleContext):
        raise TypeError(f"evaluate_rules očekává RuleContext, ne {type(context).__name__}.")
    seen: set[str] = set()
    warnings: list[RuleWarning] = []
    for rule in rules:
        if not isinstance(rule, WarningRule):
            raise TypeError(f"Pravidlo musí být WarningRule, ne {type(rule).__name__}.")
        if rule.code in seen:
            raise ValidationError(f"Pravidlo {rule.code} je uvedeno vícekrát.")
        seen.add(rule.code)
        if rule.species is not None and context.species not in rule.species:
            continue
        matched, codes = _matches(rule.condition, context)
        if matched:
            warnings.append(
                RuleWarning(
                    level=rule.level,
                    code=rule.code,
                    message_cs=rule.message_cs,
                    source_key=rule.source_key,
                    ingredient_codes=tuple(sorted(codes)),
                )
            )
    return tuple(sorted(warnings, key=_warning_key))


def sorted_rules(rules: Iterable[WarningRule]) -> tuple[WarningRule, ...]:
    """Ověří pravidla a seřadí je podle kódu (kanonické pořadí pro snapshot).

    Chyby: ``TypeError`` pro jiný typ;
    :class:`~nutricalc.errors.ValidationError` pro duplicitní kód.
    """
    collected: dict[str, WarningRule] = {}
    for rule in rules:
        if not isinstance(rule, WarningRule):
            raise TypeError(f"Pravidlo musí být WarningRule, ne {type(rule).__name__}.")
        if rule.code in collected:
            raise ValidationError(f"Pravidlo {rule.code} je uvedeno vícekrát.")
        collected[rule.code] = rule
    return tuple(collected[code] for code in sorted(collected))
