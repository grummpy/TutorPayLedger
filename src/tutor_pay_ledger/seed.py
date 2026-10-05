"""Demo ledger for the flagship tutor example.

The payee, student, and session window are sample data for tests and local
demos. The agreed amount is the session rate times billable units on the
sample calendar, stored explicitly so a later calendar edit does not silently
rewrite the price.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from tutor_pay_ledger.calendars.fixture import build_sample_district_calendar
from tutor_pay_ledger.ledger import Ledger, PayCycle, Payment, project
from tutor_pay_ledger.models import MONEY, HalfDayPolicy, WeekendEndPolicy

SEED_CYCLE_ID = "cyc_cj_math_2026oct"
SEED_PAYMENT_ID = "pay_cj_sep_block"
SEED_AS_OF = date(2026, 10, 5)
SESSION_RATE = Decimal("40.00")
RECORDED_PAYMENT = Decimal("240.00")


def build_seed_ledger() -> Ledger:
    calendar = build_sample_district_calendar()
    draft = PayCycle(
        id=SEED_CYCLE_ID,
        payee="Personal school tutor",
        service="Mathematics",
        beneficiary="CJ",
        coverage_start=date(2026, 9, 28),
        named_end=date(2026, 10, 16),
        extend_weekdays=0,
        weekdays=frozenset({0, 1, 2, 3, 4}),
        session_start=time(15, 30),
        session_end=time(16, 30),
        session_rate=SESSION_RATE,
        quoted_amount=None,
        half_day_policy=HalfDayPolicy.HALF_RATE,
        weekend_end_policy=WeekendEndPolicy.ROLL_TO_MONDAY,
        note="Sample cycle for demos and tests. Not a real invoice.",
    )
    preview = project(draft, calendar, SEED_AS_OF, ())
    agreed = (SESSION_RATE * preview.total_units).quantize(MONEY)
    cycle = PayCycle(
        id=draft.id,
        payee=draft.payee,
        service=draft.service,
        beneficiary=draft.beneficiary,
        coverage_start=draft.coverage_start,
        named_end=draft.named_end,
        extend_weekdays=draft.extend_weekdays,
        weekdays=draft.weekdays,
        session_start=draft.session_start,
        session_end=draft.session_end,
        session_rate=draft.session_rate,
        quoted_amount=agreed,
        half_day_policy=draft.half_day_policy,
        weekend_end_policy=draft.weekend_end_policy,
        note=draft.note,
    )
    payment = Payment(
        id=SEED_PAYMENT_ID,
        cycle_id=cycle.id,
        paid_on=date(2026, 9, 28),
        amount=RECORDED_PAYMENT,
        method="check",
        memo="September block toward Mathematics coverage",
    )
    return Ledger(cycles=[cycle], payments=[payment])
