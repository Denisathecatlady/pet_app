"""``manage.py reset_2fa <e-mail>``: remove the two-factor devices of an account.

For loss of the device when no superuser can use the administration (shell access to the
server is the proof of authority). The user must set two-factor authentication up again at the
next sign-in; staff cannot use anything before that. The reset is written to the access log of
the administration and to the application log (docs/14 §14.6).
"""

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from accounts import two_factor
from accounts.models import User, UserManager
from backoffice.access_log import log_command_access
from backoffice.models import AdminAccessAction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Zruší dvoufázové ověření účtu (ztráta zařízení). Uživatel ho musí nastavit znovu."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("email", help="E-mail účtu.")

    def handle(self, *args: Any, **options: Any) -> None:
        email = UserManager.normalize_email(options["email"])
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"Účet s e-mailem {email} neexistuje.")
        removed = two_factor.remove_devices(user)
        log_command_access("reset_2fa", AdminAccessAction.CHANGE, User, [user.pk])
        logger.warning("Two-factor reset for user %s by manage.py reset_2fa.", user.pk)
        self.stdout.write(
            f"Dvoufázové ověření účtu {user.email} bylo zrušeno (smazaných zařízení: {removed})."
        )
