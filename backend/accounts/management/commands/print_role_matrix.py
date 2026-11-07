"""``manage.py print_role_matrix``: print the role table as a Markdown table.

The output is what docs/14 §14.3 embeds between two marker lines; a test compares the two.
"""

from typing import Any

from django.core.management.base import BaseCommand

from accounts.role_permissions import render_role_matrix


class Command(BaseCommand):
    help = "Vypíše tabulku oprávnění rolí (ROLE_PERMISSIONS) jako tabulku v Markdownu."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(render_role_matrix(), ending="")
