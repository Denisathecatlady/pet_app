"""Template tags for warning-level badges (docs/08 §8.6)."""

from django import template

from core.status import level_style

register = template.Library()


@register.inclusion_tag("core/includes/status_badge.html")
def status_badge(level: str, text: str = "") -> dict[str, str]:
    """Render ``{% status_badge "EXPERT_REQUIRED" "optional text" %}``.

    Outputs an icon (hidden from screen readers), visible text and the colour class
    of the level. Without ``text`` the standard label of the level is shown.

    Raises:
        ValueError: unknown level.
    """
    style = level_style(level)
    return {"css": style.css, "icon": style.icon, "label": style.label, "text": text}
