"""Input rules: weekdays, money, and no bank credentials."""

from datetime import time
from decimal import Decimal

import pytest

from tutor_pay_ledger.models import (
    LedgerError,
    format_money,
    format_session_time,
    parse_money,
    parse_session_time,
    parse_weekdays,
)


def test_weekdays_accept_monday_through_friday_aliases():
    assert parse_weekdays("mon-fri") == frozenset({0, 1, 2, 3, 4})
    assert parse_weekdays("Mon, Wed, Fri") == frozenset({0, 2, 4})


def test_weekends_cannot_be_scheduled():
    with pytest.raises(LedgerError, match="Monday–Friday only"):
        parse_weekdays("mon,sat")
    with pytest.raises(LedgerError, match="Weekends never count"):
        parse_weekdays("sunday")


def test_session_clock_and_meridiem_on_the_end_only():
    start, end = parse_session_time("3:30–4:30 PM")
    assert (start, end) == (time(15, 30), time(16, 30))
    assert format_session_time(start, end) == "3:30 PM–4:30 PM"


def test_session_must_end_after_it_starts():
    with pytest.raises(LedgerError, match="after session start"):
        parse_session_time("4:30pm-3:30pm")


def test_money_is_cents_and_non_negative():
    assert parse_money("$1,240.50") == Decimal("1240.50")
    with pytest.raises(LedgerError, match="two decimal places"):
        parse_money("40.001")
    with pytest.raises(LedgerError, match="negative"):
        parse_money("-1")


def test_format_money_keeps_the_sign_on_a_credit():
    assert format_money(Decimal("540")) == "$540.00"
    assert format_money(Decimal("-20")) == "-$20.00"
