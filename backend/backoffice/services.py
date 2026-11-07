"""Services of the back office: retention of the access log."""

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .models import AdminAccessLog


def purge_admin_access_log(*, now: datetime | None = None) -> int:
    """Delete access-log rows older than ``settings.ADMIN_ACCESS_LOG_RETENTION_DAYS``.

    The retention is a working value that the lawyer must confirm (docs/12 §12.8). Nothing
    else deletes rows of the log.

    Output: the number of deleted rows.

    Raises:
        ValueError: the retention setting is not a positive number of days (a wrong
            setting must not delete the whole log).
    """
    days = settings.ADMIN_ACCESS_LOG_RETENTION_DAYS
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("ADMIN_ACCESS_LOG_RETENTION_DAYS must be a positive number of days.")
    cutoff = (now or timezone.now()) - timedelta(days=days)
    deleted, _ = AdminAccessLog.objects.filter(timestamp__lt=cutoff).delete()
    return deleted
