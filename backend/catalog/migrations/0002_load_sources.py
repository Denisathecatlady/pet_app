"""Load the library of sources from ``catalog/data/sources.json`` on a fresh install.

Self-contained on purpose: a migration must not import application code that may change
later, so this file has its own small loader. ``manage.py load_sources`` is the maintained
tool for later updates; a test checks that the rows loaded here are identical to what
that command would write.

Rules:

* only fields that exist in the model *as of this migration* are read from the file, so a
  later version of the file with more fields does not break a fresh install (the command
  fills the new fields afterwards);
* a source whose citation key already exists is left alone (nothing is overwritten);
* nothing is deleted, also not when the migration is reversed;
* historical models send no signals, so the history record "created" (``+``) that
  django-simple-history would write is added here, as in ``animals.0003``.
"""

import json
from datetime import date
from pathlib import Path

from django.db import migrations
from django.utils import timezone

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "sources.json"
CHANGE_REASON = "Načteno ze souboru sources.json (migrace 0002)."
NOT_IN_FILE = {"id", "verified_by", "created_at", "updated_at"}


def load_sources(apps, schema_editor):
    ScientificSource = apps.get_model("catalog", "ScientificSource")
    Historical = apps.get_model("catalog", "HistoricalScientificSource")
    fields = ScientificSource._meta.concrete_fields
    in_file = {field.name for field in fields} - NOT_IN_FILE

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    now = timezone.now()
    history = []
    for entry in data["sources"]:
        values = {name: value for name, value in entry.items() if name in in_file}
        if values.get("last_verified_at"):
            values["last_verified_at"] = date.fromisoformat(values["last_verified_at"])
        source, created = ScientificSource.objects.get_or_create(
            citation_key=values.pop("citation_key"), defaults=values
        )
        if created:
            history.append(
                Historical(
                    **{field.attname: getattr(source, field.attname) for field in fields},
                    history_date=now,
                    history_type="+",
                    history_change_reason=CHANGE_REASON,
                )
            )
    Historical.objects.bulk_create(history)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [migrations.RunPython(load_sources, migrations.RunPython.noop)]
