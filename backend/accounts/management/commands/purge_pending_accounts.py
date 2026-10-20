"""``manage.py purge_pending_accounts``: delete registrations that were never activated.

Run it periodically (e.g. daily from cron or a systemd timer, README). The retention
is ``settings.PENDING_ACCOUNT_RETENTION``.
"""

from typing import Any

from django.core.management.base import BaseCommand

from accounts.services import purge_pending_accounts


class Command(BaseCommand):
    help = "Smaže registrace, které nebyly aktivovány v době PENDING_ACCOUNT_RETENTION."

    def handle(self, *args: Any, **options: Any) -> None:
        deleted = purge_pending_accounts()
        self.stdout.write(f"Smazáno neaktivovaných registrací: {deleted}")
