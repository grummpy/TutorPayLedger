"""Sample US school-year calendar.

Sample District is fictional. The dates are a typical US school year
(2026–27): federal-style holidays, a Thanksgiving recess, winter and spring
breaks, and a few early-release days. They are fixtures for demos and tests,
not a claim about any real district.

Weekdays inside the year that are not listed are regular instructional days.
Weekdays outside the year are a break ("Outside the sample school year"),
so summer is not billed by accident. Weekends are weekends even inside the year.
"""

from __future__ import annotations

from datetime import date, timedelta

from tutor_pay_ledger.calendars.base import SchoolDay
from tutor_pay_ledger.models import DayKind

SAMPLE_CALENDAR_NAME = "Sample District 2026–27"
SAMPLE_YEAR_START = date(2026, 8, 24)  # Monday, first day
SAMPLE_YEAR_END = date(2027, 6, 11)  # Friday, last day (half day)
OUTSIDE_YEAR = "Outside the sample school year"


def _range(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


class FixtureSchoolCalendar:
    """The bundled Sample District calendar."""

    def __init__(self, closures: dict[date, SchoolDay]) -> None:
        self.label = SAMPLE_CALENDAR_NAME
        self._closures = closures

    def describe(self, day: date) -> SchoolDay:
        if day.weekday() >= 5:
            return SchoolDay(day, DayKind.WEEKEND, None)
        if day < SAMPLE_YEAR_START or day > SAMPLE_YEAR_END:
            return SchoolDay(day, DayKind.BREAK, OUTSIDE_YEAR)
        listed = self._closures.get(day)
        if listed is not None:
            return listed
        return SchoolDay(day, DayKind.IN_SESSION, None)


def _closure(kind: DayKind, name: str, start: str, end: str | None = None) -> list[tuple[date, SchoolDay]]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end or start)
    return [(day, SchoolDay(day, kind, name)) for day in _range(first, last)]


def build_sample_district_calendar() -> FixtureSchoolCalendar:
    """Return the sample year. Holidays win over breaks if a date is repeated."""

    entries: list[tuple[date, SchoolDay]] = []
    entries += _closure(DayKind.HOLIDAY, "Labor Day", "2026-09-07")
    entries += _closure(DayKind.HOLIDAY, "Indigenous Peoples' Day", "2026-10-12")
    entries += _closure(DayKind.HOLIDAY, "Veterans Day", "2026-11-11")
    entries += _closure(DayKind.BREAK, "Thanksgiving recess", "2026-11-25")
    entries += _closure(DayKind.HOLIDAY, "Thanksgiving", "2026-11-26")
    entries += _closure(DayKind.BREAK, "Thanksgiving recess", "2026-11-27")
    entries += _closure(DayKind.HALF_DAY, "Early release — before winter break", "2026-12-18")
    entries += _closure(DayKind.BREAK, "Winter break", "2026-12-21", "2026-12-24")
    entries += _closure(DayKind.HOLIDAY, "Christmas", "2026-12-25")
    entries += _closure(DayKind.BREAK, "Winter break", "2026-12-26", "2026-12-31")
    entries += _closure(DayKind.HOLIDAY, "New Year's Day", "2027-01-01")
    entries += _closure(DayKind.HOLIDAY, "Martin Luther King Jr. Day", "2027-01-18")
    entries += _closure(DayKind.HOLIDAY, "Presidents Day", "2027-02-15")
    entries += _closure(DayKind.BREAK, "Spring break", "2027-03-15", "2027-03-19")
    entries += _closure(DayKind.HOLIDAY, "Good Friday", "2027-03-26")
    entries += _closure(DayKind.HOLIDAY, "Memorial Day", "2027-05-31")
    entries += _closure(DayKind.HALF_DAY, "Early release — parent conferences", "2026-10-16")
    entries += _closure(DayKind.HALF_DAY, "Last day of school", "2027-06-11")

    closures: dict[date, SchoolDay] = {}
    for day, described in entries:
        # Later rows replace earlier ones. Half-days are listed after breaks
        # only when they should win; holidays are applied in the list order
        # and are not repeated as half-days.
        closures[day] = described
    return FixtureSchoolCalendar(closures)


class FixtureCalendarProvider:
    """Default provider: the bundled sample school year. No network."""

    name = "sample-us-school-year"

    def load(self) -> FixtureSchoolCalendar:
        return build_sample_district_calendar()
