"""Neměnný vstup rozboru a kanonická serializace pro hash (docs/07 §7.2).

:class:`AnalysisInput` obsahuje **všechny** hodnoty, které výpočet použije
(zvíře, recept se složením surovin, koeficient energie, oba sloupce
standardu, pravidla, prahy a verze dat), takže jádro nic nečte z databáze.
Kolekce se při vytvoření normalizují do kanonického pořadí (položky podle
kódu suroviny, pravidla a zdravotní stavy podle kódu, verze dat podle
oblasti), proto hash nezávisí na pořadí zadání.

:func:`canonical_json` převádí snapshot i výsledky na JSON se seřazenými
klíči, ``Decimal`` jako text přesně v uloženém tvaru, slovníkové hodnoty
jako text, n-tice jako seznamy v uloženém (kanonickém) pořadí, množiny jako
seznamy seřazené podle kanonického JSON prvků. Čísla ``float`` odmítá.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum

from nutricalc.composition import RecipeItem, validate_items
from nutricalc.decimal_ctx import to_decimal
from nutricalc.energy import BCS_MAX, BCS_MIN, EnergyFactor
from nutricalc.errors import InvalidInputError, ValidationError
from nutricalc.gate import HealthConditionRef
from nutricalc.requirements import StandardProfile
from nutricalc.rules import WarningRule, sorted_rules
from nutricalc.vocab import (
    DataScope,
    LifeStage,
    MeMethod,
    PhysiologicalState,
    Species,
    as_member,
    require_text,
)


@dataclass(frozen=True, kw_only=True)
class AnimalSnapshot:
    """Údaje o zvířeti v okamžiku rozboru.

    Pole (jen jako pojmenované argumenty):
        ``species`` – druh.
        ``body_weight_kg`` – aktuální hmotnost v kg (``Decimal``, ``int`` nebo
        text; technické meze kontroluje odhad energie).
        ``physiological_state`` – fyziologický stav (bezpečnostní brána a
        odhad energie).
        ``life_stage`` – životní fáze profilu standardu, do které zvíře patří
        (např. ``ADULT_MAINTENANCE``); musí patřit do dvojice sloupců
        standardu. Soulad fáze s fyziologickým stavem určuje aplikační vrstva;
        jádro blokuje podle fyziologického stavu.
        ``bcs`` – BCS 1–9 nebo ``None``.
        ``neutered`` – kastrace (``bool``).
        ``health_conditions`` – zdravotní stavy (seřadí se podle kódu).

    Chyby: ``TypeError`` pro nesprávné typy;
    :class:`~nutricalc.errors.InvalidInputError` pro neplatné číslo nebo BCS
    mimo 1–9; :class:`~nutricalc.errors.ValidationError` pro zdravotní stav
    uvedený vícekrát.
    """

    species: Species
    body_weight_kg: Decimal
    physiological_state: PhysiologicalState
    life_stage: LifeStage
    bcs: int | None
    neutered: bool
    health_conditions: tuple[HealthConditionRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "species", as_member(Species, self.species, "druh"))
        object.__setattr__(
            self, "body_weight_kg", to_decimal(self.body_weight_kg, name="Hmotnost (kg)")
        )
        object.__setattr__(
            self,
            "physiological_state",
            as_member(PhysiologicalState, self.physiological_state, "fyziologický stav"),
        )
        object.__setattr__(
            self, "life_stage", as_member(LifeStage, self.life_stage, "životní fáze")
        )
        if self.bcs is not None:
            if isinstance(self.bcs, bool) or not isinstance(self.bcs, int):
                raise TypeError(
                    f"BCS musí být celé číslo 1–9 nebo None, ne {type(self.bcs).__name__}."
                )
            if not BCS_MIN <= self.bcs <= BCS_MAX:
                raise InvalidInputError(
                    f"BCS {self.bcs} je mimo devítibodovou škálu {BCS_MIN}–{BCS_MAX}."
                )
        if not isinstance(self.neutered, bool):
            raise TypeError(f"Údaj o kastraci musí být bool, ne {type(self.neutered).__name__}.")
        if isinstance(self.health_conditions, (str, HealthConditionRef)) or not isinstance(
            self.health_conditions, Iterable
        ):
            raise TypeError("health_conditions musí být kolekce HealthConditionRef.")
        collected: dict[str, HealthConditionRef] = {}
        for condition in self.health_conditions:
            if not isinstance(condition, HealthConditionRef):
                raise TypeError(
                    f"Zdravotní stav musí být HealthConditionRef, ne {type(condition).__name__}."
                )
            if condition.code in collected:
                raise ValidationError(f"Zdravotní stav {condition.code} je uveden vícekrát.")
            collected[condition.code] = condition
        object.__setattr__(
            self, "health_conditions", tuple(collected[code] for code in sorted(collected))
        )


def _data_versions(value: object) -> tuple[tuple[DataScope, str], ...]:
    if isinstance(value, Mapping):
        pairs: Iterable[object] = value.items()
    elif isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError("data_versions musí být kolekce dvojic (oblast, verze).")
    else:
        pairs = value
    collected: dict[DataScope, str] = {}
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise TypeError("Každá verze dat musí být dvojice (oblast, verze).")
        scope = as_member(DataScope, pair[0], "oblast verze dat")
        label = require_text(pair[1], f"Verze dat {scope}")
        if scope in collected:
            raise ValidationError(f"Verze dat pro oblast {scope} je uvedena vícekrát.")
        collected[scope] = label
    return tuple((scope, collected[scope]) for scope in sorted(collected))


@dataclass(frozen=True, kw_only=True)
class AnalysisInput:
    """Neměnný a serializovatelný vstup rozboru (docs/06 §6.9, docs/07 §7.2).

    Pole (jen jako pojmenované argumenty):
        ``animal`` – :class:`AnimalSnapshot`.
        ``items`` – položky receptu (seřadí se podle kódu suroviny; prázdný
        recept a duplicitní surovina jsou chybou).
        ``energy_factor`` – schválený koeficient ``k``
        (:class:`~nutricalc.energy.EnergyFactor`).
        ``high_profile``, ``low_profile`` – vyšší a nižší sloupec standardu.
        ``me_method`` – metoda ME (:class:`~nutricalc.vocab.MeMethod`).
        ``warning_rules`` – pravidla upozornění (seřadí se podle kódu).
        ``confidence_threshold`` – práh významnosti suroviny pro spolehlivost
        (podíl 0–1, docs/06 §6.6.5; data 🛠 🩺).
        ``data_versions`` – dvojice (oblast, verze), např.
        ``(("STANDARDS", "standards-2026.1"), …)``; seřadí se podle oblasti.
        ``engine_version`` – verze jádra, pro kterou byl snapshot sestaven.

    Chyby: ``TypeError`` pro nesprávné typy (včetně ``float``);
    :class:`~nutricalc.errors.ValidationError` pro prázdný recept,
    duplicitní surovinu (:class:`~nutricalc.errors.DuplicateItemError`),
    duplicitní pravidlo nebo oblast verze dat;
    :class:`~nutricalc.errors.InvalidInputError` pro neznámou metodu nebo
    práh mimo 0–1.
    """

    animal: AnimalSnapshot
    items: tuple[RecipeItem, ...]
    energy_factor: EnergyFactor
    high_profile: StandardProfile
    low_profile: StandardProfile
    me_method: MeMethod
    warning_rules: tuple[WarningRule, ...] = ()
    confidence_threshold: Decimal
    data_versions: tuple[tuple[DataScope, str], ...]
    engine_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.animal, AnimalSnapshot):
            raise TypeError(f"animal musí být AnimalSnapshot, ne {type(self.animal).__name__}.")
        if isinstance(self.items, RecipeItem) or not isinstance(self.items, Iterable):
            raise TypeError("items musí být kolekce RecipeItem.")
        object.__setattr__(self, "items", validate_items(self.items))
        if not isinstance(self.energy_factor, EnergyFactor):
            raise TypeError(
                f"energy_factor musí být EnergyFactor, ne {type(self.energy_factor).__name__}."
            )
        for name in ("high_profile", "low_profile"):
            if not isinstance(getattr(self, name), StandardProfile):
                raise TypeError(f"{name} musí být StandardProfile.")
        object.__setattr__(self, "me_method", as_member(MeMethod, self.me_method, "metoda ME"))
        if isinstance(self.warning_rules, WarningRule) or not isinstance(
            self.warning_rules, Iterable
        ):
            raise TypeError("warning_rules musí být kolekce WarningRule.")
        object.__setattr__(self, "warning_rules", sorted_rules(self.warning_rules))
        if not isinstance(self.confidence_threshold, Decimal):
            raise TypeError(
                "confidence_threshold musí být Decimal (podíl 0–1), ne "
                f"{type(self.confidence_threshold).__name__}."
            )
        threshold = to_decimal(self.confidence_threshold, name="Práh spolehlivosti")
        if threshold > 1:
            raise InvalidInputError(f"Práh spolehlivosti musí být 0 až 1 (zadáno {threshold}).")
        object.__setattr__(self, "confidence_threshold", threshold)
        object.__setattr__(self, "data_versions", _data_versions(self.data_versions))
        require_text(self.engine_version, "engine_version")

    @property
    def data_versions_map(self) -> dict[DataScope, str]:
        """Verze dat jako slovník oblast → verze."""
        return dict(self.data_versions)


# --- kanonická serializace ---------------------------------------------------------------------


def _element_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _key(value: object) -> str:
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        raise TypeError(f"Klíč mapování musí být text, ne {type(value).__name__}.")
    return str(value)


def to_canonical(obj: object, *, exclude: frozenset[str] = frozenset()) -> object:
    """Převede objekt jádra na strukturu pro JSON (bez ``float``).

    Pravidla: ``None``, ``bool``, ``int`` a text beze změny; člen slovníku →
    jeho hodnota; ``Decimal`` → ``str`` (přesně v uloženém tvaru, např.
    ``"0.50"``); dataclass → objekt s poli (``exclude`` vynechá pole jen na
    nejvyšší úrovni); pojmenovaná n-tice → objekt; n-tice a seznam → seznam
    v uloženém pořadí; ``frozenset``/``set`` → seznam seřazený podle
    kanonického JSON prvků; mapování → objekt s textovými klíči.

    Chyby: ``TypeError`` pro ``float`` a každý jiný nepodporovaný typ;
    :class:`~nutricalc.errors.InvalidInputError` pro nekonečné ``Decimal``.
    """
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Enum):
        return to_canonical(obj.value)
    if isinstance(obj, (str, int)):
        return obj
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            raise InvalidInputError(f"Hodnota {obj} není konečné číslo a nelze ji uložit.")
        return str(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            item.name: to_canonical(getattr(obj, item.name))
            for item in fields(obj)
            if item.name not in exclude
        }
    if isinstance(obj, tuple) and hasattr(obj, "_asdict"):
        return {name: to_canonical(value) for name, value in obj._asdict().items()}
    if isinstance(obj, (tuple, list)):
        return [to_canonical(value) for value in obj]
    if isinstance(obj, (frozenset, set)):
        return sorted((to_canonical(value) for value in obj), key=_element_key)
    if isinstance(obj, Mapping):
        return {_key(key): to_canonical(value) for key, value in obj.items()}
    raise TypeError(
        f"Typ {type(obj).__name__} nelze kanonicky serializovat. Jádro ukládá čísla jen jako "
        "Decimal; čísla float nejsou povolena."
    )


def canonical_json(obj: object, *, exclude: frozenset[str] = frozenset()) -> str:
    """Kanonický JSON objektu jádra (docs/07 §7.2).

    Seřazené klíče, ``ensure_ascii=False``, oddělovače ``(",", ":")``, bez
    ``NaN``; převod hodnot podle :func:`to_canonical`.

    Vstup: snapshot, výsledek nebo jiný objekt jádra; ``exclude`` = pole
    nejvyšší úrovně, která se vynechají (např. ``result_hash``).
    Výstup: text JSON.
    Chyby: jako :func:`to_canonical`.
    """
    return json.dumps(
        to_canonical(obj, exclude=exclude),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    """SHA-256 textu v UTF-8 jako 64 malých šestnáctkových znaků.

    Chyby: ``TypeError`` pro jiný typ než text.
    """
    if not isinstance(text, str):
        raise TypeError(f"sha256_hex očekává text, ne {type(text).__name__}.")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_hash(inp: AnalysisInput) -> str:
    """Hash vstupu rozboru: SHA-256 kanonického JSON snapshotu (docs/07 §7.2).

    Chyby: ``TypeError`` pro jiný typ než :class:`AnalysisInput`.
    """
    if not isinstance(inp, AnalysisInput):
        raise TypeError(f"input_hash očekává AnalysisInput, ne {type(inp).__name__}.")
    return sha256_hex(canonical_json(inp))
