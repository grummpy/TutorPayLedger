"""Shared vocabulary: money, weekday windows, and coverage policies."""

from __future__ import annotations

import re
from datetime import time
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

MONEY = Decimal("0.01")
CENT = MONEY
ALL_WEEKDAYS = frozenset({0, 1, 2, 3, 4})
WEEKDAY_TOKENS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_LABELS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# Eight or more digits is enough to be a card, account, or routing number.
_DIGIT = re.compile(r"\d")
_ID = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


class LedgerError(Exception):
    """Invalid input, or a coverage request the calendar cannot satisfy."""


class HalfDayPolicy(str, Enum):
    """How a school half-day affects billing and an extend-by-N count.

    half_rate: the day counts as one school weekday and bills at half the
    session rate.
    skip: the day is not billable and does not consume an extend-by-N day.
    """

    HALF_RATE = "half_rate"
    SKIP = "skip"


class WeekendEndPolicy(str, Enum):
    """What a Saturday or Sunday coverage end date means.

    Sessions are never held on a weekend. See the README for the full rule.

    roll_to_monday: move the boundary to the following Monday, inclusive,
    even when that Monday is closed.
    roll_to_next_session: move the boundary to the next day that actually
    bills under the half-day policy.
    strict: keep the named date. Monday is outside the window.
    """

    ROLL_TO_MONDAY = "roll_to_monday"
    ROLL_TO_NEXT_SESSION = "roll_to_next_session"
    STRICT = "strict"


class DayKind(str, Enum):
    IN_SESSION = "in_session"
    HALF_DAY = "half_day"
    HOLIDAY = "holiday"
    BREAK = "break"
    WEEKEND = "weekend"


def parse_money(value: str | Decimal | int, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, Decimal):
        amount = value
    else:
        text = str(value).strip().replace("$", "").replace(",", "")
        if not text:
            raise LedgerError("Amount is required.")
        try:
            amount = Decimal(text)
        except Exception as exc:
            raise LedgerError(f"Invalid amount {value!r}.") from exc
    if not amount.is_finite():
        raise LedgerError("Amount must be finite.")
    if amount < 0 or (amount == 0 and not allow_zero):
        raise LedgerError("Amount must be greater than zero." if not allow_zero else "Amount cannot be negative.")
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise LedgerError("Amounts use cents only (two decimal places).")
    return amount.quantize(MONEY, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal) -> str:
    quantized = amount.quantize(MONEY, rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    return f"{sign}${abs(quantized):,.2f}"


def format_units(units: Decimal) -> str:
    if units == units.to_integral_value():
        return str(int(units))
    return format(units.normalize(), "f")


def assert_no_secret(value: str, field: str) -> str:
    """Reject strings that look like account, card, or routing numbers.

    The ledger keeps labels and memos. It does not keep bank credentials.
    """

    text = " ".join(value.split())
    if not text:
        raise LedgerError(f"{field} is required.")
    digits = "".join(_DIGIT.findall(text))
    if len(digits) >= 8:
        raise LedgerError(
            f"{field} looks like an account or card number. "
            "This ledger stores labels and memos only, never bank credentials."
        )
    return text


def optional_text(value: str | None, field: str) -> str:
    if value is None:
        return ""
    text = " ".join(value.split())
    if not text:
        return ""
    return assert_no_secret(text, field)


def check_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise LedgerError(
            "Ids use lowercase letters, digits, and underscores, and start with a letter."
        )
    return value


def parse_weekdays(value: str | frozenset[int]) -> frozenset[int]:
    if isinstance(value, frozenset):
        days = value
    else:
        token = value.strip().lower().replace(" ", "")
        if token in {"mon-fri", "monday-friday", "weekdays", "mf"}:
            return ALL_WEEKDAYS
        parts = [part for part in re.split(r"[,/+]", token) if part]
        if not parts:
            raise LedgerError("Weekday window is required. Use mon-fri or a list such as mon,wed,fri.")
        parsed: list[int] = []
        for part in parts:
            if part not in WEEKDAY_TOKENS:
                raise LedgerError(f"Unknown weekday {part!r}. Sessions run Monday–Friday only.")
            parsed.append(WEEKDAY_TOKENS[part])
        days = frozenset(parsed)
    weekend = sorted(day for day in days if day >= 5)
    if weekend:
        names = ", ".join(WEEKDAY_LABELS[day] for day in weekend)
        raise LedgerError(
            "Sessions are Monday–Friday only. "
            f"Weekends never count and cannot be scheduled ({names})."
        )
    if not days or not days <= ALL_WEEKDAYS:
        raise LedgerError("Weekday window must be a non-empty subset of Monday–Friday.")
    return frozenset(days)


def format_weekdays(days: frozenset[int]) -> str:
    if days == ALL_WEEKDAYS:
        return "Mon–Fri"
    return ", ".join(WEEKDAY_LABELS[day] for day in sorted(days))


def parse_clock(value: str) -> time:
    text = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", text)
    if not match:
        raise LedgerError(f"Invalid time {value!r}. Use 3:30pm or 15:30.")
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    suffix = match.group(3)
    if suffix:
        if not 1 <= hour <= 12:
            raise LedgerError(f"Invalid time {value!r}.")
        if suffix == "pm" and hour != 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        raise LedgerError(f"Invalid time {value!r}.")
    if minute > 59:
        raise LedgerError(f"Invalid time {value!r}.")
    return time(hour, minute)


def parse_session_time(value: str) -> tuple[time, time]:
    parts = re.split(r"\s*[–—-]\s*", value.strip())
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise LedgerError("Session time must look like 3:30pm-4:30pm.")
    start_raw, end_raw = parts
    if re.search(r"(am|pm)\s*$", end_raw, re.I) and not re.search(r"(am|pm)\s*$", start_raw, re.I):
        meridiem = re.search(r"(am|pm)\s*$", end_raw, re.I)
        assert meridiem is not None
        start_raw = f"{start_raw}{meridiem.group(1)}"
    start = parse_clock(start_raw)
    end = parse_clock(end_raw)
    if start >= end:
        raise LedgerError("Session end must be after session start on the same day.")
    return start, end


def format_clock(value: time) -> str:
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {suffix}"


def format_session_time(start: time, end: time) -> str:
    return f"{format_clock(start)}–{format_clock(end)}"


def format_date(day) -> str:
    return f"{WEEKDAY_LABELS[day.weekday()]} {MONTH_LABELS[day.month - 1]} {day.day}, {day.year}"
