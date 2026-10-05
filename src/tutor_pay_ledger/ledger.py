"""Pay cycles, logged payments, and a standing for one as-of date.

A cycle is an agreement: who is paid, which weekdays, what time, the session
rate, and how far coverage runs. A payment is money the household recorded.
This module does not move money and does not store account numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

from tutor_pay_ledger.calendars.base import SchoolCalendar
from tutor_pay_ledger.coverage import (
    coverage_span_of_n,
    coverage_warning,
    effective_named_end,
    extend_by_n,
    iter_billable,
    units_amount,
)
from tutor_pay_ledger.models import (
    MONEY,
    DayKind,
    HalfDayPolicy,
    LedgerError,
    WeekendEndPolicy,
    assert_no_secret,
    check_id,
    optional_text,
    parse_money,
)


@dataclass(frozen=True)
class PayCycle:
    """One coverage window for a recurring weekday service."""

    id: str
    payee: str
    service: str
    coverage_start: date
    weekdays: frozenset[int]
    session_start: time
    session_end: time
    session_rate: Decimal
    beneficiary: str | None = None
    named_end: date | None = None
    extend_weekdays: int = 0
    half_day_policy: HalfDayPolicy = HalfDayPolicy.HALF_RATE
    weekend_end_policy: WeekendEndPolicy = WeekendEndPolicy.ROLL_TO_MONDAY
    quoted_amount: Decimal | None = None
    note: str = ""

    def __post_init__(self) -> None:
        check_id(self.id)
        assert_no_secret(self.payee, "Payee")
        assert_no_secret(self.service, "Service")
        if self.beneficiary is not None:
            assert_no_secret(self.beneficiary, "Beneficiary")
        if self.note:
            optional_text(self.note, "Note")
        if self.named_end is None and self.extend_weekdays < 1:
            raise LedgerError("Provide a coverage end date, an extend-by count, or both.")
        if self.extend_weekdays < 0:
            raise LedgerError("Extend-by count cannot be negative.")
        if self.named_end is not None and self.named_end < self.coverage_start:
            raise LedgerError("Coverage end is before the coverage start.")
        if not self.weekdays or any(day >= 5 for day in self.weekdays):
            raise LedgerError(
                "Sessions are Monday–Friday only. Weekends never count and cannot be scheduled."
            )
        if self.session_start >= self.session_end:
            raise LedgerError("Session end must be after session start on the same day.")
        if self.session_rate < 0:
            raise LedgerError("Session rate cannot be negative.")
        if self.quoted_amount is not None and self.quoted_amount < 0:
            raise LedgerError("Agreed amount cannot be negative.")


@dataclass(frozen=True)
class Payment:
    """Money recorded against a cycle. A label, not a transfer."""

    id: str
    cycle_id: str
    paid_on: date
    amount: Decimal
    method: str
    memo: str = ""

    def __post_init__(self) -> None:
        check_id(self.id)
        check_id(self.cycle_id)
        if self.amount <= 0:
            raise LedgerError("Payment amount must be greater than zero.")
        assert_no_secret(self.method, "Payment method")
        if self.memo:
            optional_text(self.memo, "Memo")


@dataclass(frozen=True)
class SessionLine:
    day: date
    weight: Decimal
    kind: DayKind
    name: str | None
    amount: Decimal


@dataclass(frozen=True)
class CycleStanding:
    """Coverage and money for one cycle on one as-of date."""

    cycle: PayCycle
    effective_end: date
    as_of: date
    sessions: tuple[SessionLine, ...]
    remaining: tuple[SessionLine, ...]
    total_units: Decimal
    remaining_units: Decimal
    agreed_amount: Decimal
    paid: Decimal
    balance: Decimal
    state: str
    warning: str | None

    @property
    def days_until_end(self) -> int:
        return (self.effective_end - self.as_of).days


@dataclass
class Ledger:
    cycles: list[PayCycle]
    payments: list[Payment]

    def cycle(self, cycle_id: str) -> PayCycle:
        for cycle in self.cycles:
            if cycle.id == cycle_id:
                return cycle
        raise LedgerError(f"No cycle with id {cycle_id!r}.")

    def payments_for(self, cycle_id: str) -> list[Payment]:
        return [payment for payment in self.payments if payment.cycle_id == cycle_id]

    def add_cycle(self, cycle: PayCycle) -> None:
        if any(existing.id == cycle.id for existing in self.cycles):
            raise LedgerError(f"A cycle with id {cycle.id!r} already exists.")
        self.cycles.append(cycle)

    def log_payment(self, payment: Payment) -> None:
        self.cycle(payment.cycle_id)
        if any(existing.id == payment.id for existing in self.payments):
            raise LedgerError(f"A payment with id {payment.id!r} already exists.")
        self.payments.append(payment)


def effective_end_for(cycle: PayCycle, calendar: SchoolCalendar) -> date:
    """Resolve the last calendar date inside coverage, inclusive.

    A named end date is adjusted with the weekend-end policy first. An
    extend-by count then walks that many additional billable weekdays.
    With no named end, the count is measured from the coverage start and
    includes the start when the start itself bills.
    """

    if cycle.named_end is None:
        return coverage_span_of_n(
            cycle.coverage_start,
            cycle.extend_weekdays,
            calendar,
            cycle.weekdays,
            cycle.half_day_policy,
        )
    rolled = effective_named_end(
        cycle.named_end,
        cycle.weekend_end_policy,
        calendar,
        cycle.weekdays,
        cycle.half_day_policy,
    )
    if cycle.extend_weekdays:
        return extend_by_n(
            rolled,
            cycle.extend_weekdays,
            calendar,
            cycle.weekdays,
            cycle.half_day_policy,
        )
    return rolled


def project(
    cycle: PayCycle,
    calendar: SchoolCalendar,
    as_of: date,
    payments: list[Payment] | tuple[Payment, ...],
) -> CycleStanding:
    """Billable sessions, remaining coverage, and the money standing."""

    effective_end = effective_end_for(cycle, calendar)
    lines: list[SessionLine] = []
    for day, weight, described in iter_billable(
        cycle.coverage_start,
        effective_end,
        calendar,
        cycle.weekdays,
        cycle.half_day_policy,
    ):
        lines.append(
            SessionLine(
                day=day,
                weight=weight,
                kind=described.kind,
                name=described.name,
                amount=units_amount(weight, cycle.session_rate),
            )
        )
    sessions = tuple(lines)
    remaining = tuple(line for line in sessions if line.day >= as_of)
    total_units = sum((line.weight for line in sessions), Decimal("0"))
    remaining_units = sum((line.weight for line in remaining), Decimal("0"))
    if cycle.quoted_amount is not None:
        agreed = cycle.quoted_amount.quantize(MONEY)
    else:
        agreed = (cycle.session_rate * total_units).quantize(MONEY)
    paid = sum((payment.amount for payment in payments), Decimal("0.00"))
    if effective_end < as_of:
        state = "ended"
    elif as_of < cycle.coverage_start:
        state = "upcoming"
    else:
        state = "active"
    warning = None if state == "ended" else coverage_warning(as_of, effective_end)
    return CycleStanding(
        cycle=cycle,
        effective_end=effective_end,
        as_of=as_of,
        sessions=sessions,
        remaining=remaining,
        total_units=total_units,
        remaining_units=remaining_units,
        agreed_amount=agreed,
        paid=paid.quantize(MONEY),
        balance=(agreed - paid).quantize(MONEY),
        state=state,
        warning=warning,
    )


def make_money(value: str | Decimal | int, *, allow_zero: bool = True) -> Decimal:
    return parse_money(value, allow_zero=allow_zero)
