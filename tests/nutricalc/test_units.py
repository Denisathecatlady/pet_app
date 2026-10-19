"""Veličiny s jednotkou a bází a explicitní převody (docs/06 §6.2, docs/11 §11.2).

Čísla jsou syntetická, kromě příkladů z docs/06 §6.10 (3,1 g P za den při
506,688 kcal) a docs/05 §5.8 (pes 20 kg, k = 95).
"""

import operator
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from nutricalc.errors import (
    BasisMismatchError,
    InvalidInputError,
    MissingDataError,
    UnitMismatchError,
    ValidationError,
)
from nutricalc.units import (
    Quantity,
    as_fed_to_dm,
    per_100g_as_fed_to_per_day,
    per_1000kcal_to_per_day,
    per_1000kcal_to_per_mj,
    per_day_to_per_1000kcal,
    per_day_to_per_kg_metabolic,
    per_mj_to_per_1000kcal,
)
from nutricalc.vocab import Basis, Species, Unit

AF = Basis.PER_100G_AS_FED
DAY = Basis.PER_DAY
K1000 = Basis.PER_1000KCAL_ME


BINARY_OPERATIONS = [
    pytest.param(operator.add, id="+"),
    pytest.param(operator.sub, id="-"),
    pytest.param(operator.lt, id="<"),
    pytest.param(operator.le, id="<="),
    pytest.param(operator.gt, id=">"),
    pytest.param(operator.ge, id=">="),
]
Operation = Callable[[object, object], object]


def q(value: str, unit: Unit = Unit.G, basis: Basis = DAY) -> Quantity:
    return Quantity(Decimal(value), unit, basis)


# --- konstrukce --------------------------------------------------------------------


def test_quantity_construction_and_coercion() -> None:
    quantity = Quantity("1.50", "mg", "PER_DAY")  # type: ignore[arg-type]
    assert quantity == Quantity(Decimal("1.50"), Unit.MG, DAY)
    assert quantity.unit is Unit.MG and quantity.basis is DAY
    # znaménko je u Quantity povolené (rozdíl veličin může být záporný)
    assert Quantity(Decimal(-2), Unit.G, DAY).value == Decimal(-2)
    assert Quantity("-2", Unit.G, DAY) == Quantity(Decimal(-2), Unit.G, DAY)  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        quantity.value = Decimal(1)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ((1.5, Unit.G, DAY), TypeError),
        ((True, Unit.G, DAY), TypeError),
        ((Decimal("NaN"), Unit.G, DAY), InvalidInputError),
        ((Decimal(1), "IU", DAY), InvalidInputError),
        ((Decimal(1), Unit.G, "PER_KG"), InvalidInputError),
        ((Decimal(1), 1, DAY), TypeError),
    ],
)
def test_quantity_rejects_invalid_fields(args: tuple[object, ...], error: type[Exception]) -> None:
    with pytest.raises(error):
        Quantity(*args)  # type: ignore[arg-type]


# --- sčítání, odčítání, porovnání ----------------------------------------------------


def test_add_and_subtract_same_unit_and_basis() -> None:
    assert q("1.5") + q("2.25") == q("3.75")
    assert q("1.5") - q("2.25") == q("-0.75")


@pytest.mark.parametrize("operation", BINARY_OPERATIONS)
@pytest.mark.parametrize(
    ("other", "error"),
    [
        (Quantity(Decimal(1), Unit.MG, DAY), UnitMismatchError),
        (Quantity(Decimal(1), Unit.G, K1000), BasisMismatchError),
        (Quantity(Decimal(1), Unit.G, AF), BasisMismatchError),
        (Quantity(Decimal(1), Unit.G, Basis.PER_100G_DM), BasisMismatchError),
        (Quantity(Decimal(1), Unit.MG, K1000), UnitMismatchError),  # jednotka se hlásí první
    ],
)
def test_mixed_unit_or_basis_raises(
    operation: Operation, other: Quantity, error: type[Exception]
) -> None:
    with pytest.raises(error):
        operation(q("1"), other)


@pytest.mark.parametrize("operation", BINARY_OPERATIONS)
@pytest.mark.parametrize("other", [Decimal(1), 1, "1"])
def test_operations_with_non_quantity_raise_type_error(operation: Operation, other: object) -> None:
    with pytest.raises(TypeError):
        operation(q("1"), other)


def test_ordering_same_unit_and_basis() -> None:
    small, large = q("1.0"), q("1.5")
    assert small < large and small <= large and large > small and large >= small
    assert q("1.0") <= q("1.00") and q("1.0") >= q("1.00")
    assert not small > large


def test_equality_never_converts() -> None:
    assert q("1") != Quantity(Decimal(1000), Unit.MG, DAY)
    assert q("1") != Quantity(Decimal(1), Unit.G, K1000)
    assert q("1.0") == q("1")
    assert hash(q("1.0")) == hash(q("1"))


# --- skalár ------------------------------------------------------------------------------


def test_multiply_and_divide_by_decimal() -> None:
    assert q("1.5") * Decimal(2) == q("3.0")
    assert Decimal(2) * q("1.5") == q("3.0")
    assert q("3") / Decimal(4) == q("0.75")


@pytest.mark.parametrize("scalar", [2, 1.5, "2", True, q("2")])
def test_scalar_must_be_decimal(scalar: object) -> None:
    with pytest.raises(TypeError):
        q("1") * scalar  # type: ignore[operator]
    with pytest.raises(TypeError):
        q("1") / scalar  # type: ignore[operator]


def test_scalar_rejects_zero_divisor_and_non_finite() -> None:
    with pytest.raises(InvalidInputError):
        q("1") / Decimal(0)
    with pytest.raises(InvalidInputError):
        q("1") * Decimal("NaN")
    with pytest.raises(TypeError):
        Decimal(1) / q("1")  # type: ignore[operator]


# --- převod jednotky ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        ("1.5", Unit.G, Unit.MG, "1500"),
        ("1.5", Unit.G, Unit.UG, "1500000"),
        ("250", Unit.MG, Unit.G, "0.25"),
        ("250", Unit.UG, Unit.MG, "0.25"),
        ("7", Unit.UG, Unit.G, "0.000007"),
        ("1", Unit.KCAL, Unit.KJ, "4.184"),
        ("4.184", Unit.KJ, Unit.KCAL, "1"),
        ("2", Unit.RATIO, Unit.RATIO, "2"),
    ],
)
def test_to_unit(value: str, source: Unit, target: Unit, expected: str) -> None:
    converted = Quantity(Decimal(value), source, K1000).to_unit(target)
    assert converted == Quantity(Decimal(expected), target, K1000)


def test_to_unit_same_unit_returns_same_quantity_and_round_trips() -> None:
    quantity = q("1.234")
    assert quantity.to_unit(Unit.G) is quantity
    assert quantity.to_unit(Unit.UG).to_unit(Unit.MG).to_unit(Unit.G) == quantity
    energy = Quantity(Decimal("506.688"), Unit.KCAL, DAY)
    back = energy.to_unit(Unit.KJ).to_unit(Unit.KCAL)
    assert abs(back.value - energy.value) < Decimal("1e-24")
    assert quantity.to_unit("mg") == q("1234", Unit.MG)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (Unit.G, Unit.KCAL),
        (Unit.KJ, Unit.MG),
        (Unit.RATIO, Unit.G),
        (Unit.G, Unit.RATIO),
        (Unit.KCAL, Unit.RATIO),
    ],
)
def test_to_unit_rejects_other_conversions(source: Unit, target: Unit) -> None:
    with pytest.raises(UnitMismatchError):
        Quantity(Decimal(1), source, DAY).to_unit(target)


# --- převody bází ------------------------------------------------------------------------------


def test_as_fed_to_dm_documented_example() -> None:
    # docs/11 §11.2: 25 g/100 g při 75 % vody = 100 g/100 g sušiny
    result = as_fed_to_dm(q("25", basis=AF), Decimal(75))
    assert result == Quantity(Decimal(100), Unit.G, Basis.PER_100G_DM)
    assert as_fed_to_dm(q("25", Unit.MG, AF), Decimal(0)) == Quantity(
        Decimal(25), Unit.MG, Basis.PER_100G_DM
    )


def test_as_fed_to_dm_errors() -> None:
    with pytest.raises(MissingDataError):
        as_fed_to_dm(q("25", basis=AF), None)
    for water in (Decimal(100), Decimal("100.5"), Decimal("-0.1")):
        with pytest.raises(ValidationError):
            as_fed_to_dm(q("25", basis=AF), water)
    with pytest.raises(TypeError):
        as_fed_to_dm(q("25", basis=AF), 75.0)  # type: ignore[arg-type]
    with pytest.raises(BasisMismatchError):
        as_fed_to_dm(q("25", basis=DAY), Decimal(75))
    with pytest.raises(UnitMismatchError):
        as_fed_to_dm(q("2", Unit.RATIO, AF), Decimal(75))
    with pytest.raises(TypeError):
        as_fed_to_dm(Decimal(25), Decimal(75))  # type: ignore[arg-type]


def test_per_100g_as_fed_to_per_day() -> None:
    result = per_100g_as_fed_to_per_day(q("0.200", basis=AF), Decimal(300))
    assert result == q("0.6")
    assert result.basis is DAY
    for grams in (Decimal(0), Decimal(-1)):
        with pytest.raises(ValidationError):
            per_100g_as_fed_to_per_day(q("1", basis=AF), grams)
    with pytest.raises(BasisMismatchError):
        per_100g_as_fed_to_per_day(q("1", basis=Basis.PER_100G_DM), Decimal(100))


def test_per_day_and_per_1000kcal_documented_example() -> None:
    # docs/06 §6.10: 3,1 g P/den při 506,688 kcal = 6,118 g / 1000 kcal
    per_1000 = per_day_to_per_1000kcal(q("3.1"), Decimal("506.688"))
    assert per_1000.basis is K1000
    assert abs(per_1000.value - Decimal("6.118163445749652646")) < Decimal("1e-15")
    back = per_1000kcal_to_per_day(per_1000, Decimal("506.688"))
    assert abs(back.value - Decimal("3.1")) < Decimal("1e-24")
    assert per_1000kcal_to_per_day(q("2", basis=K1000), Decimal(500)) == q("1")


@pytest.mark.parametrize("energy", [Decimal(0), Decimal("-1"), "0"])
def test_per_1000kcal_conversions_require_positive_energy(energy: object) -> None:
    with pytest.raises(ValidationError):
        per_day_to_per_1000kcal(q("1"), energy)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        per_1000kcal_to_per_day(q("1", basis=K1000), energy)  # type: ignore[arg-type]


def test_per_1000kcal_conversions_check_basis() -> None:
    with pytest.raises(BasisMismatchError):
        per_day_to_per_1000kcal(q("1", basis=AF), Decimal(500))
    with pytest.raises(BasisMismatchError):
        per_1000kcal_to_per_day(q("1"), Decimal(500))
    with pytest.raises(UnitMismatchError):
        per_day_to_per_1000kcal(q("1", Unit.RATIO), Decimal(500))


def test_mj_conversions() -> None:
    # 1000 kcal = 4,184 MJ: 2 na MJ = 8,368 na 1000 kcal (docs/03 §3.5)
    per_mj = q("2", basis=Basis.PER_MJ_ME)
    per_1000 = per_mj_to_per_1000kcal(per_mj)
    assert per_1000 == q("8.368", basis=K1000)
    assert per_1000kcal_to_per_mj(per_1000) == per_mj
    with pytest.raises(BasisMismatchError):
        per_mj_to_per_1000kcal(q("2", basis=K1000))
    with pytest.raises(BasisMismatchError):
        per_1000kcal_to_per_mj(q("2", basis=Basis.PER_MJ_ME))


def test_per_day_to_per_kg_metabolic() -> None:
    # docs/05 §5.8: pes 20 kg, k = 95 → 898,4545285530… kcal/den
    daily = Quantity(Decimal("898.4545285530170226366113139"), Unit.KCAL, DAY)
    dog = per_day_to_per_kg_metabolic(daily, Decimal(20), Species.DOG)
    assert dog.basis is Basis.PER_KG_BW075
    assert abs(dog.value - Decimal(95)) < Decimal("1e-24")
    cat = per_day_to_per_kg_metabolic(q("100"), Decimal(1), "CAT")  # type: ignore[arg-type]
    assert cat == Quantity(Decimal(100), Unit.G, Basis.PER_KG_BW067)


def test_per_day_to_per_kg_metabolic_errors() -> None:
    for weight in (Decimal(0), Decimal(-5)):
        with pytest.raises(InvalidInputError):
            per_day_to_per_kg_metabolic(q("1"), weight, Species.DOG)
    with pytest.raises(BasisMismatchError):
        per_day_to_per_kg_metabolic(q("1", basis=K1000), Decimal(10), Species.DOG)
    with pytest.raises(InvalidInputError):
        per_day_to_per_kg_metabolic(q("1"), Decimal(10), "HORSE")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        per_day_to_per_kg_metabolic(q("1"), 10.0, Species.DOG)  # type: ignore[arg-type]


def test_typical_mixups_are_impossible() -> None:
    # docs/11 §11.2: smíchání „na 100 g“ a „na 1000 kcal“, sušiny a původní hmoty
    with pytest.raises(BasisMismatchError):
        _ = q("1", basis=AF) + q("1", basis=K1000)
    with pytest.raises(BasisMismatchError):
        _ = q("1", basis=AF) < q("1", basis=Basis.PER_100G_DM)
    with pytest.raises(UnitMismatchError):
        _ = q("1", Unit.MG) + q("1", Unit.UG)
