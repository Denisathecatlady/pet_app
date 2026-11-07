"""Pure date arithmetic for the deadlines of data subject requests (docs/14 §14.12).

No Django, no database, no clock: every function gets the dates it needs, so the rules are
easy to test. The length of the period is NOT decided here (``settings.DATA_SUBJECT_REQUEST_
PERIOD_MONTHS``, a working value for the lawyer, docs/12 §12.8).
"""

import calendar
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Final

# A request that is still open and due within this many days is flagged as approaching. A
# working value of the operator, not a legal period.
DUE_SOON_DAYS: Final = 7


def add_months(day: date, months: int) -> date:
    """Return ``day`` moved by ``months`` calendar months, clamped to the end of the month.

    Example: 31 January plus one month is 28 (or 29) February; 30 November plus three months
    is 28 (or 29) February.

    Raises:
        ValueError: ``months`` is negative.
    """
    if months < 0:
        raise ValueError("The number of months must not be negative.")
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def default_due_date(received_on: date, months: int) -> date:
    """Return the standard deadline of a request received on ``received_on``.

    Inputs: the day the request was received and the length of the period in months
    (``settings.DATA_SUBJECT_REQUEST_PERIOD_MONTHS``). Output: the same day ``months`` later.
    """
    return add_months(received_on, months)


class DeadlineKind(Enum):
    DONE = "done"
    OVERDUE = "overdue"
    SOON = "soon"
    OK = "ok"


@dataclass(frozen=True)
class Deadline:
    """Where a request stands against its deadline.

    ``days`` is the number of days past the deadline (``OVERDUE``) or left until it (``SOON``,
    ``OK``); 0 for ``DONE``. A request due today is not overdue yet (``SOON`` with 0 days).
    """

    kind: DeadlineKind
    days: int = 0


def deadline_state(
    due_on: date, today: date, *, finished: bool, soon_days: int = DUE_SOON_DAYS
) -> Deadline:
    """Classify a request against its deadline: done, overdue, due soon or in time."""
    if finished:
        return Deadline(DeadlineKind.DONE)
    left = (due_on - today).days
    if left < 0:
        return Deadline(DeadlineKind.OVERDUE, -left)
    return Deadline(DeadlineKind.SOON if left <= soon_days else DeadlineKind.OK, left)
