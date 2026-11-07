"""``manage.py purge_admin_access_log``: delete old rows of the admin access log.

Run it periodically (e.g. daily from cron, docs/13 §13.7). The retention is
``settings.ADMIN_ACCESS_LOG_RETENTION_DAYS``: a working value, to be confirmed by the lawyer
(docs/12 §12.8 point 5).
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backoffice.services import purge_admin_access_log


class Command(BaseCommand):
    help = "Smaže záznamy o přístupu do administrace starší než ADMIN_ACCESS_LOG_RETENTION_DAYS."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            deleted = purge_admin_access_log()
        except ValueError as error:
            raise CommandError(f"Nic nebylo smazáno: {error}") from error
        self.stdout.write(
            f"Smazáno záznamů o přístupu do administrace starších než "
            f"{settings.ADMIN_ACCESS_LOG_RETENTION_DAYS} dní: {deleted}"
        )
