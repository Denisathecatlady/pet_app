"""Kontext Decimal jádra, striktní převod čísel a hierarchie výjimek."""

from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    getcontext,
    localcontext,
)

import pytest

import nutricalc
from nutricalc import errors
from nutricalc.decimal_ctx import (
    CALC_CONTEXT,
    CALC_PRECISION,
    calc_context,
    to_decimal,
    to_optional_decimal,
)


def test_versions() -> None:
    assert nutricalc.__version__ == "0.1.0"
    assert nutricalc.ENGINE_VERSION == nutricalc.__version__


# --- kontext -------------------------------------------------------------------


def test_calc_context_settings() -> None:
    assert CALC_PRECISION == 28
    assert CALC_CONTEXT.prec == 28
    assert CALC_CONTEXT.rounding == ROUND_HALF_EVEN
    for trap in (InvalidOperation, DivisionByZero, Overflow):
        assert CALC_CONTEXT.traps[trap]
    with calc_context() as context:
        assert context.prec == 28
        assert context.rounding == ROUND_HALF_EVEN
        assert all(context.traps[trap] for trap in (InvalidOperation, DivisionByZero, Overflow))


def test_calc_context_ignores_and_restores_global_context() -> None:
    with localcontext() as outer:
        outer.prec = 3
        outer.rounding = ROUND_DOWN
        with calc_context():
            assert getcontext().prec == 28
            assert Decimal(1) / Decimal(3) == Decimal("0.3333333333333333333333333333")
        assert getcontext().prec == 3
        assert getcontext().rounding == ROUND_DOWN


def test_calc_context_does_not_read_mutable_module_object() -> None:
    original = CALC_CONTEXT.prec
    try:
        CALC_CONTEXT.prec = 5
        with calc_context() as context:
            assert context.prec == 28
    finally:
        CALC_CONTEXT.prec = original


@pytest.mark.parametrize(
    ("trap", "operation"),
    [
        (DivisionByZero, lambda: Decimal(1) / Decimal(0)),
        (InvalidOperation, lambda: Decimal(-1) ** Decimal("0.5")),
        (Overflow, lambda: Decimal("9e999999") * 10),
    ],
)
def test_calc_context_traps(trap: type[Exception], operation: object) -> None:
    with calc_context(), pytest.raises(trap):
        operation()  # type: ignore[operator]


# --- to_decimal ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1.25"), "1.25"),
        (7, "7"),
        ("12.5", "12.5"),
        ("0.50", "0.50"),
        ("  3  ", "3"),
        ("0", "0"),
        (Decimal("-0"), "0"),
    ],
)
def test_to_decimal_accepts_decimal_int_and_text(value: Decimal | int | str, expected: str) -> None:
    result = to_decimal(value)
    assert isinstance(result, Decimal)
    assert str(result) == expected


def test_to_decimal_keeps_printed_precision() -> None:
    assert to_decimal("0.50").as_tuple().exponent == -2


@pytest.mark.parametrize("value", [1.5, 0.0, True, False, None, [1], b"1", complex(1, 0)])
def test_to_decimal_rejects_float_bool_and_other_types(value: object) -> None:
    with pytest.raises(TypeError):
        to_decimal(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    ["1,5", "1e3", "+1", "-1", "", " ", "1.", ".5", "1 000", "NaN", "Infinity", "1.2.3", "０"],
)
def test_to_decimal_rejects_text_in_wrong_form(text: str) -> None:
    with pytest.raises(errors.InvalidInputError):
        to_decimal(text)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_to_decimal_rejects_non_finite(value: Decimal) -> None:
    with pytest.raises(errors.InvalidInputError):
        to_decimal(value, signed=True)


@pytest.mark.parametrize("value", [Decimal("-0.1"), -1, "-2"])
def test_sign_only_where_allowed(value: Decimal | int | str) -> None:
    with pytest.raises(errors.InvalidInputError, match="(?i)záporn"):
        to_decimal(value)
    assert to_decimal(value, signed=True) < 0


def test_signed_text_pattern() -> None:
    assert to_decimal("-1.5", signed=True) == Decimal("-1.5")
    for text in ("--1", "+1", "- 1"):
        with pytest.raises(errors.InvalidInputError):
            to_decimal(text, signed=True)


def test_to_decimal_message_names_the_field() -> None:
    with pytest.raises(TypeError, match="Hmotnost"):
        to_decimal(1.5, name="Hmotnost")  # type: ignore[arg-type]


def test_to_optional_decimal() -> None:
    assert to_optional_decimal(None) is None
    assert to_optional_decimal("2") == Decimal(2)
    with pytest.raises(TypeError):
        to_optional_decimal(2.0)  # type: ignore[arg-type]


# --- výjimky -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "parent"),
    [
        (errors.ValidationError, errors.NutricalcError),
        (errors.InvalidInputError, errors.ValidationError),
        (errors.DuplicateItemError, errors.ValidationError),
        (errors.UnitMismatchError, errors.NutricalcError),
        (errors.BasisMismatchError, errors.NutricalcError),
        (errors.MissingDataError, errors.NutricalcError),
        (errors.SpeciesMismatchError, errors.NutricalcError),
        (errors.UnsupportedMethodError, errors.NutricalcError),
        (errors.NutricalcError, Exception),
    ],
)
def test_error_hierarchy(error: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(error, parent)


def test_mismatch_errors_are_distinct() -> None:
    assert not issubclass(errors.UnitMismatchError, errors.BasisMismatchError)
    assert not issubclass(errors.BasisMismatchError, errors.UnitMismatchError)
    assert not issubclass(errors.MissingDataError, errors.ValidationError)


# --- zaokrouhlení na platné číslice --------------------------------------------------------


def test_round_significant() -> None:
    from nutricalc.decimal_ctx import round_significant

    assert round_significant(Decimal("109.9999999999999999999999999"), 20) == Decimal(110)
    assert round_significant(Decimal("125.0000000000000000000000001"), 20) == Decimal(125)
    assert round_significant(Decimal("1.25"), 2) == Decimal("1.2")  # ROUND_HALF_EVEN
    assert round_significant(Decimal("1.35"), 2) == Decimal("1.4")
    assert round_significant(Decimal(0), 5) == 0


def test_round_significant_ignores_global_context() -> None:
    from nutricalc.decimal_ctx import round_significant

    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        assert round_significant(Decimal("1.2345"), 4) == Decimal("1.234")
        assert round_significant(Decimal("1.2355"), 4) == Decimal("1.236")


def test_round_significant_rejects_invalid_input() -> None:
    from nutricalc.decimal_ctx import round_significant

    with pytest.raises(TypeError):
        round_significant(1.5, 3)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        round_significant(Decimal(1), True)
    with pytest.raises(errors.InvalidInputError):
        round_significant(Decimal("NaN"), 3)
    for digits in (0, CALC_PRECISION + 1):
        with pytest.raises(errors.InvalidInputError):
            round_significant(Decimal(1), digits)
