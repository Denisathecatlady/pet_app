"""Reading settings from environment variables.

Settings modules use these helpers so that no secret ever lives in the
repository (docs/07 §7.7). Every helper reads ``os.environ`` at call time, so
settings modules evaluate the environment when they are imported.
"""

import os
import re
from collections.abc import Mapping
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

DATABASE_VARIABLES = (
    ("NAME", "POSTGRES_DB"),
    ("USER", "POSTGRES_USER"),
    ("PASSWORD", "POSTGRES_PASSWORD"),
    ("HOST", "POSTGRES_HOST"),
    ("PORT", "POSTGRES_PORT"),
)
DEFAULT_POSTGRES_PORT = "5432"


def env_str(name: str, default: str | None = None) -> str | None:
    """Return the stripped value of ``name``; unset or empty returns ``default``."""
    value = os.environ.get(name, "").strip()
    return value if value else default


def require_env(name: str) -> str:
    """Return the value of ``name``.

    Raises:
        ImproperlyConfigured: the variable is unset or empty.
    """
    value = env_str(name)
    if value is None:
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value


def env_bool(name: str, default: bool) -> bool:
    """Return ``name`` parsed as a boolean (1/0, true/false, yes/no, on/off).

    Raises:
        ImproperlyConfigured: the value is not one of the accepted words.
    """
    value = env_str(name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ImproperlyConfigured(f"Environment variable {name} must be a boolean, got {value!r}.")


def env_int(name: str, default: int) -> int:
    """Return ``name`` parsed as a non-negative integer.

    Raises:
        ImproperlyConfigured: the value is not a non-negative integer.
    """
    value = env_str(name)
    if value is None:
        return default
    if not value.isdigit():
        raise ImproperlyConfigured(f"Environment variable {name} must be a non-negative integer.")
    return int(value)


def env_list(name: str) -> list[str]:
    """Return ``name`` split on commas, without empty items (unset returns ``[]``)."""
    value = env_str(name, "") or ""
    return [item.strip() for item in value.split(",") if item.strip()]


def database_from_env(defaults: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build ``DATABASES["default"]`` for PostgreSQL from ``POSTGRES_*`` variables.

    Args:
        defaults: fallback values keyed by variable name (``POSTGRES_DB`` …) for
            local development and tests. ``None`` means production: every
            variable except ``POSTGRES_PORT`` (default 5432) is required.

    Returns:
        A Django database settings dictionary.

    Raises:
        ImproperlyConfigured: a required variable is missing.
    """
    config: dict[str, Any] = {
        "ENGINE": "django.db.backends.postgresql",
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
    for key, variable in DATABASE_VARIABLES:
        if defaults is not None:
            value = env_str(variable, defaults.get(variable))
        elif variable == "POSTGRES_PORT":
            value = env_str(variable, DEFAULT_POSTGRES_PORT)
        else:
            value = require_env(variable)
        if value is None:
            raise ImproperlyConfigured(f"Required environment variable {variable} is not set.")
        config[key] = value
    return config


ADMIN_URL_VARIABLE: Final = "DJANGO_ADMIN_URL"
DEFAULT_ADMIN_URL: Final = "admin/"
# Letters, digits and - _ . ~ in segments separated by slashes; ends with a slash.
_ADMIN_URL_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.~-]*(/[A-Za-z0-9_.~-]+)*/")
# First path segments used by the application itself: the administration must not hide them.
_RESERVED_ADMIN_SEGMENTS: Final = frozenset(
    {"ucet", "zvirata", "zdroje", "prehled", "podminky-uziti", "ochrana-osobnich-udaju", "static"}
)


def admin_url_from_env(*, production: bool) -> str:
    """Return the path of the administration from ``DJANGO_ADMIN_URL`` (docs/14 §14.4).

    Development and tests (``production=False``) fall back to ``admin/`` when the variable
    is unset. Production requires the variable and refuses the well-known ``admin/``: a
    hidden address is the first, cheap layer against scanners (it is not a replacement for
    the second factor and the access rules).

    Raises:
        ImproperlyConfigured: the value does not end with a slash, starts with a slash,
            contains characters other than letters, digits and ``-_.~/``, starts with a path
            of the application (``ucet/`` ...), or (production) is unset or ``admin/``.
    """
    value = env_str(ADMIN_URL_VARIABLE)
    if value is None:
        if production:
            raise ImproperlyConfigured(
                f"Required environment variable {ADMIN_URL_VARIABLE} is not set: choose a "
                "hard to guess path of the administration, e.g. 'sprava-x7k2q9/'."
            )
        return DEFAULT_ADMIN_URL
    if not _ADMIN_URL_PATTERN.fullmatch(value):
        raise ImproperlyConfigured(
            f"{ADMIN_URL_VARIABLE} must end with a slash, must not start with one and may "
            f"contain only letters, digits and -_.~/ (got {value!r})."
        )
    if value.split("/", 1)[0].lower() in _RESERVED_ADMIN_SEGMENTS:
        raise ImproperlyConfigured(
            f"{ADMIN_URL_VARIABLE} must not start with a path used by the application ({value!r})."
        )
    if production and value.lower() == DEFAULT_ADMIN_URL:
        raise ImproperlyConfigured(
            f"{ADMIN_URL_VARIABLE} must not be the well-known {DEFAULT_ADMIN_URL!r}."
        )
    return value
