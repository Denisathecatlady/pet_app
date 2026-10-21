"""``manage.py load_sources``: load the library of sources from ``catalog/data/sources.json``.

Upsert by citation key; nothing is ever deleted (docs/13 §13.5). Safe to run repeatedly:
the second run reports every source as unchanged.
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from catalog.loader import DATA_FILE, SourceDataError, load_sources


class Command(BaseCommand):
    help = (
        "Načte knihovnu odborných zdrojů ze souboru catalog/data/sources.json "
        "(vytvoří nové zdroje, aktualizuje změněné, nic nemaže)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--file",
            type=Path,
            default=DATA_FILE,
            help="Jiný soubor ve stejném formátu (výchozí: catalog/data/sources.json).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Jen vypíše, co by se změnilo; nic nezapíše.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            result = load_sources(options["file"], dry_run=options["dry_run"])
        except SourceDataError as error:
            raise CommandError(
                f"Zdroje se nepodařilo načíst, nic nebylo zapsáno:\n{error}"
            ) from error
        prefix = "Zkouška (nic nezapsáno). " if options["dry_run"] else ""
        self.stdout.write(
            f"{prefix}Zdrojů v souboru: {result.total}. "
            f"Vytvořeno: {len(result.created)}, aktualizováno: {len(result.updated)}, "
            f"beze změny: {result.unchanged}."
        )
        if options["verbosity"] >= 2 or options["dry_run"]:
            for key in result.created:
                self.stdout.write(f"  vytvořen: {key}")
            for key, fields in result.updated.items():
                self.stdout.write(f"  aktualizován: {key} (pole: {', '.join(fields)})")
