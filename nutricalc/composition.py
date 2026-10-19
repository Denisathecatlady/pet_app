"""Hodnoty živin surovin a denní součty dávky s intervaly a úplností (docs/06 §6.5).

Všechny hodnoty :class:`NutrientValue` jsou **na 100 g původní hmoty** (as
fed) v kanonické jednotce živiny. Příspěvek suroviny je
``c_i = g_i / 100 · v_i`` a součet živiny ``T_n = Σ c_i``. Chybějící
hodnota se nikdy nepovažuje za nulu: součet je pak ``PARTIAL`` (známá jen
dolní mez) nebo ``UNKNOWN`` (docs/06 §6.5.2). Intervaly se sčítají jako
nejhorší případ ``[Σ lo, Σ hi]``.

Položky receptu se zpracovávají seřazené podle kódu suroviny, takže výsledek
nezávisí na pořadí zadání (docs/07 §7.2).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cached_property
from types import MappingProxyType
from typing import Final, NamedTuple, cast

from nutricalc.decimal_ctx import calc_context, to_decimal, to_optional_decimal
from nutricalc.errors import DuplicateItemError, UnitMismatchError, ValidationError
from nutricalc.units import Quantity
from nutricalc.vocab import (
    Basis,
    Completeness,
    QualityGrade,
    Unit,
    ValueKind,
    as_member,
    require_text,
)

MEASURED_KINDS: Final = frozenset(
    {ValueKind.MEASURED, ValueKind.CALCULATED, ValueKind.BORROWED, ValueKind.IMPUTED}
)
"""Stavy s číselnou hodnotou (a volitelně intervalem [min, max] ze zdroje)."""

LOD_KINDS: Final = frozenset({ValueKind.BELOW_LOD, ValueKind.TRACE})
"""Stavy pod mezí detekce nebo „stopy“: interval [0, LOD], bez bodové hodnoty."""

_ZERO: Final = Decimal(0)
_HUNDRED: Final = Decimal(100)


@dataclass(frozen=True)
class NutrientValue:
    """Hodnota jedné živiny suroviny na 100 g původní hmoty (kanonická jednotka).

    Pole:
        ``value`` – hodnota, nebo ``None`` (povinně u ``MISSING``; povoleno
        u ``BELOW_LOD`` a ``TRACE``).
        ``kind`` – :class:`~nutricalc.vocab.ValueKind`.
        ``value_min``, ``value_max`` – volitelný interval ze zdroje (jen
        u ``MEASURED``, ``CALCULATED``, ``BORROWED``, ``IMPUTED``), platí
        ``value_min ≤ value ≤ value_max``.
        ``lod`` – mez detekce > 0 (jen u ``BELOW_LOD`` a ``TRACE``; je-li
        zadaná i hodnota, platí ``value ≤ lod``).
        ``quality`` – kvalita údaje A–D (povinný pojmenovaný argument).

    Pravidla: ``MISSING`` ⇔ ``value is None`` (kromě ``BELOW_LOD``/``TRACE``,
    které hodnotu mít nemusí); ``ZERO_BY_DEFINITION`` ⇒ ``value == 0``; čísla
    nesmí být záporná.

    Chyby: ``TypeError`` pro ``float``;
    :class:`~nutricalc.errors.ValidationError` (včetně podtřídy
    :class:`~nutricalc.errors.InvalidInputError` pro záporné číslo) pro
    porušení pravidel.
    """

    value: Decimal | None
    kind: ValueKind
    value_min: Decimal | None = field(default=None, kw_only=True)
    value_max: Decimal | None = field(default=None, kw_only=True)
    lod: Decimal | None = field(default=None, kw_only=True)
    quality: QualityGrade = field(kw_only=True)

    def __post_init__(self) -> None:
        kind = as_member(ValueKind, self.kind, "stav hodnoty")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "quality", as_member(QualityGrade, self.quality, "kvalita údaje"))
        for name in ("value", "value_min", "value_max", "lod"):
            number = to_optional_decimal(getattr(self, name), name=f"NutrientValue.{name}")
            object.__setattr__(self, name, number)
        value, low, high, lod = self.value, self.value_min, self.value_max, self.lod
        if kind == ValueKind.MISSING:
            if any(number is not None for number in (value, low, high, lod)):
                raise ValidationError(
                    "Hodnota MISSING nesmí mít číslo, interval ani LOD (chybějící údaj není 0)."
                )
            return
        if kind == ValueKind.ZERO_BY_DEFINITION:
            if value is None or value != 0 or any(n is not None for n in (low, high, lod)):
                raise ValidationError(
                    "Hodnota ZERO_BY_DEFINITION musí mít value = 0 a žádný interval ani LOD."
                )
            return
        if kind in LOD_KINDS:
            if low is not None or high is not None:
                raise ValidationError(f"Hodnota {kind} nesmí mít interval value_min/value_max.")
            if lod is not None and not lod > 0:
                raise ValidationError(f"Mez detekce (LOD) musí být větší než 0 (zadáno {lod}).")
            if value is not None and lod is not None and value > lod:
                raise ValidationError(f"Hodnota {kind} {value} nesmí být větší než LOD {lod}.")
            return
        if value is None:
            raise ValidationError(
                f"Hodnota {kind} musí mít číslo. Chybějící údaj zapište jako MISSING."
            )
        if lod is not None:
            raise ValidationError(f"LOD lze zadat jen u BELOW_LOD a TRACE, ne u {kind}.")
        if low is not None and low > value:
            raise ValidationError(f"value_min {low} je větší než hodnota {value}.")
        if high is not None and high < value:
            raise ValidationError(f"value_max {high} je menší než hodnota {value}.")


MISSING_VALUE: Final = NutrientValue(None, ValueKind.MISSING, quality=QualityGrade.D)
"""Hodnota živiny, kterou profil suroviny neuvádí (kvalita D = bez údaje)."""


NutrientValues = Mapping[str, NutrientValue] | Iterable[tuple[str, NutrientValue]]
"""Vstup hodnot živin profilu: mapování ``kód → hodnota`` nebo dvojice."""


@dataclass(frozen=True, init=False)
class IngredientProfile:
    """Neměnný profil složení jedné suroviny (jedna verze dat).

    Pole:
        ``ingredient_code`` – kód suroviny (neprázdný text, klíč v receptu).
        ``profile_id`` – identifikátor verze profilu.
        ``category`` – kategorie suroviny (text, např. ``MUSCLE``).
        ``safety_flags`` – bezpečnostní příznaky (``frozenset`` textů; přijme
        i jinou kolekci textů).
        ``values`` – hodnoty živin. Přijme ``Mapping[str, NutrientValue]`` nebo
        dvojice ``(kód, hodnota)``; uloží se jako n-tice dvojic seřazená podle
        kódu živiny.

    Živina, která v ``values`` chybí, má stav ``MISSING`` (:meth:`get`).

    Chyby: ``TypeError`` pro nesprávné typy;
    :class:`~nutricalc.errors.ValidationError` pro prázdný kód nebo duplicitní
    kód živiny.
    """

    ingredient_code: str
    profile_id: str
    category: str
    safety_flags: frozenset[str]
    values: tuple[tuple[str, NutrientValue], ...]

    def __init__(
        self,
        ingredient_code: str,
        profile_id: str,
        category: str,
        safety_flags: Iterable[str],
        values: NutrientValues,
    ) -> None:
        object.__setattr__(
            self,
            "ingredient_code",
            require_text(ingredient_code, "IngredientProfile.ingredient_code"),
        )
        object.__setattr__(
            self, "profile_id", require_text(profile_id, "IngredientProfile.profile_id")
        )
        object.__setattr__(self, "category", require_text(category, "IngredientProfile.category"))
        if isinstance(safety_flags, str) or not isinstance(safety_flags, Iterable):
            raise TypeError("safety_flags musí být kolekce textů (např. frozenset).")
        normalized_flags = frozenset(safety_flags)
        for flag in normalized_flags:
            require_text(flag, "Bezpečnostní příznak")
        object.__setattr__(self, "safety_flags", normalized_flags)
        pairs = values.items() if isinstance(values, Mapping) else values
        collected: dict[str, NutrientValue] = {}
        for code, value in pairs:
            require_text(code, "Kód živiny")
            if not isinstance(value, NutrientValue):
                raise TypeError(f"Hodnota živiny {code} musí být NutrientValue.")
            if code in collected:
                raise ValidationError(
                    f"Surovina {ingredient_code}: živina {code} je v profilu vícekrát."
                )
            collected[code] = value
        object.__setattr__(self, "values", tuple(sorted(collected.items())))

    @cached_property
    def _index(self) -> dict[str, NutrientValue]:
        # Mezipaměť pro vyhledávání; není polem dataclass, takže neovlivní
        # rovnost, hash ani serializaci profilu.
        return dict(self.values)

    @property
    def values_map(self) -> Mapping[str, NutrientValue]:
        """Hodnoty živin jako neměnné mapování ``kód → NutrientValue``."""
        return MappingProxyType(self._index)

    def get(self, nutrient_code: str) -> NutrientValue:
        """Vrátí hodnotu živiny; neuvedená živina je :data:`MISSING_VALUE`."""
        return self._index.get(nutrient_code, MISSING_VALUE)


@dataclass(frozen=True)
class RecipeItem:
    """Položka receptu: profil suroviny a denní množství v gramech (as fed).

    Chyby: ``TypeError`` pro jiný typ profilu nebo ``float`` gramy;
    :class:`~nutricalc.errors.ValidationError` pro gramy ≤ 0.
    """

    profile: IngredientProfile
    grams: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.profile, IngredientProfile):
            raise TypeError(
                f"RecipeItem.profile musí být IngredientProfile, ne {type(self.profile).__name__}."
            )
        grams = to_decimal(self.grams, name=f"Gramy suroviny {self.profile.ingredient_code}")
        if not grams > 0:
            raise ValidationError(
                f"Množství suroviny {self.profile.ingredient_code} musí být větší než 0 g "
                f"(zadáno {grams})."
            )
        object.__setattr__(self, "grams", grams)

    @property
    def ingredient_code(self) -> str:
        """Kód suroviny (zkratka pro ``profile.ingredient_code``)."""
        return self.profile.ingredient_code


def validate_items(items: Iterable[RecipeItem]) -> tuple[RecipeItem, ...]:
    """Zkontroluje položky receptu a seřadí je podle kódu suroviny.

    Vstup: položky v libovolném pořadí.
    Výstup: n-tice položek seřazená podle ``ingredient_code``.
    Chyby: ``TypeError`` pro jinou položku než :class:`RecipeItem`;
    :class:`~nutricalc.errors.ValidationError` pro prázdný recept;
    :class:`~nutricalc.errors.DuplicateItemError`, je-li stejná surovina
    (stejný ``ingredient_code``) v receptu vícekrát – položky se neslučují.
    """
    collected: dict[str, RecipeItem] = {}
    for item in items:
        if not isinstance(item, RecipeItem):
            raise TypeError(f"Položka receptu musí být RecipeItem, ne {type(item).__name__}.")
        if item.ingredient_code in collected:
            raise DuplicateItemError(
                f"Surovina {item.ingredient_code} je v receptu vícekrát. Položky se neslučují "
                "automaticky: upravte recept tak, aby každá surovina byla jen jednou."
            )
        collected[item.ingredient_code] = item
    if not collected:
        raise ValidationError("Recept nemá žádnou položku.")
    return tuple(collected[code] for code in sorted(collected))


@dataclass(frozen=True)
class Contribution:
    """Příspěvek jedné suroviny k denní dávce živiny.

    ``lower``: dolní mez (≥ 0; u neznámé hodnoty 0, protože množství nemůže
    být záporné). ``upper``: horní mez, nebo ``None``, když není známá.
    ``point``: bodová hodnota, nebo ``None`` (pod LOD, stopy, neznámo).
    ``known``: ``True``, když je horní mez známá.
    """

    lower: Decimal
    upper: Decimal | None
    point: Decimal | None
    known: bool


_UNKNOWN_CONTRIBUTION: Final = Contribution(_ZERO, None, None, False)


def _grams(grams: Decimal | int | str) -> Decimal:
    amount = to_decimal(grams, name="Množství v gramech")
    if not amount > 0:
        raise ValidationError(f"Množství musí být větší než 0 g (zadáno {amount}).")
    return amount


def contribution(nv: NutrientValue, grams: Decimal | int | str) -> Contribution:
    """Spočítá příspěvek suroviny podle stavu hodnoty (docs/06 §6.5.1).

    =====================================================  ======================  ========
    Stav                                                   interval                bod
    =====================================================  ======================  ========
    ``MEASURED``, ``CALCULATED``, ``BORROWED``, ``IMPUTED``  [min, max], jinak [v, v]  v
    ``BELOW_LOD``, ``TRACE`` s LOD                         [0, LOD]                –
    ``BELOW_LOD``, ``TRACE`` bez LOD                       [0, neznámo]            –
    ``ZERO_BY_DEFINITION``                                 [0, 0]                  0
    ``MISSING``                                            [0, neznámo]            –
    =====================================================  ======================  ========

    Chybí-li jen jedna mez intervalu ze zdroje, nahradí ji hodnota ``v``.
    Všechny meze se násobí ``gramy / 100``.

    Vstup: hodnota živiny na 100 g a množství suroviny v gramech (> 0).
    Výstup: :class:`Contribution` (``known`` = horní mez je známá).
    Chyby: ``TypeError`` pro jiný typ;
    :class:`~nutricalc.errors.ValidationError` pro gramy ≤ 0.
    """
    if not isinstance(nv, NutrientValue):
        raise TypeError(f"contribution očekává NutrientValue, ne {type(nv).__name__}.")
    amount = _grams(grams)
    kind = nv.kind
    if kind == ValueKind.MISSING:
        return _UNKNOWN_CONTRIBUTION
    if kind == ValueKind.ZERO_BY_DEFINITION:
        return Contribution(_ZERO, _ZERO, _ZERO, True)
    with calc_context():
        scale = amount / _HUNDRED
        if kind in LOD_KINDS:
            if nv.lod is None:
                return _UNKNOWN_CONTRIBUTION
            return Contribution(_ZERO, nv.lod * scale, None, True)
        # Stavy MEASURED_KINDS mají číslo vždy (vynucuje NutrientValue.__post_init__).
        value = cast(Decimal, nv.value)
        low = nv.value_min if nv.value_min is not None else value
        high = nv.value_max if nv.value_max is not None else value
        return Contribution(low * scale, high * scale, value * scale, True)


class Contributor(NamedTuple):
    """Surovina se známým příspěvkem k součtu živiny (meze za den)."""

    ingredient_code: str
    lower: Decimal
    upper: Decimal


@dataclass(frozen=True)
class NutrientTotal:
    """Denní součet jedné živiny v dávce (docs/06 §6.5.2).

    ``nutrient_code``, ``unit`` (kanonická jednotka živiny), ``basis``
    (vždy ``PER_DAY``).
    ``lower``: dolní mez Σ lo přes všechny suroviny (neznámé přispívají 0).
    ``upper``: horní mez Σ hi, jen pro ``COMPLETE``, jinak ``None``.
    ``point``: bodový součet, jen pro ``COMPLETE`` a jen když každá surovina
    má bodovou hodnotu (ne pod LOD, ne stopy), jinak ``None``.
    ``completeness``: ``COMPLETE`` (všechny suroviny známé), ``PARTIAL``
    (některé neznámé), ``UNKNOWN`` (žádná známá).
    ``missing_mass_share``: podíl gramů dávky bez známé horní meze (0–1).
    ``contributors``: suroviny se známou horní mezí jako :class:`Contributor`,
    seřazené podle horní meze sestupně, pak podle kódu.

    Hodnotu ``lower`` u ``PARTIAL`` a ``UNKNOWN`` nelze vykládat jako obsah
    živiny: je to jen dolní mez (chybějící údaj není nula).
    """

    nutrient_code: str
    unit: Unit
    basis: Basis
    lower: Decimal
    upper: Decimal | None
    point: Decimal | None
    completeness: Completeness
    missing_mass_share: Decimal
    contributors: tuple[Contributor, ...]

    def lower_quantity(self) -> Quantity:
        """Dolní mez jako :class:`~nutricalc.units.Quantity` (na den)."""
        return Quantity(self.lower, self.unit, self.basis)

    def upper_quantity(self) -> Quantity | None:
        """Horní mez jako :class:`~nutricalc.units.Quantity`, nebo ``None``."""
        return None if self.upper is None else Quantity(self.upper, self.unit, self.basis)

    def point_quantity(self) -> Quantity | None:
        """Bodový součet jako :class:`~nutricalc.units.Quantity`, nebo ``None``."""
        return None if self.point is None else Quantity(self.point, self.unit, self.basis)


def sum_nutrient(
    items: Iterable[RecipeItem], nutrient_code: str, unit: Unit | str
) -> NutrientTotal:
    """Sečte živinu přes položky receptu s intervaly a úplností (docs/06 §6.5).

    Vstup: položky receptu (libovolné pořadí), kód živiny a její kanonická
    jednotka (jádro katalog živin nečte; jednotku dodá volající).
    Výstup: :class:`NutrientTotal` na den. Výsledek nezávisí na pořadí položek.
    Chyby: jako :func:`validate_items`;
    :class:`~nutricalc.errors.UnitMismatchError` pro jednotku ``ratio``
    (poměry se nesčítají); :class:`~nutricalc.errors.ValidationError` pro
    prázdný kód živiny.
    """
    ordered = validate_items(items)
    code = require_text(nutrient_code, "Kód živiny")
    member = as_member(Unit, unit, "jednotka")
    if member == Unit.RATIO:
        raise UnitMismatchError(
            f"Poměr {code} nelze sčítat přes suroviny; počítá se z denních součtů."
        )
    lower = _ZERO
    upper = _ZERO
    point = _ZERO
    has_point = True
    total_grams = _ZERO
    missing_grams = _ZERO
    contributors: list[Contributor] = []
    with calc_context():
        for item in ordered:
            part = contribution(item.profile.get(code), item.grams)
            total_grams += item.grams
            lower += part.lower
            if part.upper is not None:
                upper += part.upper
                contributors.append(Contributor(item.ingredient_code, part.lower, part.upper))
            else:
                missing_grams += item.grams
            if part.point is None:
                has_point = False
            else:
                point += part.point
        share = missing_grams / total_grams
        contributors.sort(key=lambda c: (-c.upper, c.ingredient_code))
    if not contributors:
        completeness = Completeness.UNKNOWN
    elif len(contributors) < len(ordered):
        completeness = Completeness.PARTIAL
    else:
        completeness = Completeness.COMPLETE
    complete = completeness == Completeness.COMPLETE
    return NutrientTotal(
        nutrient_code=code,
        unit=member,
        basis=Basis.PER_DAY,
        lower=lower,
        upper=upper if complete else None,
        point=point if complete and has_point else None,
        completeness=completeness,
        missing_mass_share=share,
        contributors=tuple(contributors),
    )
