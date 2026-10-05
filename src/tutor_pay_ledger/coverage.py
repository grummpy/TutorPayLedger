"""Coverage math for weekday services.

Rules, in order:

1. Saturday and Sunday are never billable. They never consume an
   extend-by-N count, even if a calendar feed labels them as in session.
2. A full closure (holiday or break) is not billable and does not consume
   an extend-by-N count.
3. A half-day is billable at half the session rate, and consumes one
   extend-by-N count, when the policy is ``half_rate``. When the policy is
   ``skip``, a half-day is ignored for both billing and the count.
4. The service's weekday window is a subset of Monday–Friday. A Wednesday
   lesson does not bill on Monday.
5. A named end date that falls on a weekend moves according to
   ``WeekendEndPolicy``. The default lands on the following Monday.
6. "Within 7 days" is seven calendar days, inclusive, measured to the
   effective end date. It is not seven school days.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from tutor_pay_ledger.calendars.base import SchoolCalendar, SchoolDay
from tutor_pay_ledger.models import (
    MONEY,
    DayKind,
    HalfDayPolicy,
    LedgerError,
    WeekendEndPolicy,
)

WARNING_WITHIN_DAYS = 7
_SEARCH_HORIZON_DAYS = 366 * 3
_FULL = Decimal("1")
_HALF = Decimal("0.5")
_NONE = Decimal("0")


def session_weight(
    day: date,
    calendar: SchoolCalendar,
    weekdays: frozenset[int],
    half_day_policy: HalfDayPolicy,
) -> tuple[Decimal, SchoolDay]:
    """Return ``(weight, school day)``. Weight is 1, 0.5, or 0."""

    described = calendar.describe(day)
    if day.weekday() >= 5:
        if described.kind != DayKind.WEEKEND:
            described = SchoolDay(day, DayKind.WEEKEND, described.name)
        return _NONE, described
    if day.weekday() not in weekdays:
        return _NONE, described
    if described.kind in {DayKind.HOLIDAY, DayKind.BREAK, DayKind.WEEKEND}:
        return _NONE, described
    if described.kind == DayKind.HALF_DAY:
        if half_day_policy == HalfDayPolicy.SKIP:
            return _NONE, described
        return _HALF, described
    if described.kind == DayKind.IN_SESSION:
        return _FULL, described
    return _NONE, described


def following_monday(day: date) -> date:
    """The Monday after a Saturday or Sunday. Weekdays return themselves."""

    if day.weekday() < 5:
        return day
    return day + timedelta(days=(7 - day.weekday()))


def effective_named_end(
    named_end: date,
    policy: WeekendEndPolicy,
    calendar: SchoolCalendar,
    weekdays: frozenset[int],
    half_day_policy: HalfDayPolicy,
) -> date:
    """Apply the weekend-end rule to a named coverage end date."""

    if named_end.weekday() < 5 or policy == WeekendEndPolicy.STRICT:
        return named_end
    monday = following_monday(named_end)
    if policy == WeekendEndPolicy.ROLL_TO_MONDAY:
        return monday
    if policy == WeekendEndPolicy.ROLL_TO_NEXT_SESSION:
        cursor = monday
        limit = named_end + timedelta(days=_SEARCH_HORIZON_DAYS)
        while cursor <= limit:
            weight, _ = session_weight(cursor, calendar, weekdays, half_day_policy)
            if weight > 0:
                return cursor
            cursor += timedelta(days=1)
        raise LedgerError(
            "No billable session within three years after the weekend end date."
        )
    raise LedgerError(f"Unknown weekend end policy {policy!r}.")


def extend_by_n(
    after: date,
    count: int,
    calendar: SchoolCalendar,
    weekdays: frozenset[int],
    half_day_policy: HalfDayPolicy,
) -> date:
    """Date of the ``count``-th billable weekday strictly after ``after``.

    Weekends, holidays, breaks, and skipped half-days do not consume ``count``.
    A half-day under ``half_rate`` consumes one.
    """

    if count < 1:
        raise LedgerError("Extend-by count must be at least 1.")
    found = 0
    cursor = after + timedelta(days=1)
    limit = after + timedelta(days=_SEARCH_HORIZON_DAYS)
    last: date | None = None
    while found < count:
        if cursor > limit:
            raise LedgerError(
                f"Could not find {count} school weekdays after {after.isoformat()}."
            )
        weight, _ = session_weight(cursor, calendar, weekdays, half_day_policy)
        if weight > 0:
            found += 1
            last = cursor
        cursor += timedelta(days=1)
    assert last is not None
    return last


def coverage_span_of_n(
    start: date,
    count: int,
    calendar: SchoolCalendar,
    weekdays: frozenset[int],
    half_day_policy: HalfDayPolicy,
) -> date:
    """Last date of a window that contains ``count`` billable weekdays from ``start``."""

    if count < 1:
        raise LedgerError("Weekday count must be at least 1.")
    weight, _ = session_weight(start, calendar, weekdays, half_day_policy)
    if weight > 0 and count == 1:
        return start
    if weight > 0:
        return extend_by_n(start, count - 1, calendar, weekdays, half_day_policy)
    return extend_by_n(start - timedelta(days=1), count, calendar, weekdays, half_day_policy)


def iter_billable(
    start: date,
    end: date,
    calendar: SchoolCalendar,
    weekdays: frozenset[int],
    half_day_policy: HalfDayPolicy,
):
    """Yield ``(day, weight, school day)`` for billable dates in the inclusive span."""

    if end < start:
        return
    cursor = start
    while cursor <= end:
        weight, described = session_weight(cursor, calendar, weekdays, half_day_policy)
        if weight > 0:
            yield cursor, weight, described
        cursor += timedelta(days=1)


def coverage_warning(as_of: date, effective_end: date) -> str | None:
    """Warn when coverage is still open and ends within seven calendar days."""

    days_left = (effective_end - as_of).days
    if days_left < 0 or days_left > WARNING_WITHIN_DAYS:
        return None
    if days_left == 0:
        return "Coverage ends today."
    if days_left == 1:
        return "Coverage ends tomorrow."
    return f"Coverage ends within 7 days ({days_left} days left)."


def units_amount(weight: Decimal, rate: Decimal) -> Decimal:
    return (weight * rate).quantize(MONEY)
