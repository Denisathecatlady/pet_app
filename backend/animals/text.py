"""Small Czech text helpers shared by the services and the chart module."""

from datetime import date

from django.utils.dateformat import format as format_date


def short_date(value: date) -> str:
    """Return ``date(2026, 10, 3)`` as ``"3. 10. 2026"``."""
    return format_date(value, "j. n. Y")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Return the Czech form of a noun for ``count``.

    Example: ``plural(2, "zdravotní stav", "zdravotní stavy", "zdravotních stavů")``
    → ``"zdravotní stavy"``. 1 → ``one``, 2–4 → ``few``, anything else (0, 5+) → ``many``.
    """
    if count == 1:
        return one
    if 2 <= count <= 4:
        return few
    return many
