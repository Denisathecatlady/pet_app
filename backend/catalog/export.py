"""GDPR export of the catalog app (registered in ``CatalogConfig.ready``).

Section ``catalog`` of the personal data export (accounts/export.py): the sources the
user is recorded as the verifier of, and the changes of sources they made in the admin
(from the change history). Both are empty for most accounts.
"""

from typing import Any

from django.utils import timezone

from .models import ScientificSource

_HISTORY_TYPES = {"+": "created", "~": "changed", "-": "deleted"}


def export_catalog(user: Any) -> dict[str, Any]:
    """Return ``{"verified_sources": [...], "changes": [...]}`` for ``user``.

    ``verified_sources``: citation key and date of the last verification of every source
    whose ``verified_by`` is the user. ``changes``: citation key, time and kind of every
    history record made by the user. Output is JSON-serialisable (dates as ISO 8601).
    """
    verified = ScientificSource.objects.filter(verified_by=user).order_by("citation_key")
    changes = ScientificSource.history.model.objects.filter(history_user=user).order_by(
        "history_date", "history_id"
    )
    return {
        "verified_sources": [
            {
                "citation_key": source.citation_key,
                "last_verified_at": (
                    source.last_verified_at.isoformat() if source.last_verified_at else None
                ),
            }
            for source in verified
        ],
        "changes": [
            {
                "citation_key": record.citation_key,
                "changed_at": timezone.localtime(record.history_date).isoformat(),
                "type": _HISTORY_TYPES[record.history_type],
            }
            for record in changes
        ],
    }
