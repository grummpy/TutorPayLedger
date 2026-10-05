"""Local ICS school-calendar feed.

This parses a file on disk. It does not fetch a URL. A bot that tracks a
live school calendar would download or receive an ICS document and hand the
text here, or return a :class:`CalendarRevision` from the update hook.

Recognized all-day events:

- ``CATEGORIES`` containing ``HALF-DAY``, ``HALFDAY``, or ``EARLY-RELEASE``
  → half-day. A summary containing "half" or "early release" does the same.
- ``BREAK``, ``VACATION``, or ``RECESS``, or a summary containing "break"
  or "recess" → break.
- Anything else all-day → holiday (school ICS feeds are mostly closures).

``DTEND;VALUE=DATE`` is exclusive, per RFC 5545. Timed events are ignored
(staff meetings are not day closures). Weekends inside a multi-day event
stay weekends. When two all-day events cover the same date, the later one
in the file wins.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from importlib.resources import files
from pathlib import Path

from tutor_pay_ledger.calendars.base import SchoolDay
from tutor_pay_ledger.models import DayKind, LedgerError

_HALF = {"HALF-DAY", "HALFDAY", "EARLY-RELEASE", "EARLYRELEASE"}
_BREAK = {"BREAK", "VACATION", "RECESS"}
_HOLIDAY = {"HOLIDAY", "CLOSED", "NO-SCHOOL", "NOSCHOOL"}


class IcsSchoolCalendar:
    """Exception calendar built from one ICS document."""

    def __init__(self, days: dict[date, SchoolDay], *, label: str = "ICS feed") -> None:
        self.label = label
        self._days = days

    def describe(self, day: date) -> SchoolDay:
        if day.weekday() >= 5:
            return SchoolDay(day, DayKind.WEEKEND, None)
        return self._days.get(day) or SchoolDay(day, DayKind.IN_SESSION, None)


def read_sample_ics() -> str:
    """Packaged fragment of Sample District closures, for the ICS stub."""

    return files("tutor_pay_ledger.data").joinpath("sample_district.ics").read_text(encoding="utf-8")


class SampleIcsProvider:
    """Loads the packaged ICS fragment. Offline stand-in for a feed."""

    name = "sample-ics"

    def load(self) -> IcsSchoolCalendar:
        return parse_ics(read_sample_ics(), label="Sample District ICS fragment")


class IcsFileProvider:
    """Loads a local ``.ics`` file the caller already has."""

    name = "ics"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> IcsSchoolCalendar:
        if not self.path.is_file():
            raise LedgerError(f"ICS file not found: {self.path}")
        text = self.path.read_text(encoding="utf-8")
        return parse_ics(text, label=self.path.name)


def parse_ics(text: str, *, label: str = "ICS feed") -> IcsSchoolCalendar:
    events = _events(text)
    days: dict[date, SchoolDay] = {}
    for event in events:
        start = _as_date_field(event.get("dtstart"))
        if start is None or not start[1]:
            # Missing, or a timed event (a staff meeting is not a day closure).
            continue
        start_day = start[0]
        end_value = _as_date_field(event.get("dtend"))
        if end_value is None:
            last = start_day
        elif not end_value[1]:
            continue
        else:
            # VALUE=DATE end is exclusive.
            last = end_value[0] - timedelta(days=1)
        if last < start_day:
            continue
        categories = event.get("categories", "")
        summary = event.get("summary", "")
        if not isinstance(categories, str):
            categories = ""
        if not isinstance(summary, str):
            summary = ""
        kind = _kind(categories, summary)
        name = summary.strip() or kind.value
        cursor = start_day
        while cursor <= last:
            if cursor.weekday() < 5:
                days[cursor] = SchoolDay(cursor, kind, name)
            cursor += timedelta(days=1)
    return IcsSchoolCalendar(days, label=label)


def _as_date_field(value: object) -> tuple[date, bool] | None:
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    day, all_day = value
    if isinstance(day, datetime) or not isinstance(day, date):
        return None
    return day, bool(all_day)


def _kind(categories: str, summary: str) -> DayKind:
    tokens = {
        part.strip().upper().replace("_", "-").replace(" ", "-")
        for part in categories.split(",")
        if part.strip()
    }
    summary_key = summary.lower()
    if tokens & _HALF or "half" in summary_key or "early release" in summary_key:
        return DayKind.HALF_DAY
    if tokens & _BREAK or "break" in summary_key or "recess" in summary_key:
        return DayKind.BREAK
    if tokens & _HOLIDAY:
        return DayKind.HOLIDAY
    return DayKind.HOLIDAY


def _events(text: str) -> list[dict[str, str | tuple[date, bool]]]:
    lines = _unfold(text)
    events: list[dict[str, str | tuple[date, bool]]] = []
    current: dict[str, str | tuple[date, bool]] | None = None
    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = {}
            continue
        if upper == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        left, value = line.split(":", 1)
        name, params = _name_and_params(left)
        key = name.lower()
        if key in {"dtstart", "dtend"}:
            parsed = _parse_dt(value.strip(), params)
            if parsed is not None:
                current[key] = parsed
        elif key in {"summary", "categories"}:
            current[key] = _unescape(value.strip())
    return events


def _unfold(text: str) -> list[str]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in raw:
        if line[:1] in " \t" and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    return lines


def _name_and_params(left: str) -> tuple[str, dict[str, str]]:
    bits = left.split(";")
    params: dict[str, str] = {}
    for bit in bits[1:]:
        if "=" in bit:
            key, val = bit.split("=", 1)
            params[key.upper()] = val.upper()
    return bits[0], params


def _parse_dt(value: str, params: dict[str, str]) -> tuple[date, bool] | None:
    token = value.split("Z")[0]
    all_day = params.get("VALUE") == "DATE" or (len(token) == 8 and "T" not in token.upper())
    try:
        if all_day:
            return datetime.strptime(token[:8], "%Y%m%d").date(), True
        return datetime.strptime(token[:15], "%Y%m%dT%H%M%S").date(), False
    except ValueError:
        return None


def _unescape(value: str) -> str:
    return value.replace(r"\,", ",").replace(r"\;", ";").replace(r"\n", " ").replace(r"\N", " ")
