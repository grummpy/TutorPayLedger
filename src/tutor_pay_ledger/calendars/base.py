"""Calendar protocol and in-memory implementations."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Protocol

from tutor_pay_ledger.models import DayKind


class SchoolDay:
    """One civil date as a school would treat it.

    ``name`` is a closure or half-day label such as "Labor Day". Regular
    instructional days leave it empty.
    """

    __slots__ = ("day", "kind", "name")

    def __init__(self, day: date, kind: DayKind, name: str | None = None) -> None:
        self.day = day
        self.kind = kind
        self.name = name or None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SchoolDay):
            return NotImplemented
        return (self.day, self.kind, self.name) == (other.day, other.kind, other.name)

    def __repr__(self) -> str:
        return f"SchoolDay({self.day.isoformat()}, {self.kind.value}, {self.name!r})"


class SchoolCalendar(Protocol):
    """Answers, for any civil date, how school treats that day."""

    def describe(self, day: date) -> SchoolDay:
        """Return the school-day classification for ``day``."""


class CalendarProvider(Protocol):
    """Builds a calendar. The ICS and bot hooks implement this shape."""

    name: str

    def load(self) -> SchoolCalendar:
        """Return the calendar. Must not contact the network."""


class MemoryCalendar:
    """Weekday map of exceptions. Unlisted weekdays are in session.

    Weekends are always reported as weekends. A caller cannot mark Saturday
    as an instructional day through this map.
    """

    def __init__(
        self,
        days: Mapping[date, SchoolDay] | None = None,
        *,
        label: str = "memory",
    ) -> None:
        self.label = label
        self._days = {day: described for day, described in (days or {}).items()}

    def describe(self, day: date) -> SchoolDay:
        if day.weekday() >= 5:
            return SchoolDay(day, DayKind.WEEKEND, None)
        described = self._days.get(day)
        if described is None:
            return SchoolDay(day, DayKind.IN_SESSION, None)
        if described.kind == DayKind.WEEKEND:
            return SchoolDay(day, DayKind.IN_SESSION, described.name)
        return described


class OverlayCalendar:
    """A base calendar with per-date overrides from a revision or a bot.

    Weekend dates stay weekends. An override cannot create a Saturday session.
    """

    def __init__(self, base: SchoolCalendar, overrides: Mapping[date, SchoolDay]) -> None:
        self.base = base
        self._overrides = dict(overrides)

    def describe(self, day: date) -> SchoolDay:
        if day.weekday() >= 5:
            return SchoolDay(day, DayKind.WEEKEND, None)
        override = self._overrides.get(day)
        if override is not None and override.kind != DayKind.WEEKEND:
            return SchoolDay(day, override.kind, override.name)
        return self.base.describe(day)
