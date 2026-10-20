"""GDPR data export: a registry of per-app exporters (docs/07 §7.7).

Each app that stores personal data registers one exporter, usually in its
``AppConfig.ready()``::

    register_exporter("animals", export_animals)

An exporter takes the user and returns JSON-serialisable data (dicts, lists,
strings, numbers, booleans, ``None``; dates as ISO 8601 strings). It must never
return password hashes, tokens or other secrets.
"""

from collections.abc import Callable
from typing import Any

from django.utils import timezone

from .roles import ROLE_LABELS

Exporter = Callable[[Any], Any]

EXPORT_FORMAT = "barf-nutri-personal-data"
EXPORT_FORMAT_VERSION = 1

_exporters: dict[str, Exporter] = {}


def register_exporter(name: str, exporter: Exporter) -> None:
    """Register ``exporter`` under the section ``name`` of the export.

    Registering the same callable again is a no-op (``ready()`` may run twice).

    Raises:
        ValueError: ``name`` is empty or already taken by a different callable.
    """
    if not name:
        raise ValueError("Exporter name must not be empty.")
    current = _exporters.get(name)
    if current is not None and current is not exporter:
        raise ValueError(f"Exporter {name!r} is already registered.")
    _exporters[name] = exporter


def registered_exporters() -> tuple[str, ...]:
    """Return the registered section names, sorted."""
    return tuple(sorted(_exporters))


def build_export(user: Any) -> dict[str, Any]:
    """Assemble the personal data export of ``user``.

    Output: ``{"format", "format_version", "generated_at", "data": {section: ...}}``
    with sections in alphabetical order. Errors raised by an exporter propagate:
    an incomplete export must not look complete.
    """
    return {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "generated_at": timezone.localtime().isoformat(),
        "data": {name: _exporters[name](user) for name in registered_exporters()},
    }


def _iso(value: Any) -> str | None:
    return timezone.localtime(value).isoformat() if value is not None else None


def export_account(user: Any) -> dict[str, Any]:
    """Exporter of the ``accounts`` app: profile, roles and login records (no password).

    Login records are kept by django-axes under the e-mail: ``login_history`` (successful
    logins), ``failed_logins`` (current counters of failed attempts per IP address) and
    ``failed_login_log`` (single failed attempts, only when
    ``AXES_ENABLE_ACCESS_FAILURE_LOG`` is on). The data axes stores from the failed
    request (GET and POST parameters) are never exported.
    """
    from axes.models import AccessAttempt, AccessFailureLog, AccessLog

    logins = AccessLog.objects.filter(username=user.email).order_by("attempt_time")
    attempts = AccessAttempt.objects.filter(username=user.email).order_by("attempt_time")
    failures = AccessFailureLog.objects.filter(username=user.email).order_by("attempt_time")
    return {
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "date_joined": _iso(user.date_joined),
        "last_login": _iso(user.last_login),
        "is_active": user.is_active,
        "roles": [
            {"code": name, "label": ROLE_LABELS.get(name, name)}
            for name in user.groups.order_by("name").values_list("name", flat=True)
        ],
        "login_history": [
            {
                "login_at": _iso(entry.attempt_time),
                "logout_at": _iso(entry.logout_time),
                "ip_address": entry.ip_address,
                "user_agent": entry.user_agent,
            }
            for entry in logins
        ],
        "failed_logins": [
            {
                "last_attempt_at": _iso(entry.attempt_time),
                "failures": entry.failures_since_start,
                "ip_address": entry.ip_address,
                "user_agent": entry.user_agent,
            }
            for entry in attempts
        ],
        "failed_login_log": [
            {
                "attempt_at": _iso(entry.attempt_time),
                "ip_address": entry.ip_address,
                "user_agent": entry.user_agent,
                "locked_out": entry.locked_out,
            }
            for entry in failures
        ],
    }
