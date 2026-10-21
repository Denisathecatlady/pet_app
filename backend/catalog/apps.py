from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "catalog"
    verbose_name = "Knihovna zdrojů"

    def ready(self) -> None:
        from accounts.export import register_exporter

        from . import signals  # noqa: F401  (connects receivers)
        from .export import export_catalog

        register_exporter("catalog", export_catalog)
