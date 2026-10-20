"""Record the initial state of the health condition catalog in its history.

Data migrations use historical models, which do not send the signals that
django-simple-history listens to, so ``0002_seed_health_conditions`` left the catalog
without history. This migration adds a "created" record (``+``) for every catalog
entry that has no history yet, so the first change made by the specialist in the
admin is stored next to the original values. Running it again adds nothing.
"""

from django.db import migrations
from django.utils import timezone

FIELDS = ("id", "code", "name_cs", "description_cs", "mode", "source_note")


def add_initial_history(apps, schema_editor):
    HealthCondition = apps.get_model("animals", "HealthCondition")
    HistoricalHealthCondition = apps.get_model("animals", "HistoricalHealthCondition")
    with_history = HistoricalHealthCondition.objects.values("id")
    now = timezone.now()
    HistoricalHealthCondition.objects.bulk_create(
        HistoricalHealthCondition(
            **{name: getattr(condition, name) for name in FIELDS},
            history_date=now,
            history_type="+",
            history_change_reason="Výchozí stav číselníku (migrace 0002).",
        )
        for condition in HealthCondition.objects.exclude(id__in=with_history).order_by("id")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("animals", "0002_seed_health_conditions"),
    ]

    operations = [migrations.RunPython(add_initial_history, migrations.RunPython.noop)]
