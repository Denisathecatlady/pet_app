"""Striktní parsování čísel, polovina posledního místa a překryv intervalů.

Čísla jsou syntetická.
"""

from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from refdata.decimal_utils import (
    MAX_SIGNIFICANT_DIGITS,
    DecimalParseError,
    consistent_with_factor,
    half_ulp,
    intervals_overlap,
    parse_decimal,
    printed_interval,
    scaled_interval,
)

D = Decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", "0"),
        ("12", "12"),
        ("1.25", "1.25"),
        ("0.50", "0.50"),
        (" 1.5 ", "1.5"),
        ("\t2.0\n", "2.0"),
        ("01.5", "1.5"),
        ("500", "500"),
    ],
)
def test_parse_decimal_accepts_plain_numbers(text: str, expected: str) -> None:
    parsed = parse_decimal(text)
    assert parsed == D(expected)
    assert str(parsed) == expected  # vytištěná přesnost zůstává zachována


@pytest.mark.parametrize(
    "text",
    [
        "1,25",
        "-1",
        "+1",
        "1e3",
        "1E3",
        "1.",
        ".5",
        "",
        "   ",
        "1 000",
        "1 000.5",
        "1,000.5",
        "1.2.3",
        "1_000",
        "NaN",
        "Infinity",
        "0x10",
        "١",  # arabsko-indická číslice 1 (není ASCII)
        "1 000",  # nezlomitelná mezera uvnitř čísla
    ],
)
def test_parse_decimal_rejects_everything_else(text: str) -> None:
    with pytest.raises(DecimalParseError) as excinfo:
        parse_decimal(text)
    assert isinstance(excinfo.value, ValueError)
    assert "desetinnou tečku" in str(excinfo.value)


@pytest.mark.parametrize("text", ["1,000", "12,500", "1,000,000", "1,000.5"])
def test_parse_decimal_explains_english_thousands_separator(text: str) -> None:
    with pytest.raises(DecimalParseError) as excinfo:
        parse_decimal(text)
    message = str(excinfo.value)
    assert "oddělovačem tisíců" in message and "1,000 → 1000" in message
    assert "desetinnou tečku" in message


def test_decimal_comma_gets_the_general_message() -> None:
    with pytest.raises(DecimalParseError) as excinfo:
        parse_decimal("1,25")
    assert "oddělovačem tisíců" not in str(excinfo.value)


def test_parse_decimal_limits_significant_digits() -> None:
    assert MAX_SIGNIFICANT_DIGITS == 15
    assert parse_decimal("123456789012345") == D("123456789012345")
    assert parse_decimal("0.000000000000001") == D("1E-15")  # úvodní nuly nejsou platné číslice
    assert parse_decimal("000000000000000000001.5") == D("1.5")
    for text in ("1234567890123456", "1.000000000000000", "100000000000000000000"):
        with pytest.raises(DecimalParseError, match="platných číslic"):
            parse_decimal(text)


def test_parse_error_is_dedicated_value_error_subclass() -> None:
    assert issubclass(DecimalParseError, ValueError)
    assert DecimalParseError is not ValueError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.25", "0.005"),
        ("500", "0.5"),
        ("0.50", "0.005"),
        ("7", "0.5"),
        ("0.1", "0.05"),
        ("10.000", "0.0005"),
    ],
)
def test_half_ulp(value: str, expected: str) -> None:
    assert half_ulp(D(value)) == D(expected)


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
def test_half_ulp_rejects_non_finite(value: str) -> None:
    with pytest.raises(ValueError):
        half_ulp(D(value))


def test_printed_interval() -> None:
    assert printed_interval(D("1.25")) == (D("1.245"), D("1.255"))
    assert printed_interval(D("500")) == (D("499.5"), D("500.5"))


def test_interval_bounds_are_never_rounded_silently() -> None:
    # 29 platných číslic: meze by se v přesnosti 28 slily do jednoho bodu
    with pytest.raises(ValueError, match="přesně"):
        printed_interval(D("1.0000000000000000000000000000"))
    with pytest.raises(ValueError, match="přesně"):
        scaled_interval(D("1.5"), D("110") / D("95"))  # neukončený podíl jako faktor


def test_scaled_interval_and_non_positive_factor() -> None:
    assert scaled_interval(D("0.50"), D("2.5")) == (D("1.2375"), D("1.2625"))
    for factor in (D("0"), D("-1")):
        with pytest.raises(ValueError):
            scaled_interval(D("1"), factor)


def test_intervals_overlap_closed_bounds() -> None:
    assert intervals_overlap((D("1"), D("2")), (D("2"), D("3")))
    assert intervals_overlap((D("2"), D("3")), (D("1"), D("2")))
    assert not intervals_overlap((D("1"), D("2")), (D("2.01"), D("3")))


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        # a = 1.0 → [0.95, 1.05]; b × 2:
        ("1.0", "0.53", True),  # [1.05, 1.07]: dotyk na horní mezi a
        ("1.0", "0.54", False),  # [1.07, 1.09]
        ("1.0", "0.47", True),  # [0.93, 0.95]: dotyk na dolní mezi a
        ("1.0", "0.46", False),  # [0.91, 0.93]
        ("1.0", "0.5", True),  # [0.9, 1.1]: překryv uvnitř
    ],
)
def test_consistent_with_factor_exact_boundaries(a: str, b: str, expected: bool) -> None:
    assert consistent_with_factor(D(a), D(b), D("2")) is expected


def test_consistent_with_factor_documented_calcium_example() -> None:
    # docs/03 §3.3: 1.25 g Ca / 1000 kcal ME ÷ 2.5 = 0.50 g Ca / 100 g sušiny.
    assert consistent_with_factor(D("1.25"), D("0.50"), D("2.5"))
    assert not consistent_with_factor(D("1.25"), D("0.60"), D("2.5"))


def test_consistent_with_factor_divisor_is_exact() -> None:
    # hodnota(95) ≈ hodnota(110) × 110 / 95 (syntetická čísla)
    assert consistent_with_factor(D("11.6"), D("10.0"), D("110"), D("95"))
    assert not consistent_with_factor(D("10.0"), D("11.6"), D("110"), D("95"))
    # a × divisor se porovnává s b × factor bez zaokrouhlení podílu 1/7:
    # [1.95, 2.05] × 7 = [13.65, 14.35] proti [14.35, 14.45] → dotyk na mezi.
    assert consistent_with_factor(D("2.0"), D("14.4"), D("1"), D("7"))
    assert not consistent_with_factor(D("2.0"), D("14.5"), D("1"), D("7"))


def test_consistent_with_factor_rejects_non_positive_factor_or_divisor() -> None:
    with pytest.raises(ValueError):
        consistent_with_factor(D("1"), D("1"), D("0"))
    with pytest.raises(ValueError):
        consistent_with_factor(D("1"), D("1"), D("1"), D("0"))


def _context_sensitive_results() -> tuple[object, ...]:
    return (
        consistent_with_factor(D("1.00"), D("0.5030"), D("2")),
        consistent_with_factor(D("1.0"), D("0.53"), D("2")),
        consistent_with_factor(D("1.0"), D("0.54"), D("2")),
        consistent_with_factor(D("1.25"), D("0.50"), D("2.5")),
        consistent_with_factor(D("1.25"), D("0.60"), D("2.5")),
        consistent_with_factor(D("11.6"), D("10.0"), D("110"), D("95")),
        consistent_with_factor(D("2.0"), D("14.4"), D("1"), D("7")),
        printed_interval(D("1.25")),
        scaled_interval(D("0.50"), D("2.5")),
    )


def test_results_do_not_depend_on_global_decimal_context() -> None:
    expected = _context_sensitive_results()
    # [0.995, 1.005] proti [1.0059, 1.0061]: s přesností 2 a ROUND_DOWN by se meze překryly
    assert expected[:5] == (False, True, False, True, False)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        assert _context_sensitive_results() == expected
