from typing import Any

from django.apps import AppConfig
from django.core import checks


def check_personal_data_admins(app_configs: Any, **kwargs: Any) -> list[checks.CheckMessage]:
    """Fail ``manage.py check`` when a model with personal data has an admin without the mixin.

    The rule of docs/14 §14.7: every admin of a model flagged ``contains_personal_data`` records
    its accesses (``backoffice.access_log.AccessLoggedAdminMixin``).
    """
    from .access_log import admin_mixin_missing

    return [
        checks.Error(
            f"The admin of {label} does not use AccessLoggedAdminMixin.",
            hint="Models with personal data must log accesses (docs/14 §14.7).",
            id="backoffice.E001",
        )
        for label in admin_mixin_missing()
    ]


class BackofficeConfig(AppConfig):
    name = "backoffice"
    verbose_name = "Správa a audit"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (connects receivers)

        checks.register(check_personal_data_admins, checks.Tags.admin)
