"""Veličiny s jednotkou a bází a explicitní převody (docs/06 §6.2, docs/09 T1).

:class:`Quantity` nese hodnotu, jednotku a bázi. Sčítat, odčítat a
porovnávat (``<``, ``<=``, ``>``, ``>=``) lze jen veličiny se stejnou
jednotkou **i** bází; jinak vznikne :class:`~nutricalc.errors.UnitMismatchError`
nebo :class:`~nutricalc.errors.BasisMismatchError` (jádro nikdy tiše
nepřevádí). Rovnost ``==`` výjimku nevyhazuje: veličiny s jinou jednotkou
nebo bází si prostě nejsou rovny (``1 g != 1000 mg``).

Převody jednotek: :meth:`Quantity.to_unit` (g ↔ mg ↔ µg, kcal ↔ kJ).
Převody bází: jen explicitní funkce tohoto modulu; každá kontroluje vstupní
bázi. Poměr (jednotka ``ratio``) na bázi nezávisí, proto ho převody bází
odmítají.
"""

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from nutricalc.decimal_ctx import calc_context, to_decimal
from nutricalc.errors import (
    BasisMismatchError,
    InvalidInputError,
    MissingDataError,
    UnitMismatchError,
    ValidationError,
)
from nutricalc.vocab import (
    BASIS_LABELS,
    METABOLIC_BASIS,
    METABOLIC_EXPONENT,
    Basis,
    Species,
    Unit,
    as_member,
)

# 1 kcal = 4,184 kJ: definice termochemické kalorie, odpovídá převodu MJ ve
# [FEDIAF2025] (docs/05 §5.1, docs/03 §3.5), stav ✅ S.
KJ_PER_KCAL: Final = Decimal("4.184")

MASS_UNITS: Final = frozenset({Unit.G, Unit.MG, Unit.UG})
"""Jednotky hmotnosti (vzájemně převoditelné)."""

ENERGY_UNITS: Final = frozenset({Unit.KCAL, Unit.KJ})
"""Jednotky energie (vzájemně převoditelné)."""

_UG_PER_UNIT: Final = MappingProxyType(
    {Unit.G: Decimal(1000000), Unit.MG: Decimal(1000), Unit.UG: Decimal(1)}
)
_HUNDRED: Final = Decimal(100)
_THOUSAND: Final = Decimal(1000)


@dataclass(frozen=True)
class Quantity:
    """Hodnota s jednotkou a bází.

    ``value``: ``Decimal`` (také ``int`` nebo text podle
    :func:`~nutricalc.decimal_ctx.to_decimal`; **znaménko je povolené**,
    protože rozdíl veličin může být záporný).
    ``unit``: :class:`~nutricalc.vocab.Unit` (nebo jeho textová hodnota).
    ``basis``: :class:`~nutricalc.vocab.Basis` (nebo jeho textová hodnota).

    Operace: ``+`` a ``-`` jen se stejnou jednotkou a bází; ``*`` a ``/``
    jen se skalárem ``Decimal``; ``<``, ``<=``, ``>``, ``>=`` jen se stejnou
    jednotkou a bází.

    Chyby: ``TypeError`` pro ``float``, ``bool`` a jiné typy;
    :class:`~nutricalc.errors.InvalidInputError` pro neplatné číslo, jednotku
    nebo bázi; :class:`~nutricalc.errors.UnitMismatchError` (rozdílná
    jednotka, kontroluje se první) a :class:`~nutricalc.errors.BasisMismatchError`
    u operací se dvěma veličinami.
    """

    value: Decimal
    unit: Unit
    basis: Basis

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "value", to_decimal(self.value, signed=True, name="Quantity.value")
        )
        object.__setattr__(self, "unit", as_member(Unit, self.unit, "jednotka"))
        object.__setattr__(self, "basis", as_member(Basis, self.basis, "báze"))

    # --- operace se dvěma veličinami -----------------------------------------

    def _check_compatible(self, other: object, operation: str) -> "Quantity":
        if not isinstance(other, Quantity):
            raise TypeError(
                f"Operaci {operation} lze provést jen mezi dvěma veličinami Quantity, "
                f"ne s {type(other).__name__}."
            )
        if self.unit != other.unit:
            raise UnitMismatchError(
                f"Operace {operation}: jednotky se liší ({self.unit} a {other.unit}). "
                "Převeďte jednotku výslovně metodou to_unit()."
            )
        if self.basis != other.basis:
            raise BasisMismatchError(
                f"Operace {operation}: báze se liší ({BASIS_LABELS[self.basis]} a "
                f"{BASIS_LABELS[other.basis]}). Převeďte bázi výslovně funkcí z nutricalc.units."
            )
        return other

    def __add__(self, other: object) -> "Quantity":
        checked = self._check_compatible(other, "+")
        with calc_context():
            return Quantity(self.value + checked.value, self.unit, self.basis)

    def __sub__(self, other: object) -> "Quantity":
        checked = self._check_compatible(other, "-")
        with calc_context():
            return Quantity(self.value - checked.value, self.unit, self.basis)

    def __lt__(self, other: object) -> bool:
        return self.value < self._check_compatible(other, "<").value

    def __le__(self, other: object) -> bool:
        return self.value <= self._check_compatible(other, "<=").value

    def __gt__(self, other: object) -> bool:
        return self.value > self._check_compatible(other, ">").value

    def __ge__(self, other: object) -> bool:
        return self.value >= self._check_compatible(other, ">=").value

    # --- operace se skalárem ---------------------------------------------------

    @staticmethod
    def _scalar(scalar: object, operation: str) -> Decimal:
        if not isinstance(scalar, Decimal):
            raise TypeError(
                f"Operace {operation}: veličinu lze násobit nebo dělit jen skalárem Decimal, "
                f"ne {type(scalar).__name__}."
            )
        if not scalar.is_finite():
            raise InvalidInputError(f"Operace {operation}: skalár {scalar} není konečné číslo.")
        return scalar

    def __mul__(self, scalar: object) -> "Quantity":
        factor = self._scalar(scalar, "*")
        with calc_context():
            return Quantity(self.value * factor, self.unit, self.basis)

    __rmul__ = __mul__

    def __truediv__(self, scalar: object) -> "Quantity":
        divisor = self._scalar(scalar, "/")
        if divisor.is_zero():
            raise InvalidInputError("Veličinu nelze dělit nulou.")
        with calc_context():
            return Quantity(self.value / divisor, self.unit, self.basis)

    # --- převod jednotky ---------------------------------------------------------

    def to_unit(self, unit: Unit | str) -> "Quantity":
        """Převede veličinu na jinou jednotku stejné veličiny.

        Vstup: cílová jednotka. Povolené převody: g ↔ mg ↔ µg a kcal ↔ kJ
        (1 kcal = 4,184 kJ); převod na stejnou jednotku vrátí stejnou veličinu.
        Výstup: nová veličina se stejnou bází.
        Chyby: :class:`~nutricalc.errors.UnitMismatchError` pro jiný převod
        (např. g → kcal, cokoli ↔ ratio).
        """
        target = as_member(Unit, unit, "jednotka")
        if target == self.unit:
            return self
        with calc_context():
            if self.unit in MASS_UNITS and target in MASS_UNITS:
                value = self.value * _UG_PER_UNIT[self.unit] / _UG_PER_UNIT[target]
            elif self.unit in ENERGY_UNITS and target in ENERGY_UNITS:
                value = self.value * KJ_PER_KCAL if target == Unit.KJ else self.value / KJ_PER_KCAL
            else:
                raise UnitMismatchError(
                    f"Jednotku {self.unit} nelze převést na {target}. Převádět lze jen "
                    "g, mg a ug mezi sebou a kcal a kJ mezi sebou."
                )
        return Quantity(value, target, self.basis)


# --- explicitní převody bází ------------------------------------------------------


def _require(q: object, basis: Basis, function: str) -> Quantity:
    if not isinstance(q, Quantity):
        raise TypeError(f"{function}: očekává se Quantity, ne {type(q).__name__}.")
    if q.unit == Unit.RATIO:
        raise UnitMismatchError(
            f"{function}: poměr (ratio) na bázi nezávisí, převod báze u něj nemá smysl."
        )
    if q.basis != basis:
        raise BasisMismatchError(
            f"{function}: očekává se veličina {BASIS_LABELS[basis]}, ale veličina je "
            f"{BASIS_LABELS[q.basis]}."
        )
    return q


def _positive(value: Decimal | int | str, name: str) -> Decimal:
    number = to_decimal(value, name=name)
    if not number > 0:
        raise ValidationError(f"{name} musí být větší než 0 (zadáno {number}).")
    return number


def as_fed_to_dm(q: Quantity, water_g_per_100g: Decimal | int | str | None) -> Quantity:
    """Převede hodnotu na 100 g původní hmoty na 100 g sušiny.

    ``x_DM = x_AF / (1 − voda/100) = x_AF · 100 / (100 − voda)`` (docs/06 §6.2).

    Vstup: veličina s bází ``PER_100G_AS_FED`` a obsah vody v g/100 g.
    Výstup: veličina s bází ``PER_100G_DM`` ve stejné jednotce.
    Chyby: :class:`~nutricalc.errors.BasisMismatchError` pro jinou bázi;
    :class:`~nutricalc.errors.UnitMismatchError` pro poměr;
    :class:`~nutricalc.errors.MissingDataError`, je-li voda ``None``;
    :class:`~nutricalc.errors.ValidationError` pro vodu < 0 nebo ≥ 100.
    """
    checked = _require(q, Basis.PER_100G_AS_FED, "as_fed_to_dm")
    if water_g_per_100g is None:
        raise MissingDataError(
            "Převod na sušinu vyžaduje známý obsah vody (WATER). Chybějící vodu nelze "
            "nahradit nulou."
        )
    water = to_decimal(water_g_per_100g, signed=True, name="obsah vody")
    if water < 0 or water >= _HUNDRED:
        raise ValidationError(
            f"Obsah vody musí být alespoň 0 a menší než 100 g/100 g (zadáno {water})."
        )
    with calc_context():
        value = checked.value * _HUNDRED / (_HUNDRED - water)
    return Quantity(value, checked.unit, Basis.PER_100G_DM)


def per_100g_as_fed_to_per_day(q: Quantity, grams: Decimal | int | str) -> Quantity:
    """Převede obsah na 100 g původní hmoty na množství za den.

    Vstup: veličina ``PER_100G_AS_FED`` a denní množství suroviny v gramech
    (> 0). Výstup: veličina ``PER_DAY`` (``x · gramy / 100``).
    Chyby: :class:`~nutricalc.errors.BasisMismatchError`,
    :class:`~nutricalc.errors.UnitMismatchError` (poměr),
    :class:`~nutricalc.errors.ValidationError` pro gramy ≤ 0.
    """
    checked = _require(q, Basis.PER_100G_AS_FED, "per_100g_as_fed_to_per_day")
    amount = _positive(grams, "Množství v gramech")
    with calc_context():
        value = checked.value * (amount / _HUNDRED)
    return Quantity(value, checked.unit, Basis.PER_DAY)


def per_day_to_per_1000kcal(q: Quantity, me_kcal_per_day: Decimal | int | str) -> Quantity:
    """Převede denní množství na množství na 1000 kcal ME.

    ``x_1000 = x_den / (ME_den / 1000)`` (docs/06 §6.2).

    Vstup: veličina ``PER_DAY`` a ME dávky v kcal/den (> 0).
    Výstup: veličina ``PER_1000KCAL_ME``.
    Chyby: :class:`~nutricalc.errors.BasisMismatchError`,
    :class:`~nutricalc.errors.UnitMismatchError` (poměr),
    :class:`~nutricalc.errors.ValidationError` pro ME ≤ 0.
    """
    checked = _require(q, Basis.PER_DAY, "per_day_to_per_1000kcal")
    energy = _positive(me_kcal_per_day, "ME dávky (kcal/den)")
    with calc_context():
        value = checked.value * _THOUSAND / energy
    return Quantity(value, checked.unit, Basis.PER_1000KCAL_ME)


def per_1000kcal_to_per_day(q: Quantity, me_kcal_per_day: Decimal | int | str) -> Quantity:
    """Převede množství na 1000 kcal ME na denní množství.

    ``x_den = x_1000 · ME_den / 1000`` (docs/06 §6.2, §6.4).

    Vstup: veličina ``PER_1000KCAL_ME`` a energie v kcal/den (> 0).
    Výstup: veličina ``PER_DAY``.
    Chyby: :class:`~nutricalc.errors.BasisMismatchError`,
    :class:`~nutricalc.errors.UnitMismatchError` (poměr),
    :class:`~nutricalc.errors.ValidationError` pro energii ≤ 0.
    """
    checked = _require(q, Basis.PER_1000KCAL_ME, "per_1000kcal_to_per_day")
    energy = _positive(me_kcal_per_day, "Energie (kcal/den)")
    with calc_context():
        value = checked.value * energy / _THOUSAND
    return Quantity(value, checked.unit, Basis.PER_DAY)


def per_mj_to_per_1000kcal(q: Quantity) -> Quantity:
    """Převede množství na MJ ME na množství na 1000 kcal ME.

    1000 kcal = 4,184 MJ, tedy ``x_1000 = x_MJ · 4,184`` (docs/03 §3.5).

    Vstup: veličina ``PER_MJ_ME``. Výstup: veličina ``PER_1000KCAL_ME``.
    Chyby: :class:`~nutricalc.errors.BasisMismatchError`,
    :class:`~nutricalc.errors.UnitMismatchError` (poměr).
    """
    checked = _require(q, Basis.PER_MJ_ME, "per_mj_to_per_1000kcal")
    with calc_context():
        value = checked.value * KJ_PER_KCAL
    return Quantity(value, checked.unit, Basis.PER_1000KCAL_ME)


def per_1000kcal_to_per_mj(q: Quantity) -> Quantity:
    """Převede množství na 1000 kcal ME na množství na MJ ME (``x_MJ = x_1000 / 4,184``).

    Vstup: veličina ``PER_1000KCAL_ME``. Výstup: veličina ``PER_MJ_ME``.
    Chyby: :class:`~nutricalc.errors.BasisMismatchError`,
    :class:`~nutricalc.errors.UnitMismatchError` (poměr).
    """
    checked = _require(q, Basis.PER_1000KCAL_ME, "per_1000kcal_to_per_mj")
    with calc_context():
        value = checked.value / KJ_PER_KCAL
    return Quantity(value, checked.unit, Basis.PER_MJ_ME)


def per_day_to_per_kg_metabolic(
    q: Quantity, body_weight_kg: Decimal | int | str, species: Species | str
) -> Quantity:
    """Převede denní množství na množství na kg metabolické hmotnosti.

    ``x = x_den / BW^n``, kde ``n`` je 0,75 pro psa a 0,67 pro kočku
    (:data:`~nutricalc.vocab.METABOLIC_EXPONENT`).

    Vstup: veličina ``PER_DAY``, hmotnost v kg (> 0) a druh.
    Výstup: veličina ``PER_KG_BW075`` (pes) nebo ``PER_KG_BW067`` (kočka).
    Chyby: :class:`~nutricalc.errors.BasisMismatchError`,
    :class:`~nutricalc.errors.UnitMismatchError` (poměr),
    :class:`~nutricalc.errors.InvalidInputError` pro hmotnost ≤ 0 nebo
    neznámý druh.
    """
    checked = _require(q, Basis.PER_DAY, "per_day_to_per_kg_metabolic")
    member = as_member(Species, species, "druh")
    weight = to_decimal(body_weight_kg, name="Hmotnost (kg)")
    if not weight > 0:
        raise InvalidInputError(f"Hmotnost musí být větší než 0 kg (zadáno {weight}).")
    with calc_context():
        value = checked.value / weight ** METABOLIC_EXPONENT[member]
    return Quantity(value, checked.unit, METABOLIC_BASIS[member])
