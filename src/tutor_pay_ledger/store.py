"""JSON ledger file. Dates and money are stored as strings. No secrets."""

from __future__ import annotations

from contextlib import contextmanager
import json
from datetime import date, time
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported local test runner is POSIX.
    fcntl = None

from tutor_pay_ledger.ledger import (
    CorrectionReversal,
    Ledger,
    PayCycle,
    Payment,
    PaymentCorrection,
)
from tutor_pay_ledger.models import HalfDayPolicy, LedgerError, WeekendEndPolicy, parse_money

VERSION = 1


@contextmanager
def locked_ledger(path: Path) -> Iterator[None]:
    """Serialize one local ledger's read-modify-write transaction.

    The sidecar is intentionally retained: deleting it after releasing an
    advisory lock can create a second inode while another process is waiting.
    The lock itself is released automatically if a process exits unexpectedly.
    """

    if fcntl is None:
        raise LedgerError("Concurrent ledger updates require a POSIX local filesystem.")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
        corrections = [_correction_from_json(item) for item in payload.get("corrections", [])]
        reversals = [_reversal_from_json(item) for item in payload.get("correction_reversals", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerError(f"Ledger file is missing fields: {path}") from exc
    ledger = Ledger(
        cycles=cycles,
        payments=payments,
        corrections=corrections,
        correction_reversals=reversals,
    )
    _validate_history(ledger)
    return ledger


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
        "corrections": [_correction_to_json(correction) for correction in ledger.corrections],
        "correction_reversals": [
            _reversal_to_json(reversal) for reversal in ledger.correction_reversals
        ],
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


def _correction_to_json(correction: PaymentCorrection) -> dict:
    return {
        "id": correction.id,
        "payment_id": correction.payment_id,
        "cycle_id": correction.cycle_id,
        "corrected_amount": f"{correction.corrected_amount:.2f}",
        "corrected_on": correction.corrected_on.isoformat(),
        "reason": correction.reason,
    }


def _reversal_to_json(reversal: CorrectionReversal) -> dict:
    return {
        "id": reversal.id,
        "correction_id": reversal.correction_id,
        "reversed_on": reversal.reversed_on.isoformat(),
        "reason": reversal.reason,
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


def _correction_from_json(item: dict) -> PaymentCorrection:
    return PaymentCorrection(
        id=item["id"],
        payment_id=item["payment_id"],
        cycle_id=item["cycle_id"],
        corrected_amount=parse_money(item["corrected_amount"]),
        corrected_on=date.fromisoformat(item["corrected_on"]),
        reason=item["reason"],
    )


def _reversal_from_json(item: dict) -> CorrectionReversal:
    return CorrectionReversal(
        id=item["id"],
        correction_id=item["correction_id"],
        reversed_on=date.fromisoformat(item["reversed_on"]),
        reason=item["reason"],
    )


def _validate_history(ledger: Ledger) -> None:
    correction_ids: set[str] = set()
    for correction in ledger.corrections:
        if correction.id in correction_ids:
            raise LedgerError(f"Duplicate payment correction id {correction.id!r}.")
        correction_ids.add(correction.id)
        payment = ledger.payment(correction.payment_id)
        if payment.cycle_id != correction.cycle_id:
            raise LedgerError("A payment correction must keep the original payment's cycle.")
        if correction.corrected_on < payment.paid_on:
            raise LedgerError("A payment cannot be corrected before it was recorded.")

    reversed_ids: set[str] = set()
    reversal_ids: set[str] = set()
    for reversal in ledger.correction_reversals:
        if reversal.id in reversal_ids:
            raise LedgerError(f"Duplicate correction reversal id {reversal.id!r}.")
        if reversal.correction_id in reversed_ids:
            raise LedgerError(f"Correction {reversal.correction_id!r} is already reversed.")
        correction = ledger.correction(reversal.correction_id)
        if reversal.reversed_on < correction.corrected_on:
            raise LedgerError("A correction cannot be undone before it was recorded.")
        reversal_ids.add(reversal.id)
        reversed_ids.add(reversal.correction_id)

    active_payments: set[str] = set()
    for correction in ledger.corrections:
        if correction.id in reversed_ids:
            continue
        if correction.payment_id in active_payments:
            raise LedgerError(
                f"Payment {correction.payment_id!r} has more than one active correction."
            )
        active_payments.add(correction.payment_id)


def _clock(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
