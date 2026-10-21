"""How the library shows evidence and verification levels (docs/08 §8.1, §8.4).

A verification level is always icon + text + colour, never colour alone. The short names
here are labels for the interface; the exact meanings from docs/zdroje.md are the labels
of ``models.VerificationLevel`` and ``models.EvidenceLevel`` and appear in the legend.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True)
class VerificationStyle:
    css: str  # suffix of the CSS class ``status--verif-<css>``
    icon: str
    name: str  # short name next to the icon


VERIFICATION_STYLES: Final = MappingProxyType(
    {
        "P": VerificationStyle("p", "✓", "P – ověřeno v primárním zdroji"),
        "A": VerificationStyle("a", "◆", "A – ověřen abstrakt nebo souhrn"),
        "S": VerificationStyle("s", "◇", "S – ověřeno jen přes sekundární zdroj"),
        "B": VerificationStyle("b", "○", "B – ověřeny jen bibliografické údaje"),
        "NONE": VerificationStyle("none", "?", "Neověřeno"),
    }
)

EVIDENCE_NAMES: Final = MappingProxyType(
    {
        "L1": "doporučení instituce",
        "L2": "přehled nebo metaanalýza",
        "L3": "původní studie",
        "L4": "kazuistika",
        "L5": "databáze potravin",
        "L6": "sekundární zdroj",
    }
)


def verification_style(level: str) -> VerificationStyle:
    """Return the style of a verification level (``B``, ``A``, ``P``, ``S`` or ``NONE``).

    Raises:
        ValueError: unknown level. An unknown level must never render as a neutral badge.
    """
    try:
        return VERIFICATION_STYLES[level]
    except KeyError:
        raise ValueError(f"Unknown verification level: {level!r}") from None


def evidence_name(level: str) -> str:
    """Return the short name of an evidence level (``L1`` … ``L6``).

    Raises:
        ValueError: unknown level.
    """
    try:
        return EVIDENCE_NAMES[level]
    except KeyError:
        raise ValueError(f"Unknown evidence level: {level!r}") from None
