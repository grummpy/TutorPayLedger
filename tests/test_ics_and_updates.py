"""ICS parser and the offline calendar-update hook."""

from datetime import date
from decimal import Decimal

from tutor_pay_ledger.calendars.base import MemoryCalendar, SchoolDay
from tutor_pay_ledger.calendars.fixture import build_sample_district_calendar
from tutor_pay_ledger.calendars.ics import parse_ics, read_sample_ics
from tutor_pay_ledger.calendars.updates import (
    CalendarRevision,
    ManualRevisionHook,
    NullCalendarUpdateHook,
    apply_revision,
)
from tutor_pay_ledger.coverage import session_weight
from tutor_pay_ledger.ledger import project
from tutor_pay_ledger.models import DayKind, HalfDayPolicy
from tutor_pay_ledger.seed import build_seed_ledger

WEEKDAYS = frozenset({0, 1, 2, 3, 4})
HALF = HalfDayPolicy.HALF_RATE

FOLDED = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261014T150000
DTEND:20261014T160000
SUMMARY:Staff meeting
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261015
SUMMARY:Early release
 — conferences
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261017
DTEND;VALUE=DATE:20261020
SUMMARY:Long weekend
CATEGORIES:BREAK
END:VEVENT
END:VCALENDAR
"""


def test_parser_unfolds_lines_ignores_timed_events_and_keeps_weekends():
    calendar = parse_ics(FOLDED)
    assert calendar.describe(date(2026, 10, 14)).kind == DayKind.IN_SESSION
    thursday = calendar.describe(date(2026, 10, 15))
    assert thursday.kind == DayKind.HALF_DAY
    assert "conferences" in (thursday.name or "")
    # Sat Oct 17 through Tue Oct 20 exclusive → Sat, Sun, Mon. Weekend stays weekend.
    assert calendar.describe(date(2026, 10, 17)).kind == DayKind.WEEKEND
    assert calendar.describe(date(2026, 10, 19)).kind == DayKind.BREAK
    weight, _ = session_weight(date(2026, 10, 17), calendar, WEEKDAYS, HALF)
    assert weight == 0


def test_sample_fragment_matches_the_fixture_inside_the_seed_window():
    fixture = build_sample_district_calendar()
    fragment = parse_ics(read_sample_ics())
    ledger = build_seed_ledger()
    cycle = ledger.cycles[0]
    on_fixture = project(cycle, fixture, date(2026, 10, 5), ledger.payments)
    on_fragment = project(cycle, fragment, date(2026, 10, 5), ledger.payments)
    assert on_fixture.total_units == on_fragment.total_units == Decimal("13.5")
    assert on_fragment.remaining_units == Decimal("8.5")
    # The fragment has no school-year bounds, so summer weekdays stay in session.
    assert fragment.describe(date(2026, 7, 6)).kind == DayKind.IN_SESSION
    assert fixture.describe(date(2026, 7, 6)).kind == DayKind.BREAK


def test_null_hook_is_a_noop_and_a_manual_revision_can_close_a_day():
    assert NullCalendarUpdateHook().poll() is None
    revision = CalendarRevision(
        source_name="inbox drop",
        observed_on=date(2026, 10, 10),
        summary="Oct 15 became a teacher workday.",
        overrides=(SchoolDay(date(2026, 10, 15), DayKind.HOLIDAY, "Teacher workday"),),
    )
    hook = ManualRevisionHook(revision)
    found = hook.poll()
    assert found is revision
    assert hook.poll() is None

    updated = apply_revision(MemoryCalendar(), found)
    weight, described = session_weight(date(2026, 10, 15), updated, WEEKDAYS, HALF)
    assert weight == 0
    assert described.name == "Teacher workday"
    # A revision cannot turn Saturday into a session.
    weekend_revision = CalendarRevision(
        source_name="bad feed",
        observed_on=date(2026, 10, 10),
        summary="ignore",
        overrides=(SchoolDay(date(2026, 10, 17), DayKind.IN_SESSION, "nope"),),
    )
    overlaid = apply_revision(MemoryCalendar(), weekend_revision)
    assert overlaid.describe(date(2026, 10, 17)).kind == DayKind.WEEKEND
