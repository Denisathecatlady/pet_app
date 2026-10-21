"""Loading the library: ``manage.py load_sources``, the loader and the data migration."""

import ast
import importlib
import json
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from catalog import loader
from catalog.loader import DATA_FILE, SourceDataError
from catalog.models import ScientificSource

pytestmark = pytest.mark.django_db


def file_entries() -> list[dict]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))["sources"]


def entry(key: str = "Novy2026", **changes) -> dict:
    values = {
        "citation_key": key,
        "title": "Nový zdroj",
        "source_type": "ORIGINAL_STUDY",
        "evidence_level": "L3",
        "species_scope": "DOG",
        "verification_level": "NONE",
    }
    return {**values, **changes}


VERIFIED = {
    "verification_level": "B",
    "verification_markers": ["B"],
    "last_verified_at": "2026-10-18",
}


def write(tmp_path, entries, **top) -> str:
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps({"format_version": 1, "sources": entries, **top}, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(path)


def run(*args: str) -> str:
    out = StringIO()
    call_command("load_sources", *args, stdout=out)
    return out.getvalue()


# --- The shipped file, loaded into an empty library ------------------------------------------


def test_load_creates_every_source_of_the_file(empty_library):
    expected = file_entries()
    assert len(expected) == 37

    output = run()

    assert output.strip() == "Zdrojů v souboru: 37. Vytvořeno: 37, aktualizováno: 0, beze změny: 0."
    assert set(ScientificSource.objects.values_list("citation_key", flat=True)) == {
        item["citation_key"] for item in expected
    }
    fediaf = ScientificSource.objects.get(citation_key="FEDIAF2025")
    assert fediaf.year == 2025 and fediaf.verification_level == "S"
    assert fediaf.verification_markers == ["B", "S"]
    assert fediaf.last_verified_at == date(2026, 10, 18)
    assert fediaf.verified_by is None  # the file never names a person


def test_load_is_idempotent(empty_library):
    run()
    history_before = ScientificSource.history.count()

    second = run()
    third = run("--verbosity", "2")

    for output in (second, third):
        assert "Vytvořeno: 0, aktualizováno: 0, beze změny: 37." in output
    assert ScientificSource.objects.count() == 37
    assert ScientificSource.history.count() == history_before  # no empty history records


def test_every_loaded_source_is_valid_and_has_history(empty_library):
    run()
    for source in ScientificSource.objects.all():
        source.full_clean()
    assert ScientificSource.history.filter(history_type="+").count() == 37
    reason = ScientificSource.history.first().history_change_reason
    assert reason == "Načteno ze souboru sources.json (manage.py load_sources)."


def test_shipped_library_is_already_loaded_by_the_migration():
    """The test database is built by migrating: the library is there without any command."""
    assert ScientificSource.objects.count() == 37
    assert "Vytvořeno: 0, aktualizováno: 0, beze změny: 37." in run()


# --- Updating, never deleting ---------------------------------------------------------------


def test_update_changes_only_what_differs_and_reports_the_fields(tmp_path, empty_library):
    path = write(tmp_path, [entry("A1"), entry("B1")])
    run("--file", path)
    changed = [entry("A1", title="Změněný název", year=2001), entry("B1")]

    output = run("--file", write(tmp_path, changed), "--verbosity", "2")

    assert "Vytvořeno: 0, aktualizováno: 1, beze změny: 1." in output
    assert "aktualizován: A1 (pole: title, year)" in output
    source = ScientificSource.objects.get(citation_key="A1")
    assert (source.title, source.year) == ("Změněný název", 2001)
    assert source.history.count() == 2


def test_load_never_deletes(tmp_path, empty_library, make_source):
    own = make_source(citation_key="Moje1")
    run("--file", write(tmp_path, [entry("A1"), entry("B1")]))

    run("--file", write(tmp_path, [entry("A1")]))  # B1 left out of the file

    assert set(ScientificSource.objects.values_list("citation_key", flat=True)) == {
        "Moje1",
        "A1",
        "B1",
    }
    assert ScientificSource.objects.filter(pk=own.pk).exists()


def test_load_keeps_the_verifier_which_is_not_part_of_the_file(tmp_path, empty_library, user):
    run("--file", write(tmp_path, [entry("A1", **VERIFIED)]))
    ScientificSource.objects.filter(citation_key="A1").update(verified_by=user)

    run("--file", write(tmp_path, [entry("A1", title="Jiný", **VERIFIED)]))

    assert ScientificSource.objects.get(citation_key="A1").verified_by == user


def test_omitted_optional_fields_are_reset_to_empty(tmp_path, empty_library):
    run("--file", write(tmp_path, [entry("A1", year=1999, url="https://example.org/x")]))
    run("--file", write(tmp_path, [entry("A1")]))
    source = ScientificSource.objects.get(citation_key="A1")
    assert source.year is None and source.url == ""


def test_dry_run_writes_nothing(tmp_path, empty_library):
    path = write(tmp_path, [entry("A1")])

    output = run("--file", path, "--dry-run")

    assert "Zkouška (nic nezapsáno)." in output and "Vytvořeno: 1" in output
    assert "vytvořen: A1" in output
    assert ScientificSource.objects.count() == 0 and ScientificSource.history.count() == 0


def test_dry_run_lists_updates(tmp_path, empty_library):
    run("--file", write(tmp_path, [entry("A1")]))
    output = run("--file", write(tmp_path, [entry("A1", title="Jiný")]), "--dry-run")
    assert "aktualizován: A1 (pole: title)" in output
    assert ScientificSource.objects.get(citation_key="A1").title == "Nový zdroj"


# --- Mistakes in the file change nothing ----------------------------------------------------


def test_one_invalid_entry_stops_the_whole_load(tmp_path, empty_library):
    good, bad = entry("Dobry1"), entry("Spatny1", year=1800, url="javascript:alert(1)")

    with pytest.raises(CommandError) as error:
        run("--file", write(tmp_path, [good, bad]))

    assert "nic nebylo zapsáno" in str(error.value)
    assert "Spatny1" in str(error.value) and "Rok musí být" in str(error.value)
    assert ScientificSource.objects.count() == 0


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([entry("A1", nesmysl=1)], "neznámá pole: nesmysl"),
        ([{"citation_key": "A1"}], "chybí pole: title, source_type"),
        ([entry("A1", year="2020")], "pole year musí být celé číslo"),
        ([entry("A1", year=True)], "pole year musí být celé číslo"),
        ([entry("A1", title=5)], "pole title musí být text"),
        ([entry("A1", life_stages="ADULT")], "pole life_stages musí být seznam"),
        ([entry("A1", last_verified_at="18. 10. 2026")], "last_verified_at musí být datum"),
        ([entry("A1", last_verified_at=20261018)], "last_verified_at musí být datum"),
        ([entry("A1"), entry("a1")], "citační klíč se opakuje"),
        (["text"], "není objekt"),
    ],
)
def test_malformed_entries_are_reported(tmp_path, empty_library, entries, message):
    with pytest.raises(CommandError, match=message):
        run("--file", write(tmp_path, entries))
    assert ScientificSource.objects.count() == 0


def test_all_problems_are_reported_together(tmp_path, empty_library):
    entries = [entry("A1", year="x"), entry("B1", title=1)]
    with pytest.raises(SourceDataError) as error:
        loader.load_sources(write(tmp_path, entries))
    assert "A1" in str(error.value) and "B1" in str(error.value)


def test_unreadable_files_are_reported(tmp_path):
    with pytest.raises(CommandError, match="nelze přečíst"):
        run("--file", str(tmp_path / "chybi.json"))
    broken = tmp_path / "broken.json"
    broken.write_text("{ nope", encoding="utf-8")
    with pytest.raises(CommandError, match="není platný JSON"):
        run("--file", str(broken))
    for content in ('{"format_version": 2, "sources": []}', "[]", '{"format_version": 1}'):
        broken.write_text(content, encoding="utf-8")
        with pytest.raises(CommandError):
            run("--file", str(broken))


def test_case_clash_with_an_existing_key_is_reported(tmp_path, empty_library, make_source):
    make_source(citation_key="Klic1")
    with pytest.raises(CommandError, match="Klic1|klic1"):
        run("--file", write(tmp_path, [entry("klic1")]))
    assert ScientificSource.objects.count() == 1


# --- The data migration ---------------------------------------------------------------------


def migrate_catalog_to(target: str) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([("catalog", target)])
    return MigrationExecutor(connection)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_migration_loads_the_library_on_a_fresh_install():
    """Unapply the data migration, empty the table, apply again: a fresh install."""
    migrate_catalog_to("0001_initial")
    try:
        ScientificSource.objects.all().delete()
        ScientificSource.history.all().delete()
        assert ScientificSource.objects.count() == 0

        migrate_catalog_to("0002_load_sources")

        assert ScientificSource.objects.count() == len(file_entries()) == 37
        assert ScientificSource.history.filter(history_type="+").count() == 37
        # The command finds nothing to do: the migration wrote exactly what the file says.
        assert "Vytvořeno: 0, aktualizováno: 0, beze změny: 37." in run()
    finally:
        migrate_catalog_to("0002_load_sources")


def historical_apps():
    executor = MigrationExecutor(connection)
    return executor.loader.project_state(("catalog", "0001_initial")).apps


def test_migration_loader_ignores_unknown_fields_and_keeps_existing_rows(tmp_path, monkeypatch):
    """A newer file with fields the model does not have yet must not break a fresh install;
    a source that already exists is not overwritten."""
    migration = importlib.import_module("catalog.migrations.0002_load_sources")
    path = write(
        tmp_path,
        [
            entry("Nova1", future_field="x", last_verified_at=None),
            entry("Stara1", title="Z migrace"),
        ],
    )
    monkeypatch.setattr(migration, "DATA_FILE", Path(path))
    ScientificSource.objects.all().delete()
    ScientificSource.objects.create(
        citation_key="Stara1",
        title="Z administrace",
        source_type="GUIDELINE",
        evidence_level="L1",
        species_scope="BOTH",
        verification_level="NONE",
    )
    before_history = ScientificSource.history.count()

    migration.load_sources(historical_apps(), None)

    assert ScientificSource.objects.get(citation_key="Nova1").title == "Nový zdroj"
    assert ScientificSource.objects.get(citation_key="Stara1").title == "Z administrace"
    assert ScientificSource.history.count() == before_history + 1  # only the new source
    migration.load_sources(historical_apps(), None)  # again: nothing new
    assert ScientificSource.objects.count() == 2


def test_migration_does_not_import_application_code():
    path = DATA_FILE.parent.parent / "migrations" / "0002_load_sources.py"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("catalog", "accounts", "core"))
        elif isinstance(node, ast.Import):
            assert not any(alias.name.startswith("catalog") for alias in node.names)
