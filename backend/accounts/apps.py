from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Uživatelské účty"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (connects receivers)
        from .export import (
            export_account,
            export_data_subject_requests,
            export_two_factor,
            export_vet_verification,
            register_exporter,
        )
        from .role_permissions import sync_after_migrate

        register_exporter("account", export_account)
        register_exporter("two_factor", export_two_factor)
        register_exporter("vet_verification", export_vet_verification)
        register_exporter("data_subject_requests", export_data_subject_requests)
        # Apply ROLE_PERMISSIONS after Django created the permissions (docs/14 §14.3).
        post_migrate.connect(sync_after_migrate, dispatch_uid="accounts_sync_role_permissions")
