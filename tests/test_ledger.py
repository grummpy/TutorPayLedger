"""Pay cycle standing on the sample district calendar."""

from datetime import date, time
from decimal import Decimal

from tutor_pay_ledger.calendars.fixture import build_sample_district_calendar
from tutor_pay_ledger.ledger import PayCycle, Payment, project
from tutor_pay_ledger.models import HalfDayPolicy, WeekendEndPolicy
from tutor_pay_ledger.notes import draft_extend_note
from tutor_pay_ledger.seed import SEED_CYCLE_ID, build_seed_ledger

RATE = Decimal("40.00")


def _cycle(**overrides) -> PayCycle:
    fields = dict(
        id="cyc_math",
        payee="Personal school tutor",
        service="Mathematics",
        beneficiary="CJ",
        coverage_start=date(2026, 9, 28),
        named_end=date(2026, 10, 16),
        weekdays=frozenset({0, 1, 2, 3, 4}),
        session_start=time(15, 30),
        session_end=time(16, 30),
        session_rate=RATE,
        half_day_policy=HalfDayPolicy.HALF_RATE,
        weekend_end_policy=WeekendEndPolicy.ROLL_TO_MONDAY,
    )
    fields.update(overrides)
    return PayCycle(**fields)


def test_seed_cycle_matches_the_october_window():
    ledger = build_seed_ledger()
    cycle = ledger.cycle(SEED_CYCLE_ID)
    standing = project(cycle, build_sample_district_calendar(), date(2026, 10, 5), ledger.payments)
    assert cycle.payee == "Personal school tutor"
    assert cycle.beneficiary == "CJ"
    assert cycle.session_start == time(15, 30)
    assert standing.effective_end == date(2026, 10, 16)
    assert standing.total_units == Decimal("13.5")
    assert standing.remaining_units == Decimal("8.5")
    assert standing.agreed_amount == Decimal("540.00")
    assert standing.paid == Decimal("240.00")
    assert standing.balance == Decimal("300.00")
    assert standing.warning is None
    assert standing.state == "active"
    remaining_days = [line.day for line in standing.remaining]
    assert date(2026, 10, 12) not in remaining_days
    assert date(2026, 10, 10) not in remaining_days
    assert remaining_days[0] == date(2026, 10, 5)
    assert remaining_days[-1] == date(2026, 10, 16)
    assert standing.remaining[-1].weight == Decimal("0.5")
    assert standing.remaining[-1].amount == Decimal("20.00")


def test_warning_and_ended_states():
    cycle = _cycle(quoted_amount=Decimal("540.00"))
    calendar = build_sample_district_calendar()
    inside = project(cycle, calendar, date(2026, 10, 9), [])
    ended = project(cycle, calendar, date(2026, 10, 17), [])
    assert inside.warning == "Coverage ends within 7 days (7 days left)."
    assert ended.state == "ended"
    assert ended.remaining_units == 0
    assert ended.warning is None


def test_skip_policy_drops_the_october_half_day():
    cycle = _cycle(half_day_policy=HalfDayPolicy.SKIP)
    standing = project(cycle, build_sample_district_calendar(), date(2026, 10, 5), [])
    assert standing.total_units == Decimal("13")
    assert all(line.day != date(2026, 10, 16) for line in standing.sessions)
    assert standing.agreed_amount == Decimal("520.00")


def test_saturday_end_covers_through_monday_by_default():
    cycle = _cycle(
        coverage_start=date(2026, 10, 5),
        named_end=date(2026, 10, 17),
    )
    standing = project(cycle, build_sample_district_calendar(), date(2026, 10, 5), [])
    assert standing.effective_end == date(2026, 10, 19)
    assert standing.sessions[-1].day == date(2026, 10, 19)


def test_strict_weekend_end_does_not_include_monday():
    cycle = _cycle(
        coverage_start=date(2026, 10, 5),
        named_end=date(2026, 10, 17),
        weekend_end_policy=WeekendEndPolicy.STRICT,
    )
    standing = project(cycle, build_sample_district_calendar(), date(2026, 10, 5), [])
    assert standing.effective_end == date(2026, 10, 17)
    assert all(line.day != date(2026, 10, 19) for line in standing.sessions)


def test_extend_note_lists_five_october_weekdays_and_moves_no_money():
    ledger = build_seed_ledger()
    cycle = ledger.cycle(SEED_CYCLE_ID)
    calendar = build_sample_district_calendar()
    standing = project(cycle, calendar, date(2026, 10, 5), ledger.payments)
    note = draft_extend_note(cycle, calendar, 5, standing)
    assert "Fri Oct 23, 2026" in note
    assert "$200.00" in note
    assert "Weekends never count" in note
    assert "does not move money" in note
    assert "CJ" in note
    assert "Personal school tutor" in note
    assert "12345678" not in note


def test_payment_memo_rejects_an_account_number():
    from tutor_pay_ledger.models import LedgerError
    import pytest

    with pytest.raises(LedgerError, match="bank credentials"):
        Payment(
            id="pay_secret",
            cycle_id="cyc_math",
            paid_on=date(2026, 10, 5),
            amount=Decimal("40.00"),
            method="transfer",
            memo="acct 123456789",
        )


def test_historical_projection_excludes_later_recorded_payments():
    cycle = _cycle(quoted_amount=Decimal("540.00"))
    payments = [
        Payment(
            id="pay_before",
            cycle_id=cycle.id,
            paid_on=date(2026, 10, 1),
            amount=Decimal("100.00"),
            method="check",
        ),
        Payment(
            id="pay_after",
            cycle_id=cycle.id,
            paid_on=date(2026, 10, 10),
            amount=Decimal("200.00"),
            method="check",
        ),
    ]
    early = project(cycle, build_sample_district_calendar(), date(2026, 10, 5), payments)
    later = project(cycle, build_sample_district_calendar(), date(2026, 10, 10), payments)
    assert early.paid == Decimal("100.00")
    assert early.balance == Decimal("440.00")
    assert later.paid == Decimal("300.00")
    assert later.balance == Decimal("240.00")
