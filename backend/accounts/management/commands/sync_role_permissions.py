"""``manage.py sync_role_permissions``: apply ``ROLE_PERMISSIONS`` to the role groups.

The same synchronisation runs after every ``migrate``; this command is for applying it by
hand and for ``--dry-run`` (docs/14 §14.3). It is idempotent: the second run reports no change.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from accounts.role_permissions import UnknownPermissionError, sync_role_permissions
from accounts.roles import ROLE_LABELS


class Command(BaseCommand):
    help = (
        "Nastaví oprávnění rolí (skupin) přesně podle tabulky ROLE_PERMISSIONS "
        "v accounts/roles.py. Superuživatele a jejich oprávnění se netýká."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Jen vypíše, co by se změnilo; nic nezapíše.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            report = sync_role_permissions(dry_run=options["dry_run"])
        except UnknownPermissionError as error:
            raise CommandError(f"Oprávnění rolí se nepodařilo nastavit: {error}") from error
        prefix = "Zkouška (nic nezapsáno). " if options["dry_run"] else ""
        if not report.changed:
            self.stdout.write(f"{prefix}Oprávnění rolí jsou beze změny.")
            return
        self.stdout.write(f"{prefix}Oprávnění rolí byla upravena:")
        for role in report.groups_created:
            self.stdout.write(f"  skupina {role}: vytvořena")
        roles = sorted(set(report.added) | set(report.removed))
        for role in roles:
            self.stdout.write(f"  {ROLE_LABELS.get(role, role)} ({role}):")
            for entry in report.added.get(role, ()):
                self.stdout.write(f"    + {entry}")
            for entry in report.removed.get(role, ()):
                self.stdout.write(f"    - {entry}")
