"""Striktní parsování čísel a intervalová aritmetika nad ``Decimal``.

Hodnota vytištěná ve standardu s *n* desetinnými místy reprezentuje každé
číslo, které se na *n* míst zaokrouhlí na stejný text. Tolerance kontrol
konzistence se proto odvozuje z vytištěné přesnosti (polovina jednotky
posledního místa), ne z pevného procenta.

Všechny výpočty běží v lokálním kontextu s přesností 28 a ``ROUND_HALF_EVEN``
(:data:`DECIMAL_CONTEXT`; meze intervalů v jeho variantě, kde je každé
zaokrouhlení chybou), takže nezávisí na globálním nastavení modulu
``decimal``. Intervalová aritmetika je přesná: čísla z
:func:`parse_decimal` mají nejvýše :data:`MAX_SIGNIFICANT_DIGITS` platných
číslic, takže meze i jejich násobky se do přesnosti 28 vejdou bez zaokrouhlení.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Final

DECIMAL_CONTEXT = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
"""Kontext pro veškerou aritmetiku balíčku (docs/07 §7.2)."""

_EXACT_CONTEXT = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)
"""Jako :data:`DECIMAL_CONTEXT`, ale zaokrouhlení je chyba (intervalové meze)."""

MAX_SIGNIFICANT_DIGITS: Final = 15
"""Nejvýše platných číslic v jednom čísle přepisu.

Vytištěné hodnoty standardů mají řádově jednotky číslic. Limit drží meze
intervalu (n + 1 číslic) i jejich násobek převodním faktorem (nejvýše
4 číslice, např. 4.184) hluboko pod přesností 28.
"""

Interval = tuple[Decimal, Decimal]
"""Uzavřený interval ``(dolní mez, horní mez)``."""

_DECIMAL_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_THOUSANDS_PATTERN = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?")
_ONE = Decimal(1)


class DecimalParseError(ValueError):
    """Text není nezáporné desetinné číslo v povoleném tvaru."""


def parse_decimal(text: str) -> Decimal:
    """Převede text na ``Decimal`` podle striktního pravidla.

    Vstup: text buňky. Okolní mezery se odstraní, zbytek musí odpovídat
    ``^[0-9]+(\\.[0-9]+)?$`` (jen číslice ASCII a nejvýše jedna desetinná
    tečka s číslicemi na obou stranách).

    Výstup: ``Decimal`` se zachovanou vytištěnou přesností
    (``"0.50"`` → ``Decimal("0.50")``).

    Chyby: :class:`DecimalParseError` (podtřída ``ValueError``) s českou
    zprávou pro prázdný text, desetinnou čárku, znaménko, exponent,
    oddělovač tisíců (pro tvar ``1,000`` se zvláštní radou) nebo mezery
    uvnitř čísla a pro číslo s více než :data:`MAX_SIGNIFICANT_DIGITS`
    platnými číslicemi.
    """
    stripped = text.strip()
    if _THOUSANDS_PATTERN.fullmatch(stripped):
        raise DecimalParseError(
            f"„{text}“ vypadá jako číslo s anglickým oddělovačem tisíců. Čárku vynechte "
            "(1,000 → 1000), nikdy ji nenahrazujte tečkou, a ponechte jen číslice a "
            "desetinnou tečku přesně podle originálu."
        )
    if not _DECIMAL_PATTERN.fullmatch(stripped):
        raise DecimalParseError(
            f"„{text}“ není číslo v povoleném tvaru. Zapište jen číslice a "
            "desetinnou tečku přesně podle originálu (např. 12.5), bez čárky, "
            "znaménka, exponentu, oddělovače tisíců a mezer uvnitř čísla."
        )
    value = Decimal(stripped)
    if len(value.as_tuple().digits) > MAX_SIGNIFICANT_DIGITS:
        raise DecimalParseError(
            f"„{text}“ má víc než {MAX_SIGNIFICANT_DIGITS} platných číslic. Ověřte buňku "
            "v originále a zapište číslo přesně tak, jak je vytištěno."
        )
    return value


def half_ulp(value: Decimal) -> Decimal:
    """Vrátí polovinu jednotky posledního vytištěného místa.

    Vstup: konečné ``Decimal`` (typicky z :func:`parse_decimal`).
    Výstup: ``0.5 × 10**exponent`` (``1.25`` → ``0.005``, ``500`` → ``0.5``,
    ``0.50`` → ``0.005``).
    Chyby: ``ValueError`` pro NaN nebo nekonečno.
    """
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("Polovinu posledního místa lze určit jen u konečného čísla.")
    return Decimal((0, (5,), exponent - 1))


@contextmanager
def _exact_arithmetic() -> Iterator[None]:
    with localcontext(_EXACT_CONTEXT):
        try:
            yield
        except Inexact as exc:
            raise ValueError(
                "Interval nelze spočítat přesně: číslo má příliš mnoho platných číslic."
            ) from exc


def printed_interval(value: Decimal) -> Interval:
    """Vrátí interval všech čísel, která se zaokrouhlí na vytištěnou hodnotu.

    Vstup: konečné ``Decimal``. Výstup: ``(value − half_ulp, value + half_ulp)``,
    spočítané přesně.
    Chyby: jako :func:`half_ulp`; ``ValueError`` také tehdy, když by se meze
    musely zaokrouhlit (víc platných číslic, než pojme přesnost 28).
    """
    margin = half_ulp(value)
    with _exact_arithmetic():
        return (value - margin, value + margin)


def scaled_interval(value: Decimal, factor: Decimal) -> Interval:
    """Vrátí vytištěný interval hodnoty vynásobený kladným faktorem.

    Vstup: konečné ``Decimal`` a faktor ``> 0``.
    Výstup: ``(dolní × faktor, horní × faktor)``, spočítané přesně.
    Chyby: ``ValueError``, pokud faktor není kladný nebo by se součin musel
    zaokrouhlit (viz :func:`printed_interval`).
    """
    if not factor > 0:
        raise ValueError("Převodní faktor musí být kladný.")
    low, high = printed_interval(value)
    with _exact_arithmetic():
        return (low * factor, high * factor)


def intervals_overlap(first: Interval, second: Interval) -> bool:
    """Zjistí, zda se dva uzavřené intervaly překrývají (dotyk se počítá).

    Vstup: dva intervaly ``(dolní, horní)``. Výstup: ``True`` při překryvu.
    """
    return first[0] <= second[1] and second[0] <= first[1]


def consistent_with_factor(
    a: Decimal, b: Decimal, factor: Decimal, divisor: Decimal = _ONE
) -> bool:
    """Zjistí, zda vytištěné ``a`` může odpovídat ``b × factor / divisor``.

    Vstup: dvě vytištěné hodnoty, kladný faktor (např. ``2.5`` pro převod
    „na 100 g sušiny“ → „na 1 000 kcal ME“) a volitelný kladný dělitel.

    Výstup: ``True``, když se vytištěný interval ``a`` překrývá s
    ``factor / divisor ×`` vytištěný interval ``b`` (meze včetně). Porovnává
    se přesně ``a × divisor`` s ``b × factor``, takže neukončené podíly
    (např. 110/95 nebo 2,5/4,184) se nezaokrouhlují. Bez dělitele jde přímo
    o překryv intervalu ``a`` s ``factor ×`` interval ``b``.

    Chyby: ``ValueError``, pokud faktor nebo dělitel není kladný, nebo
    pokud by se meze musely zaokrouhlit (viz :func:`scaled_interval`).
    """
    return intervals_overlap(scaled_interval(a, divisor), scaled_interval(b, factor))
