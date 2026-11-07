"""The pure date arithmetic of the deadlines of data subject requests (docs/14 §14.12)."""

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from accounts.deadlines import (
    DUE_SOON_DAYS,
    DeadlineKind,
    add_months,
    deadline_state,
    default_due_date,
)

dates = st.dates(min_value=date(1990, 1, 1), max_value=date(2080, 12, 31))


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2026, 10, 22), 1, date(2026, 11, 22)),
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # the end of a shorter month
        (date(2024, 1, 31), 1, date(2024, 2, 29)),  # leap year
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),  # across the year
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 3, 31), 1, date(2026, 4, 30)),
        (date(2026, 5, 31), 0, date(2026, 5, 31)),
        (date(2026, 1, 15), 24, date(2028, 1, 15)),
    ],
)
def test_add_months(day, months, expected):
    assert add_months(day, months) == expected


def test_negative_months_are_refused():
    with pytest.raises(ValueError):
        add_months(date(2026, 1, 1), -1)


def test_the_default_due_date_is_the_period_after_the_day_of_receipt():
    assert default_due_date(date(2026, 10, 22), 1) == date(2026, 11, 22)
    assert default_due_date(date(2026, 10, 22), 2) == date(2026, 12, 22)


@given(day=dates, months=st.integers(min_value=0, max_value=48))
def test_the_result_is_that_many_months_later_and_never_earlier(day, months):
    result = add_months(day, months)

    assert result >= day
    assert (result.year * 12 + result.month) - (day.year * 12 + day.month) == months
    assert result.day <= day.day
    assert result.day == day.day or result.day >= 28  # only the end of the month is clamped


@given(day=dates)
def test_a_month_never_gives_more_than_31_days(day):
    assert timedelta(days=28) <= add_months(day, 1) - day <= timedelta(days=31)


@given(day=dates, months=st.integers(min_value=0, max_value=24))
def test_it_is_deterministic(day, months):
    assert add_months(day, months) == add_months(day, months)


TODAY = date(2026, 10, 22)


def test_a_finished_request_is_done_whatever_the_date():
    assert deadline_state(TODAY - timedelta(days=100), TODAY, finished=True).kind is (
        DeadlineKind.DONE
    )


@pytest.mark.parametrize(
    ("days_left", "kind"),
    [
        (-30, DeadlineKind.OVERDUE),
        (-1, DeadlineKind.OVERDUE),
        (0, DeadlineKind.SOON),  # due today is not overdue yet
        (1, DeadlineKind.SOON),
        (DUE_SOON_DAYS, DeadlineKind.SOON),
        (DUE_SOON_DAYS + 1, DeadlineKind.OK),
        (60, DeadlineKind.OK),
    ],
)
def test_the_state_of_an_open_request(days_left, kind):
    state = deadline_state(TODAY + timedelta(days=days_left), TODAY, finished=False)

    assert state.kind is kind
    assert state.days == abs(days_left)


def test_the_soon_window_can_be_changed():
    due = TODAY + timedelta(days=3)

    assert deadline_state(due, TODAY, finished=False, soon_days=2).kind is DeadlineKind.OK
    assert deadline_state(due, TODAY, finished=False, soon_days=3).kind is DeadlineKind.SOON


@given(due=dates, today=dates)
def test_overdue_exactly_when_the_deadline_is_before_today(due, today):
    state = deadline_state(due, today, finished=False)

    assert (state.kind is DeadlineKind.OVERDUE) == (due < today)
