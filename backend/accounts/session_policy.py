"""Time limits of staff sessions (docs/14 §14.5).

A signed-in staff user (``User.is_staff``) is signed out

* after ``settings.STAFF_SESSION_IDLE_SECONDS`` without a request (default 30 minutes), and
* after ``settings.STAFF_SESSION_MAX_SECONDS`` since the password sign-in, however active the
  user is (default 12 hours).

The sign-in time and the time of the last request live in the session. A session of a staff
user without a sign-in time (it did not go through the sign-in of this application) counts
as expired. All time is read through :func:`now_seconds`, which tests patch.
"""

import time
from collections.abc import MutableMapping
from typing import Any, Final

from django.conf import settings
from django.http import HttpRequest

SESSION_LOGIN_AT: Final = "staff_session_login_at"
SESSION_LAST_SEEN: Final = "staff_session_last_seen"

IDLE: Final = "idle"
TOO_OLD: Final = "too_old"


def now_seconds() -> int:
    """Return the current time in whole seconds since the epoch (the policy's only clock)."""
    return int(time.time())


def start_session(request: HttpRequest) -> None:
    """Record the sign-in time in the session (called on every sign-in)."""
    session = getattr(request, "session", None)
    if session is None:
        return
    now = now_seconds()
    session[SESSION_LOGIN_AT] = now
    session[SESSION_LAST_SEEN] = now


def expiry_reason(session: MutableMapping[str, Any]) -> str | None:
    """Return ``IDLE`` or ``TOO_OLD`` when the session is over its limits, else ``None``.

    Does not change the session. A missing sign-in time or last-seen time is treated as
    ``TOO_OLD``.
    """
    now = now_seconds()
    login_at = session.get(SESSION_LOGIN_AT)
    last_seen = session.get(SESSION_LAST_SEEN)
    if not isinstance(login_at, int) or not isinstance(last_seen, int):
        return TOO_OLD
    if now - login_at > settings.STAFF_SESSION_MAX_SECONDS:
        return TOO_OLD
    if now - last_seen > settings.STAFF_SESSION_IDLE_SECONDS:
        return IDLE
    return None


def touch(session: MutableMapping[str, Any]) -> None:
    """Record that the user is active now (call only for a session that has not expired)."""
    session[SESSION_LAST_SEEN] = now_seconds()


def _count(number: int, forms: tuple[str, str, str]) -> str:
    """Return ``number`` with the Czech noun form for 'more than ...' (1 / 2-4 / 5+)."""
    form = forms[0] if number == 1 else forms[1] if 2 <= number <= 4 else forms[2]
    return f"{number} {form}"


def duration_text(seconds: int) -> str:
    """Return a duration as Czech text in the accusative: '30 minut', '12 hodin', '1 hodinu'."""
    if seconds % 3600 == 0:
        return _count(seconds // 3600, ("hodinu", "hodiny", "hodin"))
    if seconds % 60 == 0:
        return _count(seconds // 60, ("minutu", "minuty", "minut"))
    return _count(seconds, ("sekundu", "sekundy", "sekund"))


def expiry_message(reason: str) -> str:
    """Return the Czech message shown on the sign-in page after a forced sign-out."""
    if reason == IDLE:
        return (
            "Z bezpečnostních důvodů jsme vás odhlásili, protože jste byli déle než "
            f"{duration_text(settings.STAFF_SESSION_IDLE_SECONDS)} nečinní. "
            "Přihlaste se prosím znovu."
        )
    return (
        "Z bezpečnostních důvodů jsme vás odhlásili, protože od přihlášení uplynulo více než "
        f"{duration_text(settings.STAFF_SESSION_MAX_SECONDS)}. Přihlaste se prosím znovu."
    )
