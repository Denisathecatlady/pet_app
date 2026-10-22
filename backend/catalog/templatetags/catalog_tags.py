"""Template tags of the library of sources: badges and the legend."""

from typing import Any

from django import template

from catalog.display import EVIDENCE_NAMES, content_caveat, evidence_name, verification_style
from catalog.models import EvidenceLevel, VerificationLevel

register = template.Library()


@register.inclusion_tag("catalog/includes/verification_badge.html")
def verification_badge(level: str) -> dict[str, str]:
    """Render ``{% verification_badge source.verification_level %}``: icon + text + colour.

    Raises:
        ValueError: unknown level.
    """
    style = verification_style(level)
    return {"css": style.css, "icon": style.icon, "name": style.name}


@register.inclusion_tag("catalog/includes/evidence_badge.html")
def evidence_badge(level: str) -> dict[str, str]:
    """Render ``{% evidence_badge source.evidence_level %}``: the code and a short name.

    Raises:
        ValueError: unknown level.
    """
    return {"code": level, "name": evidence_name(level)}


@register.inclusion_tag("catalog/includes/content_caveat.html")
def source_content_caveat(level: str) -> dict[str, str]:
    """Render ``{% source_content_caveat source.verification_level %}``: the warning that the
    numbers and findings next to it were not checked in the original (nothing for A and P).

    Raises:
        ValueError: unknown level.
    """
    return {"text": content_caveat(level)}


# The legend lists the verification levels from the strongest to the weakest, the order in
# which one badge stands for several marks (models.VERIFICATION_STRENGTH).
LEGEND_VERIFICATION_ORDER = (
    VerificationLevel.P,
    VerificationLevel.A,
    VerificationLevel.S,
    VerificationLevel.B,
    VerificationLevel.NONE,
)


@register.inclusion_tag("catalog/includes/legend.html")
def source_legend() -> dict[str, Any]:
    """Render the legend: all evidence levels and all verification levels with their meaning."""
    return {
        "evidence": [
            (level.value, EVIDENCE_NAMES[level.value], level.label) for level in EvidenceLevel
        ],
        "verification": [(level.value, level.label) for level in LEGEND_VERIFICATION_ORDER],
    }
