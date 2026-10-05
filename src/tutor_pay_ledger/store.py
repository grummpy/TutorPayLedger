"""JSON ledger file. Dates and money are stored as strings. No secrets."""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

from tutor_pay_ledger.ledger import Ledger, PayCycle, Payment
from tutor_pay_ledger.models import HalfDayPolicy, LedgerError, WeekendEndPolicy, parse_money

VERSION = 1


def load_ledger(path: Path) -> Ledger:
    if not path.is_file():
        raise LedgerError(f"No ledger at {path}. Add a cycle or run `tutor-ledger seed`.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerError(f"Ledger file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != VERSION:
        raise LedgerError(f"Unsupported ledger version in {path}.")
    try:
        cycles = [_cycle_from_json(item) for item in payload.get("cycles", [])]
        payments = [_payment_from_json(item) for item in payload.get("payments", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerError(f"Ledger file is missing fields: {path}") from exc
    return Ledger(cycles=cycles, payments=payments)


def save_ledger(path: Path, ledger: Ledger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_to_json(ledger), indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def empty_ledger() -> Ledger:
    return Ledger(cycles=[], payments=[])


def _to_json(ledger: Ledger) -> dict:
    return {
        "version": VERSION,
        "cycles": [_cycle_to_json(cycle) for cycle in ledger.cycles],
        "payments": [_payment_to_json(payment) for payment in ledger.payments],
    }


def _cycle_to_json(cycle: PayCycle) -> dict:
    return {
        "id": cycle.id,
        "payee": cycle.payee,
        "service": cycle.service,
        "beneficiary": cycle.beneficiary,
        "coverage_start": cycle.coverage_start.isoformat(),
        "named_end": None if cycle.named_end is None else cycle.named_end.isoformat(),
        "extend_weekdays": cycle.extend_weekdays,
        "weekdays": sorted(cycle.weekdays),
        "session_start": cycle.session_start.strftime("%H:%M"),
        "session_end": cycle.session_end.strftime("%H:%M"),
        "session_rate": f"{cycle.session_rate:.2f}",
        "quoted_amount": None if cycle.quoted_amount is None else f"{cycle.quoted_amount:.2f}",
        "half_day_policy": cycle.half_day_policy.value,
        "weekend_end_policy": cycle.weekend_end_policy.value,
        "note": cycle.note,
    }


def _payment_to_json(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "cycle_id": payment.cycle_id,
        "paid_on": payment.paid_on.isoformat(),
        "amount": f"{payment.amount:.2f}",
        "method": payment.method,
        "memo": payment.memo,
    }


def _cycle_from_json(item: dict) -> PayCycle:
    named = item["named_end"]
    quoted = item["quoted_amount"]
    return PayCycle(
        id=item["id"],
        payee=item["payee"],
        service=item["service"],
        beneficiary=item["beneficiary"],
        coverage_start=date.fromisoformat(item["coverage_start"]),
        named_end=None if named is None else date.fromisoformat(named),
        extend_weekdays=int(item["extend_weekdays"]),
        weekdays=frozenset(int(day) for day in item["weekdays"]),
        session_start=_clock(item["session_start"]),
        session_end=_clock(item["session_end"]),
        session_rate=parse_money(item["session_rate"]),
        quoted_amount=None if quoted is None else parse_money(quoted),
        half_day_policy=HalfDayPolicy(item["half_day_policy"]),
        weekend_end_policy=WeekendEndPolicy(item["weekend_end_policy"]),
        note=item.get("note") or "",
    )


def _payment_from_json(item: dict) -> Payment:
    return Payment(
        id=item["id"],
        cycle_id=item["cycle_id"],
        paid_on=date.fromisoformat(item["paid_on"]),
        amount=parse_money(item["amount"], allow_zero=False),
        method=item["method"],
        memo=item.get("memo") or "",
    )


def _clock(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
