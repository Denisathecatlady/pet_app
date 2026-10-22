"""Loading ``catalog/data/sources.json`` into ``ScientificSource`` (``manage.py load_sources``).

The file mirrors docs/zdroje.md (docs/15-zdroje-v-aplikaci.md §15.5). Loading is an upsert by
``citation_key``: sources in the file are created or updated, sources not in the file are never
deleted,
and ``verified_by`` (not part of the file) is never touched. Everything is validated
(``full_clean``) before anything is written, and written in one transaction, so a mistake
in the file changes nothing.

The data migration ``0002_load_sources`` has its own, simpler loader on purpose
(migrations must not import application code); a test checks that both give the same rows.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ScientificSource

DATA_FILE: Final = Path(__file__).resolve().parent / "data" / "sources.json"
FORMAT_VERSION: Final = 1
CHANGE_REASON: Final = "Načteno ze souboru sources.json (manage.py load_sources)."

# Fields of the file and their empty values. ``citation_key`` identifies the source.
REQUIRED_FIELDS: Final = (
    "citation_key",
    "title",
    "source_type",
    "evidence_level",
    "species_scope",
    "verification_level",
)
OPTIONAL_DEFAULTS: Final[dict[str, Any]] = {
    "authors_or_org": "",
    "year": None,
    "publication_details": "",
    "doi": "",
    "url": "",
    "type_note": "",
    "life_stages": [],
    "units_and_conditions": "",
    "edition_version": "",
    "verification_markers": [],
    "verification_note": "",
    "last_verified_at": None,
    "limitations": "",
    "key_findings": "",
}
FIELD_ORDER: Final = (*REQUIRED_FIELDS, *OPTIONAL_DEFAULTS)
TEXT_FIELDS: Final = (
    "citation_key",
    "title",
    "authors_or_org",
    "publication_details",
    "doi",
    "url",
    "source_type",
    "type_note",
    "evidence_level",
    "species_scope",
    "units_and_conditions",
    "edition_version",
    "verification_level",
    "verification_note",
    "limitations",
    "key_findings",
)
LIST_FIELDS: Final = ("life_stages", "verification_markers")


class SourceDataError(ValueError):
    """The data file is unreadable or has mistakes; the message lists all of them."""


@dataclass(frozen=True)
class LoadResult:
    """Outcome of a load: keys created, keys updated (with the names of the changed
    fields) and the number of sources already identical to the file."""

    created: list[str] = field(default_factory=list)
    updated: dict[str, list[str]] = field(default_factory=dict)
    unchanged: int = 0

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated) + self.unchanged


def read_entries(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    """Read and structurally check the data file.

    Output: the list of entries (dicts) in file order, values converted to the types of
    the model (``last_verified_at`` as ``date``).

    Raises:
        SourceDataError: file missing or not valid JSON, wrong ``format_version``, an
            entry that is not an object, an unknown or missing field, a wrong type,
            a bad date or a repeated citation key (letter case ignored).
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise SourceDataError(f"Soubor {path} nelze přečíst: {error}") from error
    except json.JSONDecodeError as error:
        raise SourceDataError(f"Soubor {path} není platný JSON: {error}") from error
    if not isinstance(data, dict) or data.get("format_version") != FORMAT_VERSION:
        raise SourceDataError(f"Očekává se objekt s položkou format_version = {FORMAT_VERSION}.")
    raw_entries = data.get("sources")
    if not isinstance(raw_entries, list):
        raise SourceDataError('Položka "sources" musí být seznam.')

    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: dict[str, int] = {}
    for position, raw in enumerate(raw_entries, start=1):
        label = f"záznam č. {position}"
        if not isinstance(raw, dict):
            errors.append(f"{label}: není objekt.")
            continue
        label = str(raw.get("citation_key") or label)
        entry, problems = _coerce(raw)
        errors.extend(f"{label}: {problem}" for problem in problems)
        key = str(entry.get("citation_key", "")).lower()
        if key and key in seen:
            errors.append(f"{label}: citační klíč se opakuje (záznam č. {seen[key]}).")
        seen.setdefault(key, position)
        entries.append(entry)
    if errors:
        raise SourceDataError("\n".join(errors))
    return entries


def _coerce(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return the entry with defaults and converted types, and the list of problems."""
    problems: list[str] = []
    unknown = sorted(set(raw) - set(REQUIRED_FIELDS) - set(OPTIONAL_DEFAULTS))
    if unknown:
        problems.append(f"neznámá pole: {', '.join(unknown)}.")
    missing = [name for name in REQUIRED_FIELDS if name not in raw]
    if missing:
        problems.append(f"chybí pole: {', '.join(missing)}.")
    entry = {name: _copy(default) for name, default in OPTIONAL_DEFAULTS.items()}
    entry.update({name: value for name, value in raw.items() if name not in unknown})
    for name in TEXT_FIELDS:
        if name in entry and not isinstance(entry[name], str):
            problems.append(f"pole {name} musí být text.")
    for name in LIST_FIELDS:
        if not isinstance(entry[name], list):
            problems.append(f"pole {name} musí být seznam.")
    year = entry["year"]
    if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
        problems.append("pole year musí být celé číslo nebo null.")
    verified = entry["last_verified_at"]
    if verified is not None:
        try:
            entry["last_verified_at"] = date.fromisoformat(verified)
        except (TypeError, ValueError):
            problems.append("pole last_verified_at musí být datum RRRR-MM-DD nebo null.")
    return entry, problems


def _copy(value: Any) -> Any:
    return list(value) if isinstance(value, list) else value


def load_sources(path: Path = DATA_FILE, *, dry_run: bool = False) -> LoadResult:
    """Create or update the sources in ``path``; never delete anything.

    Inputs: the data file and ``dry_run`` (only report what would change, write nothing).
    Output: ``LoadResult``. A second run with the same file creates and updates nothing.
    Each created or changed source gets a history record with ``CHANGE_REASON``.

    Raises:
        SourceDataError: the file has mistakes (see ``read_entries``) or an entry fails
            the model's validation; in both cases nothing has been written.
    """
    entries = read_entries(path)
    existing = {
        source.citation_key.lower(): source
        for source in ScientificSource.objects.filter(
            citation_key__in=[entry["citation_key"] for entry in entries]
        )
    }
    pending: list[ScientificSource] = []
    created: list[str] = []
    updated: dict[str, list[str]] = {}
    unchanged = 0
    errors: list[str] = []
    for entry in entries:
        source = existing.get(entry["citation_key"].lower())
        if source is None:
            source = ScientificSource(**entry)
            created.append(entry["citation_key"])
        else:
            changed = [name for name in FIELD_ORDER if getattr(source, name) != entry[name]]
            if not changed:
                unchanged += 1
                continue
            for name in changed:
                setattr(source, name, entry[name])
            updated[source.citation_key] = changed
        try:
            source.full_clean()
        except ValidationError as error:
            errors.extend(
                f"{entry['citation_key']}: {message}"
                for messages in error.message_dict.values()
                for message in messages
            )
        pending.append(source)
    if errors:
        raise SourceDataError("\n".join(errors))
    if not dry_run:
        with transaction.atomic():
            for source in pending:
                source._change_reason = CHANGE_REASON
                source.save()
    return LoadResult(created=created, updated=updated, unchanged=unchanged)
