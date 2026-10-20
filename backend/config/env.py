"""Reading settings from environment variables.

Settings modules use these helpers so that no secret ever lives in the
repository (docs/07 §7.7). Every helper reads ``os.environ`` at call time, so
settings modules evaluate the environment when they are imported.
"""

import os
from collections.abc import Mapping
from typing import Any

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
