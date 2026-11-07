"""``ROLE_PERMISSIONS``, its synchronisation and the printed matrix (docs/14 §14.3)."""

import io
from types import MappingProxyType

import pytest
from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts import role_permissions
from accounts.role_permissions import (
    UnknownPermissionError,
    defined_permissions,
    render_role_matrix,
    sync_after_migrate,
    sync_role_permissions,
    validate_matrix,
)
from accounts.roles import ROLE_PERMISSIONS, STAFF_ROLES, Role
from config.settings.base import BASE_DIR

pytestmark = pytest.mark.django_db


def granted(role: str) -> set[str]:
    return {
        f"{p.content_type.app_label}.{p.codename}"
        for p in Group.objects.get(name=role).permissions.select_related("content_type")
    }


# --- The table itself -----------------------------------------------------------------------


def test_the_initial_matrix_is_the_decided_one():
    assert dict(ROLE_PERMISSIONS) == {
        "owner": (),
        "vet": (),
        "support_admin": (
            "accounts.view_user",
            "accounts.change_user",
            "accounts.view_vetverificationrequest",
            "accounts.decide_vetverificationrequest",
            "accounts.view_datasubjectrequest",
            "accounts.add_datasubjectrequest",
            "accounts.change_datasubjectrequest",
            "accounts.export_datasubjectrequest",
            "accounts.erase_datasubjectrequest",
            "axes.view_accessattempt",
            "axes.delete_accessattempt",
        ),
        "data_curator": (
            "catalog.view_scientificsource",
            "catalog.add_scientificsource",
            "catalog.change_scientificsource",
        ),
        "nutrition_reviewer": (
            "catalog.view_scientificsource",
            "animals.view_healthcondition",
            "animals.change_healthcondition",
        ),
    }


def test_every_role_is_in_the_table():
    assert set(ROLE_PERMISSIONS) == {role.value for role in Role}


def test_the_table_is_read_only():
    assert isinstance(ROLE_PERMISSIONS, MappingProxyType)
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS["owner"] = ("accounts.view_user",)  # type: ignore[index]


def test_support_has_nothing_on_animals_and_not_the_access_log():
    """Data minimisation (docs/12 §12.8 point 5): no health data, no reading of own access."""
    entries = set(ROLE_PERMISSIONS[Role.SUPPORT_ADMIN])
    assert not any(entry.startswith(("animals.", "backoffice.")) for entry in entries)
    for role, role_entries in ROLE_PERMISSIONS.items():
        assert not any(entry.startswith("backoffice.") for entry in role_entries), role


def test_nobody_may_delete_users_or_sources_by_role():
    for entries in ROLE_PERMISSIONS.values():
        assert "accounts.delete_user" not in entries
        assert "catalog.delete_scientificsource" not in entries


def test_recorded_requests_are_evidence_nobody_rewrites_or_deletes_them_by_role():
    """Vet verification requests are decided by actions only; data subject requests are
    recorded and handled, never deleted, and the decision permissions belong to support."""
    evidence = (
        "accounts.add_vetverificationrequest",
        "accounts.change_vetverificationrequest",
        "accounts.delete_vetverificationrequest",
        "accounts.delete_datasubjectrequest",
    )
    for role, entries in ROLE_PERMISSIONS.items():
        assert not set(evidence) & set(entries), role


@pytest.mark.parametrize(
    "permission",
    [
        "accounts.decide_vetverificationrequest",
        "accounts.export_datasubjectrequest",
        "accounts.erase_datasubjectrequest",
    ],
)
def test_the_decision_permissions_belong_to_support_only(permission):
    holders = {role for role, entries in ROLE_PERMISSIONS.items() if permission in entries}

    assert holders == {Role.SUPPORT_ADMIN.value}


def test_only_staff_roles_have_permissions():
    for role, entries in ROLE_PERMISSIONS.items():
        assert bool(entries) == (role in STAFF_ROLES), role


def test_every_entry_is_a_real_permission():
    validate_matrix()
    assert set().union(*ROLE_PERMISSIONS.values()) <= defined_permissions()


# --- Synchronisation ------------------------------------------------------------------------


def test_after_migrate_every_role_has_exactly_its_permissions():
    for role, entries in ROLE_PERMISSIONS.items():
        assert granted(role) == set(entries), role


def test_sync_is_idempotent():
    report = sync_role_permissions()
    assert not report.changed and report.not_yet_created == ()
    assert not sync_role_permissions().changed


def test_sync_repairs_a_changed_group():
    support = Group.objects.get(name=Role.SUPPORT_ADMIN)
    stray = Permission.objects.get(codename="delete_user")
    missing = Permission.objects.get(codename="change_user")
    support.permissions.add(stray)
    support.permissions.remove(missing)

    report = sync_role_permissions()

    assert report.changed
    assert report.added == {"support_admin": ("accounts.change_user",)}
    assert report.removed == {"support_admin": ("accounts.delete_user",)}
    assert granted(Role.SUPPORT_ADMIN) == set(ROLE_PERMISSIONS[Role.SUPPORT_ADMIN])
    assert not sync_role_permissions().changed


def test_sync_removes_permissions_from_roles_that_have_none():
    owner = Group.objects.get(name=Role.OWNER)
    owner.permissions.add(Permission.objects.get(codename="view_user"))

    report = sync_role_permissions()

    assert report.removed == {"owner": ("accounts.view_user",)}
    assert granted(Role.OWNER) == set()


def test_sync_creates_a_missing_group():
    Group.objects.get(name=Role.SUPPORT_ADMIN).delete()

    report = sync_role_permissions()

    assert report.groups_created == ("support_admin",)
    assert granted(Role.SUPPORT_ADMIN) == set(ROLE_PERMISSIONS[Role.SUPPORT_ADMIN])


def test_dry_run_reports_and_writes_nothing():
    support = Group.objects.get(name=Role.SUPPORT_ADMIN)
    support.permissions.clear()
    Group.objects.get(name=Role.DATA_CURATOR).delete()

    report = sync_role_permissions(dry_run=True)

    assert report.groups_created == ("data_curator",)
    assert set(report.added["support_admin"]) == set(ROLE_PERMISSIONS[Role.SUPPORT_ADMIN])
    assert "data_curator" in report.added
    assert granted(Role.SUPPORT_ADMIN) == set()
    assert not Group.objects.filter(name=Role.DATA_CURATOR).exists()


def test_groups_outside_the_table_are_left_alone():
    custom = Group.objects.create(name="custom_group")
    custom.permissions.add(Permission.objects.get(codename="view_user"))

    sync_role_permissions()

    assert granted("custom_group") == {"accounts.view_user"}


def test_sync_never_touches_users_or_superusers(make_user, superuser):
    plain = make_user("plain@example.cz", roles=(Role.SUPPORT_ADMIN,))
    plain.user_permissions.add(Permission.objects.get(codename="delete_user"))
    groups_before = set(superuser.groups.values_list("pk", flat=True))
    flags_before = (superuser.is_superuser, superuser.is_staff)

    sync_role_permissions()

    assert set(plain.user_permissions.values_list("codename", flat=True)) == {"delete_user"}
    superuser.refresh_from_db()
    assert set(superuser.groups.values_list("pk", flat=True)) == groups_before
    assert (superuser.is_superuser, superuser.is_staff) == flags_before
    assert not superuser.user_permissions.exists()


@pytest.mark.parametrize(
    "entry", ["accounts.fly_user", "nothing.view_user", "accounts", "view_user", ""]
)
def test_an_unknown_codename_is_a_clear_error(entry):
    with pytest.raises(UnknownPermissionError, match="support_admin") as error:
        sync_role_permissions({"support_admin": ("accounts.view_user", entry)})
    assert repr(entry) in str(error.value)
    # Nothing was applied: the real group is unchanged.
    assert granted(Role.SUPPORT_ADMIN) == set(ROLE_PERMISSIONS[Role.SUPPORT_ADMIN])


def test_all_unknown_entries_are_listed_at_once():
    with pytest.raises(UnknownPermissionError) as error:
        validate_matrix({"a": ("x.y",), "b": ("accounts.view_user", "z.w")})
    assert "'x.y'" in str(error.value) and "'z.w'" in str(error.value)


def test_missing_database_rows_fail_unless_told_otherwise():
    Permission.objects.filter(codename="view_user", content_type__app_label="accounts").delete()
    with pytest.raises(UnknownPermissionError, match="migrate"):
        sync_role_permissions()

    report = sync_role_permissions(require_rows=False)

    assert report.not_yet_created == ("accounts.view_user",)
    assert "accounts.change_user" in granted(Role.SUPPORT_ADMIN)


# --- post_migrate -----------------------------------------------------------------------------


def last_app_config():
    return [c for c in apps.get_app_configs() if c.models_module is not None][-1]


def test_the_receiver_applies_the_table_after_the_last_app(monkeypatch):
    calls = []
    monkeypatch.setattr(
        role_permissions,
        "sync_role_permissions",
        lambda **kwargs: calls.append(kwargs) or role_permissions.SyncReport(),
    )

    for config in apps.get_app_configs():
        if config.models_module is not None:
            sync_after_migrate(config, using="default")

    assert calls == [{"require_rows": False, "using": "default"}]  # once, not per app


def test_the_receiver_is_connected_and_repairs_the_groups():
    from django.db.models.signals import post_migrate

    Group.objects.get(name=Role.SUPPORT_ADMIN).permissions.clear()
    Group.objects.get(name=Role.DATA_CURATOR).permissions.clear()

    post_migrate.send(sender=last_app_config(), app_config=last_app_config(), using="default")

    for role in (Role.SUPPORT_ADMIN, Role.DATA_CURATOR):
        assert granted(role) == set(ROLE_PERMISSIONS[role])


def test_the_receiver_warns_about_a_partly_migrated_database(caplog):
    Permission.objects.filter(codename="view_user", content_type__app_label="accounts").delete()

    with caplog.at_level("WARNING", logger="accounts.role_permissions"):
        sync_after_migrate(last_app_config(), using="default")

    assert "accounts.view_user" in caplog.text


# --- Commands ---------------------------------------------------------------------------------


def run(command: str, *args: str) -> str:
    out = io.StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


def test_the_command_reports_no_change_after_migrate():
    assert "beze změny" in run("sync_role_permissions")


def test_the_command_lists_what_it_changed_and_then_nothing():
    Group.objects.get(name=Role.SUPPORT_ADMIN).permissions.clear()
    Group.objects.get(name=Role.OWNER).permissions.add(Permission.objects.get(codename="view_user"))

    out = run("sync_role_permissions")

    assert "Správce uživatelů (support_admin):" in out
    assert "+ accounts.view_user" in out and "+ axes.delete_accessattempt" in out
    assert "Majitel zvířat (owner):" in out and "- accounts.view_user" in out
    assert "beze změny" in run("sync_role_permissions")


def test_the_command_dry_run_changes_nothing():
    Group.objects.get(name=Role.SUPPORT_ADMIN).permissions.clear()

    out = run("sync_role_permissions", "--dry-run")

    assert out.startswith("Zkouška (nic nezapsáno).") and "+ accounts.view_user" in out
    assert granted(Role.SUPPORT_ADMIN) == set()


def test_the_command_fails_with_a_clear_message_for_an_unknown_codename(monkeypatch):
    from accounts.management.commands import sync_role_permissions as command

    original = command.sync_role_permissions
    monkeypatch.setattr(
        command,
        "sync_role_permissions",
        lambda **kwargs: original({"support_admin": ("accounts.fly_user",)}, **kwargs),
    )

    with pytest.raises(CommandError, match="accounts.fly_user"):
        call_command("sync_role_permissions", stdout=io.StringIO())


# --- The printed matrix -----------------------------------------------------------------------


def test_the_matrix_is_a_markdown_table_of_the_roles_with_permissions():
    text = render_role_matrix()
    lines = text.splitlines()

    assert lines[0] == (
        "| Oprávnění | Kód | Správce uživatelů | Kurátor dat | Odborný revizor výživy |"
    )
    assert lines[1] == "|---|---|:---:|:---:|:---:|"
    assert "| zobrazit: uživatel | `accounts.view_user` | ✔ | – | – |" in lines
    assert (
        "| změnit: zdravotní stav (číselník) | `animals.change_healthcondition` | – | – | ✔ |"
        in lines
    )
    assert "| zobrazit: odborný zdroj | `catalog.view_scientificsource` | – | ✔ | ✔ |" in lines
    assert text.endswith(
        "Role bez jakéhokoli oprávnění v administraci: Majitel zvířat (`owner`), "
        "Veterinární lékař (`vet`).\n"
    )


def test_the_matrix_has_one_row_per_permission_and_is_deterministic():
    rows = [line for line in render_role_matrix().splitlines() if line.startswith("| ")][1:]
    entries = set().union(*ROLE_PERMISSIONS.values())
    assert len(rows) == len(entries)
    assert render_role_matrix() == render_role_matrix()


def test_the_command_prints_the_matrix():
    assert run("print_role_matrix") == render_role_matrix()


def test_the_matrix_follows_the_table_it_is_given():
    text = render_role_matrix({"a": ("accounts.view_user",), "b": ()})
    assert "| zobrazit: uživatel | `accounts.view_user` | ✔ |" in text
    assert "(`b`)" in text


# --- The document -------------------------------------------------------------------------------

DOCUMENT = BASE_DIR.parent / "docs" / "14-administrace.md"


def embedded_matrix() -> str:
    text = DOCUMENT.read_text(encoding="utf-8")
    start = "<!-- role-matrix:begin -->\n"
    end = "\n<!-- role-matrix:end -->"
    assert text.count(start) == text.count(end) == 1
    return text.split(start, 1)[1].split(end, 1)[0] + "\n"


def test_docs_14_embeds_the_current_matrix():
    """The table in the chapter is the output of ``print_role_matrix``, not a copy that rots."""
    assert embedded_matrix() == render_role_matrix()


def test_docs_14_names_every_role():
    text = DOCUMENT.read_text(encoding="utf-8")
    for role in Role:
        assert f"`{role.value}`" in text, role
