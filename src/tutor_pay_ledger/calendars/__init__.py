"""School calendar providers.

The ledger asks a provider whether a weekday is a full session, a half-day,
or closed. Weekends are never sessions, regardless of what a feed says.
"""

from tutor_pay_ledger.calendars.base import (
    CalendarProvider,
    MemoryCalendar,
    OverlayCalendar,
    SchoolCalendar,
    SchoolDay,
)
from tutor_pay_ledger.calendars.fixture import (
    SAMPLE_CALENDAR_NAME,
    SAMPLE_YEAR_END,
    SAMPLE_YEAR_START,
    FixtureCalendarProvider,
    build_sample_district_calendar,
)
from tutor_pay_ledger.calendars.ics import (
    IcsFileProvider,
    SampleIcsProvider,
    parse_ics,
    read_sample_ics,
)
from tutor_pay_ledger.calendars.updates import (
    CalendarRevision,
    CalendarUpdateHook,
    ManualRevisionHook,
    NullCalendarUpdateHook,
    apply_revision,
)

__all__ = [
    "CalendarProvider",
    "CalendarRevision",
    "CalendarUpdateHook",
    "FixtureCalendarProvider",
    "IcsFileProvider",
    "ManualRevisionHook",
    "MemoryCalendar",
    "NullCalendarUpdateHook",
    "OverlayCalendar",
    "SAMPLE_CALENDAR_NAME",
    "SAMPLE_YEAR_END",
    "SAMPLE_YEAR_START",
    "SampleIcsProvider",
    "SchoolCalendar",
    "SchoolDay",
    "apply_revision",
    "build_sample_district_calendar",
    "parse_ics",
    "read_sample_ics",
]
