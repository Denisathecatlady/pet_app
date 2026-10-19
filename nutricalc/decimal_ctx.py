"""Kontext ``Decimal`` výpočetního jádra a striktní převod čísel.

Veškerá aritmetika jádra běží uvnitř :func:`calc_context`: přesnost 28
platných číslic, zaokrouhlení ``ROUND_HALF_EVEN`` a výjimka při neplatné
operaci, dělení nulou a přetečení (docs/05 §5.7, docs/07 §7.2). Kontext se
vytváří vždy znovu z konstant tohoto modulu, takže nezávisí na globálním
kontextu modulu ``decimal`` ani na ``decimal.DefaultContext``.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Final

from nutricalc.errors import InvalidInputError

CALC_PRECISION: Final = 28
"""Počet platných číslic výpočtu (docs/05 §5.7)."""

CALC_ROUNDING: Final = ROUND_HALF_EVEN
"""Zaokrouhlení výpočtu (docs/05 §5.7)."""

_EMIN: Final = -999999
_EMAX: Final = 999999


def _make_context() -> Context:
    # Všechna pole kontextu jsou zadána výslovně: nezadaná pole by se jinak
    # převzala z (měnitelného) decimal.DefaultContext.
    return Context(
        prec=CALC_PRECISION,
        rounding=CALC_ROUNDING,
        Emin=_EMIN,
        Emax=_EMAX,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


CALC_CONTEXT: Final = _make_context()
"""Popis kontextu jádra (pro kontrolu a dokumentaci).

:func:`calc_context` z tohoto objektu nečte; vždy vytvoří nový kontext se
stejným nastavením, takže ani omylem změněný ``CALC_CONTEXT`` výpočet
neovlivní.
"""


@contextmanager
def calc_context() -> Iterator[Context]:
    """Spustí blok v lokálním kontextu jádra.

    Vstup: žádný. Výstup: aktivní kontext (přesnost 28, ``ROUND_HALF_EVEN``,
    pasti ``InvalidOperation``, ``DivisionByZero``, ``Overflow``). Po
    opuštění bloku platí znovu původní kontext volajícího.
    Chyby: výjimky ``decimal`` z pastí kontextu propadnou ven.
    """
    with localcontext(_make_context()) as context:
        yield context


def round_significant(value: Decimal, digits: int) -> Decimal:
    """Zaokrouhlí číslo na ``digits`` platných číslic (``ROUND_HALF_EVEN``).

    Slouží jen tam, kde se odvozená veličina porovnává s přesnou hranicí a
    chyba zaokrouhlení ve 28. číslici by jinak mohla změnit výsledek
    porovnání (např. ``k_skut = DER / BW^n``, docs/06 §6.4).

    Vstup: konečné ``Decimal`` a počet platných číslic (``int``, 1 až
    :data:`CALC_PRECISION`).
    Výstup: ``Decimal`` s nejvýše ``digits`` platnými číslicemi.
    Chyby: ``TypeError`` pro jiný typ čísla než ``Decimal`` nebo jiný typ
    počtu číslic než ``int``;
    :class:`~nutricalc.errors.InvalidInputError` pro nekonečné číslo nebo
    počet číslic mimo rozsah.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"round_significant očekává Decimal, ne {type(value).__name__}.")
    if isinstance(digits, bool) or not isinstance(digits, int):
        raise TypeError(f"Počet platných číslic musí být int, ne {type(digits).__name__}.")
    if not value.is_finite():
        raise InvalidInputError(f"{value} není konečné číslo.")
    if not 1 <= digits <= CALC_PRECISION:
        raise InvalidInputError(
            f"Počet platných číslic musí být 1 až {CALC_PRECISION} (zadáno {digits})."
        )
    context = _make_context()
    context.prec = digits
    return context.plus(value)


_UNSIGNED_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_SIGNED_PATTERN = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def to_decimal(value: Decimal | int | str, *, signed: bool = False, name: str = "číslo") -> Decimal:
    """Převede vstup na konečné ``Decimal`` podle striktního pravidla.

    Vstup:
        ``value`` – ``Decimal``, ``int`` nebo text. Text smí po odstranění
        okolních mezer obsahovat jen číslice ASCII a nejvýše jednu desetinnou
        tečku s číslicemi na obou stranách (``^[0-9]+(\\.[0-9]+)?$``, jako
        ``refdata.decimal_utils.parse_decimal``). Znaménko minus je povolené
        jen s ``signed=True`` (``^-?[0-9]+(\\.[0-9]+)?$``).
        ``signed`` – povolí záporná čísla (u všech typů vstupu). Výchozí je
        ``False``: většina veličin jádra (gramy, hmotnost, obsah živin) je
        nezáporná. Kde je znaménko povolené, uvádí to dokumentace volající
        funkce.
        ``name`` – český název údaje pro chybové zprávy.

    Výstup: ``Decimal`` se zachovanou přesností zápisu (``"0.50"`` →
    ``Decimal("0.50")``); záporná nula se převede na kladnou.

    Chyby:
        ``TypeError`` pro ``float``, ``bool`` a jakýkoli jiný typ (čísla
        ``float`` nejsou v jádře povolena, protože binární reprezentace není
        přesná).
        :class:`~nutricalc.errors.InvalidInputError` pro text v nepovoleném
        tvaru (desetinná čárka, exponent, mezery uvnitř, ``+``), pro ``NaN``
        a nekonečno a pro záporné číslo bez ``signed=True``.
    """
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise TypeError(
            f"{name}: očekává se Decimal, int nebo text, ne {type(value).__name__}. "
            "Čísla typu float jádro nepřijímá; předejte Decimal nebo text (např. '12.5')."
        )
    if isinstance(value, str):
        text = value.strip()
        pattern = _SIGNED_PATTERN if signed else _UNSIGNED_PATTERN
        if not pattern.fullmatch(text):
            sign_hint = "" if signed else " Záporné číslo zde není dovoleno."
            raise InvalidInputError(
                f"{name}: „{value}“ není číslo v povoleném tvaru. Zapište jen číslice a "
                f"desetinnou tečku (např. 12.5), bez čárky, exponentu a mezer.{sign_hint}"
            )
        result = Decimal(text)
    elif isinstance(value, int):
        result = Decimal(value)
    else:
        result = value
        if not result.is_finite():
            raise InvalidInputError(f"{name}: {value} není konečné číslo.")
    if result.is_zero() and result.is_signed():
        result = result.copy_abs()
    if not signed and result < 0:
        raise InvalidInputError(f"{name}: hodnota {result} nesmí být záporná.")
    return result


def to_optional_decimal(
    value: Decimal | int | str | None, *, signed: bool = False, name: str = "číslo"
) -> Decimal | None:
    """Jako :func:`to_decimal`, ale ``None`` projde beze změny.

    Vstup: ``None`` nebo hodnota pro :func:`to_decimal`.
    Výstup: ``None`` nebo ``Decimal``. Chyby: jako :func:`to_decimal`.
    """
    if value is None:
        return None
    return to_decimal(value, signed=signed, name=name)
