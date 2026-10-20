"""Warning levels of docs/08 §8.6 and how the UI shows them.

Every level is shown as icon + text + colour, never colour alone (docs/08 §8.1).
The level names match ``nutricalc.vocab.WarningLevel`` without importing it.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True)
class LevelStyle:
    css: str  # suffix of the CSS classes ``status--<css>`` and ``notice--<css>``
    icon: str
    label: str


WARNING_LEVELS: Final = MappingProxyType(
    {
        "INFO": LevelStyle("info", "ⓘ", "Informativní doporučení"),
        "NUTRITION_WARNING": LevelStyle("nutrition-warning", "⚠", "Nutriční varování"),
        "EXPERT_REQUIRED": LevelStyle("expert-required", "🩺", "Vyžaduje odborné posouzení"),
        "BLOCKED": LevelStyle("blocked", "⛔", "Automatický výpočet nelze doporučit"),
    }
)


def level_style(level: str) -> LevelStyle:
    """Return the style of a warning level.

    Args:
        level: ``INFO``, ``NUTRITION_WARNING``, ``EXPERT_REQUIRED`` or ``BLOCKED``
            (case-insensitive).

    Raises:
        ValueError: unknown level. An unknown level must never render as a neutral badge.
    """
    try:
        return WARNING_LEVELS[str(level).upper()]
    except KeyError:
        raise ValueError(f"Unknown warning level: {level!r}") from None
