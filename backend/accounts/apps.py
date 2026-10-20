from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Uživatelské účty"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (connects receivers)
        from .export import export_account, register_exporter

        register_exporter("account", export_account)
