"""Draft an extend-by-N note. The draft is text only. It does not send or move money."""

from __future__ import annotations

from decimal import Decimal

from tutor_pay_ledger.calendars.base import SchoolCalendar
from tutor_pay_ledger.coverage import extend_by_n, iter_billable, units_amount
from tutor_pay_ledger.ledger import CycleStanding, PayCycle, effective_end_for
from tutor_pay_ledger.models import (
    MONEY,
    HalfDayPolicy,
    LedgerError,
    format_date,
    format_money,
    format_session_time,
    format_units,
    format_weekdays,
)

_HALF = Decimal("0.5")
_FULL = Decimal("1")


def draft_extend_note(
    cycle: PayCycle,
    calendar: SchoolCalendar,
    count: int,
    standing: CycleStanding,
) -> str:
    """Plain-text note describing an extension of ``count`` school weekdays."""

    if count < 1:
        raise LedgerError("Extend-by count must be at least 1.")
    current_end = effective_end_for(cycle, calendar)
    new_end = extend_by_n(
        current_end,
        count,
        calendar,
        cycle.weekdays,
        cycle.half_day_policy,
    )
    added: list[tuple] = []
    for day, weight, described in iter_billable(
        current_end,
        new_end,
        calendar,
        cycle.weekdays,
        cycle.half_day_policy,
    ):
        if day <= current_end:
            continue
        amount = units_amount(weight, cycle.session_rate)
        added.append((day, weight, described.name, amount))
    if len(added) != count:
        raise LedgerError("Extension count did not match the billable days in the new window.")

    total_weight = sum((weight for _, weight, _, _ in added), Decimal("0"))
    estimate = sum((amount for _, _, _, amount in added), Decimal("0")).quantize(MONEY)
    who = cycle.beneficiary or "the household"
    if cycle.half_day_policy == HalfDayPolicy.HALF_RATE:
        half = "Half-days count as one weekday and bill at half the session rate."
    else:
        half = "Half-days are skipped. They do not bill and do not count toward the extension."

    lines = [
        f"Extend {cycle.service} coverage by {count} school weekdays",
        "",
        f"For: {who}",
        f"Payee: {cycle.payee}",
        (
            f"Session: {format_weekdays(cycle.weekdays)}, "
            f"{format_session_time(cycle.session_start, cycle.session_end)}"
        ),
        f"Current coverage ends: {format_date(current_end)}",
        (
            f"Remaining as of {format_date(standing.as_of)}: "
            f"{format_units(standing.remaining_units)} sessions"
        ),
        "",
        (
            f"Please extend coverage by {count} school weekdays after "
            f"{format_date(current_end)}. Count only Monday–Friday days that are "
            "in session. Weekends never count. Holidays and breaks never count."
        ),
        half,
        "",
        "Days in this extension:",
    ]
    for day, weight, label, amount in added:
        suffix = f"  {label}" if label else ""
        lines.append(
            f"  {format_date(day):<16}  {_weight_word(weight):<4}  "
            f"{format_money(amount):>8}{suffix}"
        )
    lines.extend(
        [
            "",
            f"New coverage end: {format_date(new_end)}",
            (
                f"Estimated extension: {format_units(total_weight)} sessions, "
                f"{format_money(estimate)} at {format_money(cycle.session_rate)} per full session."
            ),
            "",
            "This note is a draft for your records. It does not move money and it is not an invoice.",
            "Do not add bank, card, or account numbers to it.",
        ]
    )
    return "\n".join(lines) + "\n"


def _weight_word(weight: Decimal) -> str:
    if weight == _FULL:
        return "full"
    if weight == _HALF:
        return "half"
    return format_units(weight)
