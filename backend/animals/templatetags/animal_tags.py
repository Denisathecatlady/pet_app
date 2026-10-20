"""Template tags and filters of the animals app."""

from datetime import date
from decimal import Decimal
from itertools import groupby

from django import template

from animals.models import format_kg
from animals.services import OK, Attention, short_date
from core.status import level_style

register = template.Library()

# "OK" is not a warning level of docs/08 §8.6, so core.status does not know it. It is
# neutral on purpose (no green): it means only that the records give no reason to warn.
OK_STYLE = {"css": "ok", "icon": "○", "label": "Bez upozornění v evidenci"}


@register.inclusion_tag("core/includes/status_badge.html")
def attention_badge(attention: Attention, text: str = "") -> dict[str, str]:
    """Render the badge of an attention level: icon + text + colour (docs/08 §8.1).

    Raises:
        ValueError: unknown level (from ``core.status.level_style``).
    """
    if attention.level == OK:
        return {**OK_STYLE, "text": text}
    style = level_style(attention.level)
    return {"css": style.css, "icon": style.icon, "label": style.label, "text": text}


@register.inclusion_tag("animals/includes/attention_panel.html")
def attention_panel(attention: Attention, for_owner: bool = True) -> dict[str, object]:
    """Render the attention level with its reasons grouped by level (docs/08 §8.6).

    Each level present is shown once as a badge (icon + text + colour) followed by the
    reasons of that level, most severe first, so the level text is not repeated for
    every reason. ``for_owner`` picks the "what next" advice: owners are sent to a vet,
    a shared vet gets advice written for a vet.
    """
    style = attention_badge(attention)
    groups = [
        {**attention_badge(Attention(level, ())), "texts": [reason.text for reason in reasons]}
        for level, reasons in groupby(attention.reasons, key=lambda reason: reason.level)
    ]
    return {**style, "level": attention.level, "groups": groups, "for_owner": for_owner}


@register.filter
def kg(value: Decimal | None) -> str:
    """``Decimal("12.500")`` → ``12,5 kg``; ``None`` → empty string."""
    if value is None:
        return ""
    return f"{format_kg(value)}\N{NO-BREAK SPACE}kg"


@register.filter
def short(value: date | None) -> str:
    """``date(2026, 10, 3)`` → ``3. 10. 2026``; ``None`` → empty string."""
    return short_date(value) if value else ""
