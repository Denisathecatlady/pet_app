"""Upozornění (příznaky) výsledků výpočtu.

Upozornění vysvětlují, jak jádro naložilo se vstupy (např. dopočet BNLV,
chybějící vláknina), a nesou úroveň :class:`~nutricalc.vocab.WarningLevel`.
O stavu výsledku ale rozhodují pole výsledku (stav, úplnost, ``None`` místo
čísla), nikdy jen přítomnost upozornění.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from nutricalc.errors import ValidationError
from nutricalc.vocab import WARNING_LEVEL_RANK, WarningLevel, as_member, require_text

_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")


def check_code(code: object, label: str) -> str:
    """Ověří stabilní kód (upozornění, pravidla, důvodu brány): velká písmena, číslice a _.

    Vstup: hodnota a český název údaje pro zprávu. Výstup: stejný text.
    Chyby: ``TypeError`` pro jiný typ než text;
    :class:`~nutricalc.errors.ValidationError` pro prázdný nebo neplatný kód.
    """
    text = require_text(code, label)
    if not _CODE_PATTERN.fullmatch(text):
        raise ValidationError(
            f"{label} „{text}“ musí obsahovat jen velká písmena, číslice a _ (začíná písmenem)."
        )
    return text


@dataclass(frozen=True)
class Flag:
    """Jedno upozornění.

    ``level``: úroveň (:class:`~nutricalc.vocab.WarningLevel`).
    ``code``: stabilní kód velkými písmeny (např. ``BCS_MISSING``).
    ``message_cs``: česká zpráva pro uživatele.
    ``subject``: čeho se upozornění týká (např. kód suroviny), jinak ``None``.

    Chyby: ``TypeError`` pro jiný typ než text;
    :class:`~nutricalc.errors.ValidationError` pro neplatný kód nebo prázdnou zprávu.
    """

    level: WarningLevel
    code: str
    message_cs: str
    subject: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", as_member(WarningLevel, self.level, "úroveň upozornění"))
        check_code(self.code, "Kód upozornění")
        require_text(self.message_cs, f"Zpráva upozornění {self.code}")
        if self.subject is not None:
            require_text(self.subject, f"Předmět upozornění {self.code}")


def _sort_key(flag: Flag) -> tuple[int, str, str, str]:
    return (-WARNING_LEVEL_RANK[flag.level], flag.code, flag.subject or "", flag.message_cs)


def sorted_flags(flags: Iterable[Flag]) -> tuple[Flag, ...]:
    """Odstraní přesné duplicity a seřadí upozornění deterministicky.

    Vstup: upozornění v libovolném pořadí. Výstup: n-tice od nejzávažnější
    úrovně, dále podle kódu, předmětu a zprávy.
    """
    return tuple(sorted(dict.fromkeys(flags), key=_sort_key))
