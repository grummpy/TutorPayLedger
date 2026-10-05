"""Coverage math: weekends, closures, half-days, and the weekend-end rule."""

from datetime import date, time
from decimal import Decimal

import pytest

from tutor_pay_ledger.calendars.base import MemoryCalendar, SchoolDay
from tutor_pay_ledger.calendars.fixture import build_sample_district_calendar
from tutor_pay_ledger.coverage import (
    coverage_span_of_n,
    coverage_warning,
    effective_named_end,
    extend_by_n,
    iter_billable,
    session_weight,
)
from tutor_pay_ledger.models import DayKind, HalfDayPolicy, WeekendEndPolicy

WEEKDAYS = frozenset({0, 1, 2, 3, 4})
HALF = HalfDayPolicy.HALF_RATE
SKIP = HalfDayPolicy.SKIP


def _memory(items: dict[date, tuple[DayKind, str]]) -> MemoryCalendar:
    return MemoryCalendar(
        {day: SchoolDay(day, kind, name) for day, (kind, name) in items.items()}
    )


def test_weekend_never_bills_even_when_a_feed_says_in_session():
    class Mislabelled:
        def describe(self, day: date) -> SchoolDay:
            return SchoolDay(day, DayKind.IN_SESSION, "Saturday school")

    weight, described = session_weight(date(2026, 10, 17), Mislabelled(), WEEKDAYS, HALF)
    assert weight == 0
    assert described.kind == DayKind.WEEKEND


def test_holiday_is_skipped_and_half_day_policy_changes_the_weight():
    calendar = _memory(
        {
            date(2026, 10, 12): (DayKind.HOLIDAY, "Indigenous Peoples' Day"),
            date(2026, 10, 16): (DayKind.HALF_DAY, "Early release"),
        }
    )
    holiday, _ = session_weight(date(2026, 10, 12), calendar, WEEKDAYS, HALF)
    full, _ = session_weight(date(2026, 10, 13), calendar, WEEKDAYS, HALF)
    half, _ = session_weight(date(2026, 10, 16), calendar, WEEKDAYS, HALF)
    skipped, _ = session_weight(date(2026, 10, 16), calendar, WEEKDAYS, SKIP)
    assert holiday == 0
    assert full == 1
    assert half == Decimal("0.5")
    assert skipped == 0


def test_service_window_can_be_a_subset_of_weekdays():
    wednesdays = frozenset({2})
    calendar = MemoryCalendar()
    end = coverage_span_of_n(date(2026, 10, 8), 2, calendar, wednesdays, HALF)
    assert end == date(2026, 10, 21)
    days = [day for day, _, _ in iter_billable(date(2026, 10, 8), end, calendar, wednesdays, HALF)]
    assert days == [date(2026, 10, 14), date(2026, 10, 21)]


def test_extend_by_n_skips_weekends_holidays_and_respects_half_days():
    calendar = _memory(
        {
            date(2026, 10, 12): (DayKind.HOLIDAY, "Holiday"),
            date(2026, 10, 16): (DayKind.HALF_DAY, "Early release"),
        }
    )
    # Friday Oct 9, then five school weekdays.
    half_end = extend_by_n(date(2026, 10, 9), 5, calendar, WEEKDAYS, HALF)
    skip_end = extend_by_n(date(2026, 10, 9), 5, calendar, WEEKDAYS, SKIP)
    assert half_end == date(2026, 10, 19)  # Oct 16 counts
    assert skip_end == date(2026, 10, 20)  # Oct 16 does not count


def test_named_weekend_end_is_configurable():
    calendar = _memory({date(2026, 10, 19): (DayKind.HOLIDAY, "Closed Monday")})
    saturday = date(2026, 10, 17)
    rolled = effective_named_end(saturday, WeekendEndPolicy.ROLL_TO_MONDAY, calendar, WEEKDAYS, HALF)
    strict = effective_named_end(saturday, WeekendEndPolicy.STRICT, calendar, WEEKDAYS, HALF)
    nxt = effective_named_end(
        saturday, WeekendEndPolicy.ROLL_TO_NEXT_SESSION, calendar, WEEKDAYS, HALF
    )
    assert rolled == date(2026, 10, 19)
    assert strict == saturday
    assert nxt == date(2026, 10, 20)


def test_roll_to_next_session_stops_on_a_billed_half_day():
    calendar = _memory({date(2026, 10, 19): (DayKind.HALF_DAY, "Early Monday")})
    saturday = date(2026, 10, 17)
    kept = effective_named_end(
        saturday, WeekendEndPolicy.ROLL_TO_NEXT_SESSION, calendar, WEEKDAYS, HALF
    )
    skipped = effective_named_end(
        saturday, WeekendEndPolicy.ROLL_TO_NEXT_SESSION, calendar, WEEKDAYS, SKIP
    )
    assert kept == date(2026, 10, 19)
    assert skipped == date(2026, 10, 20)


def test_sunday_also_rolls_to_the_following_monday():
    calendar = MemoryCalendar()
    monday = effective_named_end(
        date(2026, 10, 18), WeekendEndPolicy.ROLL_TO_MONDAY, calendar, WEEKDAYS, HALF
    )
    assert monday == date(2026, 10, 19)


def test_warning_window_is_seven_calendar_days_inclusive():
    end = date(2026, 10, 16)
    assert coverage_warning(date(2026, 10, 8), end) is None
    assert coverage_warning(date(2026, 10, 9), end) == "Coverage ends within 7 days (7 days left)."
    assert coverage_warning(date(2026, 10, 15), end) == "Coverage ends tomorrow."
    assert coverage_warning(date(2026, 10, 16), end) == "Coverage ends today."
    assert coverage_warning(date(2026, 10, 17), end) is None


def test_sample_district_october_and_winter_break():
    calendar = build_sample_district_calendar()
    assert calendar.describe(date(2026, 10, 12)).kind == DayKind.HOLIDAY
    assert calendar.describe(date(2026, 10, 16)).kind == DayKind.HALF_DAY
    assert calendar.describe(date(2026, 10, 10)).kind == DayKind.WEEKEND
    assert calendar.describe(date(2026, 7, 6)).name == "Outside the sample school year"
    assert calendar.describe(date(2026, 8, 24)).kind == DayKind.IN_SESSION
    assert calendar.describe(date(2026, 9, 7)).name == "Labor Day"
    assert calendar.describe(date(2026, 12, 25)).name == "Christmas"
    assert calendar.describe(date(2027, 1, 1)).name == "New Year's Day"
    assert calendar.describe(date(2027, 3, 16)).name == "Spring break"
    assert calendar.describe(date(2027, 3, 26)).name == "Good Friday"
    assert calendar.describe(date(2027, 5, 31)).name == "Memorial Day"
    assert calendar.describe(date(2027, 6, 11)).kind == DayKind.HALF_DAY

    # Five school weekdays after the early-release Friday before winter break
    # walk through the recess and land on the first week of January.
    new_end = extend_by_n(date(2026, 12, 18), 3, calendar, WEEKDAYS, HALF)
    assert new_end == date(2027, 1, 6)


def test_extend_requires_a_positive_count():
    from tutor_pay_ledger.models import LedgerError

    with pytest.raises(LedgerError, match="at least 1"):
        extend_by_n(date(2026, 10, 16), 0, MemoryCalendar(), WEEKDAYS, HALF)


def test_cycle_constructor_rejects_a_weekend_window():
    from tutor_pay_ledger.ledger import PayCycle
    from tutor_pay_ledger.models import LedgerError

    with pytest.raises(LedgerError, match="Monday–Friday only"):
        PayCycle(
            id="cyc_bad",
            payee="Neighborhood piano",
            service="Piano",
            coverage_start=date(2026, 10, 5),
            weekdays=frozenset({5}),
            session_start=time(15, 30),
            session_end=time(16, 30),
            session_rate=Decimal("40.00"),
            named_end=date(2026, 10, 16),
        )
