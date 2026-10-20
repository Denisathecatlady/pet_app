from django.apps import AppConfig


class AnimalsConfig(AppConfig):
    name = "animals"
    verbose_name = "Zvířata"

    def ready(self) -> None:
        from accounts.export import register_exporter

        from . import signals  # noqa: F401  (connects receivers)
        from .export import export_animals

        register_exporter("animals", export_animals)
