"""Hook for a bot that tracks school-calendar updates.

The default hook is a stub: it never opens a socket and it never returns a
change. A real bot would poll a published ICS URL, a school-site export, or
an inbox drop, diff it against the calendar in use, and return a revision.
Merge the revision with :func:`apply_revision`. The ledger store does not
call the network on your behalf.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from tutor_pay_ledger.calendars.base import OverlayCalendar, SchoolCalendar, SchoolDay


class CalendarRevision:
    """A batch of school-day changes observed by a bot or typed in by hand."""

    def __init__(
        self,
        *,
        source_name: str,
        observed_on: date,
        summary: str,
        overrides: tuple[SchoolDay, ...] | list[SchoolDay],
    ) -> None:
        if not source_name.strip():
            raise ValueError("A calendar revision needs a source name.")
        self.source_name = source_name.strip()
        self.observed_on = observed_on
        self.summary = summary.strip()
        self.overrides = tuple(overrides)

    def __repr__(self) -> str:
        return (
            f"CalendarRevision({self.source_name!r}, {self.observed_on.isoformat()}, "
            f"{len(self.overrides)} days)"
        )


class CalendarUpdateHook(Protocol):
    """Implemented by a calendar-watching bot.

    ``poll`` returns a revision when the source has something new, or ``None``
    when it does not. Implementations used in this package stay offline.
    """

    def poll(self) -> CalendarRevision | None:
        """Return newly observed changes, or ``None``."""


class NullCalendarUpdateHook:
    """Stub hook. Polling it is always a no-op and never uses the network."""

    name = "null"

    def poll(self) -> CalendarRevision | None:
        return None


class ManualRevisionHook:
    """Holds at most one revision and yields it on the next poll.

    Use this in tests, or as the place a human (or a bot running elsewhere)
    drops a revision the CLI can apply later. The revision is consumed once.
    """

    name = "manual"

    def __init__(self, revision: CalendarRevision | None = None) -> None:
        self.revision = revision

    def poll(self) -> CalendarRevision | None:
        found = self.revision
        self.revision = None
        return found


def apply_revision(calendar: SchoolCalendar, revision: CalendarRevision) -> OverlayCalendar:
    """Overlay a revision on a calendar. Weekend overrides are ignored."""

    overrides = {item.day: item for item in revision.overrides}
    return OverlayCalendar(calendar, overrides)
