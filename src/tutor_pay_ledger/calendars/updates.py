"""Hook for a bot that tracks school-calendar updates.

The default hook is a stub: it never opens a socket and it never returns a
change. A real bot would poll a published ICS URL, a school-site export, or
an inbox drop, diff it against the calendar in use, and return a revision.
Merge the revision with :func:`apply_revision`. The ledger store does not
call the network on your behalf.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from tutor_pay_ledger.calendars.base import OverlayCalendar, SchoolCalendar, SchoolDay
from tutor_pay_ledger.models import DayKind, LedgerError


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


@dataclass(frozen=True)
class RevisionDayChange:
    """One requested revision day and its actual before/after classification."""

    day: date
    before: SchoolDay
    after: SchoolDay
    session_value_before: Decimal
    session_value_after: Decimal


@dataclass(frozen=True)
class RevisionPreview:
    """A non-mutating coverage and value comparison for one revision."""

    revision: CalendarRevision
    before: object
    after: object
    changed_days: tuple[RevisionDayChange, ...]
    scheduled_value_before: Decimal
    scheduled_value_after: Decimal

    @property
    def session_units_delta(self) -> Decimal:
        return self.after.total_units - self.before.total_units

    @property
    def session_value_delta(self) -> Decimal:
        return self.scheduled_value_after - self.scheduled_value_before


def load_revision(path: str | Path) -> CalendarRevision:
    """Read one manually supplied, local revision JSON file.

    This is deliberately a reader rather than an acceptance workflow: callers
    can inspect a source change without persisting it or contacting a calendar
    service.
    """

    source = Path(path)
    if not source.is_file():
        raise LedgerError(f"Revision file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerError(f"Revision file is not valid JSON: {source}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("overrides"), list):
        raise LedgerError("Revision file needs source_name, observed_on, summary, and an overrides list.")
    try:
        overrides = tuple(_revision_day(item) for item in payload["overrides"])
        observed_on = date.fromisoformat(str(payload["observed_on"]))
        source_name = str(payload["source_name"])
        summary = str(payload["summary"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerError(f"Revision file has invalid fields: {source}") from exc
    return CalendarRevision(
        source_name=source_name,
        observed_on=observed_on,
        summary=summary,
        overrides=overrides,
    )


def preview_revision(cycle, calendar: SchoolCalendar, revision: CalendarRevision, as_of: date, payments):
    """Compare projections before and after a revision without changing either.

    Payments are passed straight through to both projections.  Calendar
    revisions therefore cannot alter recorded payment history.
    """

    # Keep imports local to avoid a calendars -> ledger import cycle.
    from tutor_pay_ledger.ledger import project

    before = project(cycle, calendar, as_of, payments)
    updated = apply_revision(calendar, revision)
    after = project(cycle, updated, as_of, payments)
    before_values = {line.day: line.amount for line in before.sessions}
    after_values = {line.day: line.amount for line in after.sessions}
    changes = tuple(
        RevisionDayChange(
            day=item.day,
            before=calendar.describe(item.day),
            after=updated.describe(item.day),
            session_value_before=before_values.get(item.day, Decimal("0.00")),
            session_value_after=after_values.get(item.day, Decimal("0.00")),
        )
        for item in sorted(revision.overrides, key=lambda entry: entry.day)
    )
    scheduled_before = sum((line.amount for line in before.sessions), Decimal("0.00"))
    scheduled_after = sum((line.amount for line in after.sessions), Decimal("0.00"))
    return RevisionPreview(
        revision=revision,
        before=before,
        after=after,
        changed_days=changes,
        scheduled_value_before=scheduled_before,
        scheduled_value_after=scheduled_after,
    )


def _revision_day(value: object) -> SchoolDay:
    if not isinstance(value, dict):
        raise ValueError("override must be an object")
    day = date.fromisoformat(str(value["date"]))
    kind = DayKind(str(value["kind"]))
    name_value = value.get("name")
    if name_value is not None and not isinstance(name_value, str):
        raise ValueError("override name must be text")
    return SchoolDay(day, kind, name_value)
