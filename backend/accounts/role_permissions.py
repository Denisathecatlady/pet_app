"""Applying ``ROLE_PERMISSIONS`` to the groups (docs/14 §14.3).

``accounts.roles.ROLE_PERMISSIONS`` is the single authoritative table of what each role may do
in the administration. :func:`sync_role_permissions` makes the permissions of every group in it
exactly that list. It runs

* after every ``migrate`` (receiver ``sync_after_migrate``, once the permissions of all apps
  exist), so a deployment never leaves a role with stale permissions, and
* by hand: ``manage.py sync_role_permissions`` (``--dry-run`` shows the change).

It works on groups only. Users - superusers included - and their individual permissions are
never read or changed. :func:`render_role_matrix` prints the table as Markdown for docs/14.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from django.apps import apps
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import Group, Permission
from django.db import DEFAULT_DB_ALIAS, transaction

from .roles import ROLE_LABELS, ROLE_PERMISSIONS

logger = logging.getLogger(__name__)

ACTION_LABELS: Final = {"view": "zobrazit", "add": "přidat", "change": "změnit", "delete": "smazat"}
_ACTION_ORDER: Final = {action: number for number, action in enumerate(ACTION_LABELS)}
GRANTED: Final = "✔"
NOT_GRANTED: Final = "–"


class UnknownPermissionError(ValueError):
    """An entry of the role table names a permission that does not exist."""


@dataclass(frozen=True)
class SyncReport:
    """What :func:`sync_role_permissions` changed (or would change with ``dry_run``).

    ``added`` and ``removed`` map a role to the sorted 'app_label.codename' entries.
    ``not_yet_created`` lists permissions whose database rows do not exist yet (a partly
    migrated database); they are skipped and applied by the next run.
    """

    groups_created: tuple[str, ...] = ()
    added: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    removed: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    not_yet_created: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.groups_created or self.added or self.removed)


def defined_permissions() -> frozenset[str]:
    """Return every permission the installed models define, as 'app_label.codename'.

    Read from the model definitions, not from the database, so a typo in the role table is
    found even before the permission rows exist.
    """
    defined = set()
    for model in apps.get_models():
        opts = model._meta
        for action in opts.default_permissions:
            defined.add(f"{opts.app_label}.{get_permission_codename(action, opts)}")
        defined.update(f"{opts.app_label}.{codename}" for codename, _ in opts.permissions)
    return frozenset(defined)


def validate_matrix(matrix: Mapping[str, Iterable[str]] = ROLE_PERMISSIONS) -> None:
    """Check that every entry of the role table is a permission of an installed model.

    Raises:
        UnknownPermissionError: lists every unknown entry ('app_label.codename') and the role.
    """
    defined = defined_permissions()
    unknown = [
        f"{role}: {entry!r}"
        for role, entries in matrix.items()
        for entry in entries
        if entry not in defined
    ]
    if unknown:
        raise UnknownPermissionError(
            "Unknown permission in ROLE_PERMISSIONS (expected 'app_label.codename' of an "
            "installed model): " + "; ".join(unknown)
        )


def _key(permission: Permission) -> str:
    return f"{permission.content_type.app_label}.{permission.codename}"


def sync_role_permissions(
    matrix: Mapping[str, Iterable[str]] = ROLE_PERMISSIONS,
    *,
    dry_run: bool = False,
    require_rows: bool = True,
    using: str = DEFAULT_DB_ALIAS,
) -> SyncReport:
    """Make the permissions of each group in ``matrix`` exactly the listed ones.

    Idempotent: a second run changes nothing. Groups that are not in ``matrix`` are left
    alone; a group that is in it but does not exist is created. Superusers are not touched.

    Inputs: the role table (default ``ROLE_PERMISSIONS``); ``dry_run`` computes the report
    and writes nothing; ``require_rows=False`` skips permissions whose database rows are
    missing instead of failing (used right after ``migrate``, where a partly migrated
    database may not have them yet).

    Output: a :class:`SyncReport`.

    Raises:
        UnknownPermissionError: an entry names no permission of an installed model, or (with
            ``require_rows``) its database row is missing - run ``migrate``.
    """
    matrix = {role: tuple(entries) for role, entries in matrix.items()}
    validate_matrix(matrix)
    wanted_keys = {entry for entries in matrix.values() for entry in entries}
    rows = {
        _key(permission): permission
        for permission in Permission.objects.using(using).select_related("content_type")
        if _key(permission) in wanted_keys
    }
    absent = sorted(wanted_keys - rows.keys())
    if absent and require_rows:
        raise UnknownPermissionError(
            "The permission rows do not exist yet (run 'manage.py migrate'): " + ", ".join(absent)
        )

    created: list[str] = []
    added: dict[str, tuple[str, ...]] = {}
    removed: dict[str, tuple[str, ...]] = {}
    with transaction.atomic(using=using):
        for role, entries in matrix.items():
            group = Group.objects.using(using).filter(name=role).first()
            if group is None:
                created.append(role)
                if not dry_run:
                    group = Group.objects.using(using).create(name=role)
            current = (
                {_key(p): p for p in group.permissions.select_related("content_type")}
                if group is not None
                else {}
            )
            wanted = set(entries)
            to_add = sorted(key for key in wanted - current.keys() if key in rows)
            to_remove = sorted(current.keys() - wanted)
            if to_add:
                added[role] = tuple(to_add)
            if to_remove:
                removed[role] = tuple(to_remove)
            if not dry_run and group is not None:
                group.permissions.add(*(rows[key] for key in to_add))
                group.permissions.remove(*(current[key] for key in to_remove))
    report = SyncReport(tuple(created), added, removed, tuple(absent))
    if report.changed and not dry_run:
        logger.info("Role permissions synchronised: %s", report)
    return report


def sync_after_migrate(sender: Any, using: str = DEFAULT_DB_ALIAS, **kwargs: Any) -> None:
    """``post_migrate`` receiver: apply the role table once, after the last app's permissions.

    Django creates the permissions of one app per ``post_migrate`` signal, so the table can
    only be applied completely after the last app with models.
    """
    last = [config for config in apps.get_app_configs() if config.models_module is not None][-1]
    if sender.label == last.label:
        report = sync_role_permissions(require_rows=False, using=using)
        if report.not_yet_created:
            logger.warning(
                "Role permissions not applied yet (database not fully migrated): %s",
                ", ".join(report.not_yet_created),
            )


# --- The table as Markdown (docs/14 §14.3) ----------------------------------------------------


def _permission_label(entry: str) -> str:
    """Return 'zobrazit: uživatel' for 'accounts.view_user'.

    A permission a model declares itself (``Meta.permissions``, e.g. deciding a request) gets
    its own name; anything else is shown as its code.
    """
    app_label, codename = entry.split(".", 1)
    action, _, model_name = codename.partition("_")
    if action in ACTION_LABELS and model_name:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            return codename
        return f"{ACTION_LABELS[action]}: {model._meta.verbose_name}"
    for model in apps.get_app_config(app_label).get_models():
        for code, name in model._meta.permissions:
            if code == codename:
                return str(name)
    return codename


def _sort_key(entry: str) -> tuple[str, str, int, str]:
    app_label, codename = entry.split(".", 1)
    action, _, model_name = codename.partition("_")
    return (app_label, model_name, _ACTION_ORDER.get(action, len(_ACTION_ORDER)), codename)


def render_role_matrix(matrix: Mapping[str, Iterable[str]] = ROLE_PERMISSIONS) -> str:
    """Return the role table as a Markdown table plus a note on roles without permissions.

    Rows are permissions (ordered by app, model and action), columns are the roles that have
    at least one permission, a cell is ``✔`` or ``–``. Deterministic, so a test can compare
    it with the copy in docs/14.
    """
    matrix = {role: frozenset(entries) for role, entries in matrix.items()}
    with_permissions = [role for role, entries in matrix.items() if entries]
    without = [role for role, entries in matrix.items() if not entries]
    entries = sorted(set().union(*matrix.values()), key=_sort_key)

    def role_label(role: str) -> str:
        return ROLE_LABELS.get(role, role)

    lines = [
        "| Oprávnění | Kód | " + " | ".join(role_label(role) for role in with_permissions) + " |",
        "|---|---|" + ":---:|" * len(with_permissions),
    ]
    for entry in entries:
        cells = (GRANTED if entry in matrix[role] else NOT_GRANTED for role in with_permissions)
        lines.append(f"| {_permission_label(entry)} | `{entry}` | " + " | ".join(cells) + " |")
    if without:
        names = ", ".join(f"{role_label(role)} (`{role}`)" for role in without)
        lines += ["", f"Role bez jakéhokoli oprávnění v administraci: {names}."]
    return "\n".join(lines) + "\n"
