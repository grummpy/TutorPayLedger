"""Command line for the weekday payment ledger.

Commands:

- ``add-cycle`` records a coverage window.
- ``log-payment`` records money already paid. It does not send a payment.
- ``status`` shows remaining sessions and warns inside the 7-day window.
- ``sessions`` lists the billable dates.
- ``extend-note`` drafts an extend-by-N weekday note.
- ``seed`` writes the sample tutor cycle.
- ``calendar`` inspects the selected school calendar.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from tutor_pay_ledger.calendars.fixture import FixtureCalendarProvider
from tutor_pay_ledger.calendars.ics import IcsFileProvider, SampleIcsProvider
from tutor_pay_ledger.calendars.updates import load_revision, preview_revision
from tutor_pay_ledger.ledger import (
    CorrectionReversal,
    PayCycle,
    Payment,
    PaymentCorrection,
    preview_correction_reversal,
    preview_payment_correction,
    project,
)
from tutor_pay_ledger.models import (
    HalfDayPolicy,
    LedgerError,
    WeekendEndPolicy,
    format_date,
    format_money,
    format_session_time,
    format_units,
    format_weekdays,
    parse_money,
    parse_session_time,
    parse_weekdays,
)
from tutor_pay_ledger.notes import draft_extend_note
from tutor_pay_ledger.seed import build_seed_ledger
from tutor_pay_ledger.store import empty_ledger, load_ledger, locked_ledger, save_ledger

_HALF = Decimal("0.5")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tutor-ledger",
        description=(
            "Weekday payment ledger with school-calendar coverage. "
            "Sessions are Monday–Friday only."
        ),
    )
    parser.add_argument(
        "--ledger",
        default="data/ledger.json",
        help="Path to the ledger JSON file (default: data/ledger.json).",
    )
    parser.add_argument(
        "--calendar",
        choices=("fixture", "sample-ics", "ics"),
        default="fixture",
        help="School calendar: fixture (sample US year), sample-ics, or a local ics file.",
    )
    parser.add_argument(
        "--ics",
        help="Local ICS file. Required when --calendar ics. Never fetched over the network.",
    )
    parser.add_argument(
        "--ics-effective-from",
        type=_date_arg,
        help="First date a local ICS file may treat an unlisted weekday as in session.",
    )
    parser.add_argument(
        "--ics-effective-through",
        type=_date_arg,
        help="Last date a local ICS file may treat an unlisted weekday as in session.",
    )
    parser.add_argument(
        "--ics-out-of-coverage",
        choices=("closed", "error"),
        help="Required with --calendar ics: close or reject dates outside declared coverage.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-cycle", help="Record a coverage window.")
    add.add_argument("--payee", required=True, help="Who is paid. A name or label, not an account.")
    add.add_argument("--service", required=True, help="Service label, such as Mathematics or piano.")
    add.add_argument("--beneficiary", help="Who the service is for, such as a student.")
    add.add_argument("--start", required=True, type=_date_arg, help="First coverage date, YYYY-MM-DD.")
    add.add_argument("--end", type=_date_arg, help="Named coverage end date, YYYY-MM-DD.")
    add.add_argument(
        "--extend-weekdays",
        type=_count_arg,
        default=0,
        help="Add this many school weekdays. With --end, they come after the named end.",
    )
    add.add_argument("--time", required=True, help="Session clock time, such as 3:30pm-4:30pm.")
    add.add_argument("--weekdays", default="mon-fri", help="Subset of Mon–Fri. Default: mon-fri.")
    add.add_argument("--rate", required=True, help="Price of one full session, such as 40.00.")
    add.add_argument(
        "--amount",
        help="Agreed price for this window. Defaults to rate × billable sessions.",
    )
    add.add_argument(
        "--half-day-policy",
        choices=[item.value for item in HalfDayPolicy],
        default=HalfDayPolicy.HALF_RATE.value,
    )
    add.add_argument(
        "--weekend-end-policy",
        choices=[item.value for item in WeekendEndPolicy],
        default=WeekendEndPolicy.ROLL_TO_MONDAY.value,
        help="Used when --end falls on Saturday or Sunday. Default rolls to the following Monday.",
    )
    add.add_argument("--note", default="", help="Short note. Do not include account numbers.")
    add.add_argument("--id", help="Optional cycle id. One is generated when omitted.")
    add.set_defaults(handler=cmd_add_cycle)

    pay = sub.add_parser("log-payment", help="Record a payment already made.")
    pay.add_argument("--cycle", required=True, help="Cycle id.")
    pay.add_argument("--amount", required=True, help="Amount received, such as 240.00.")
    pay.add_argument("--date", required=True, type=_date_arg, help="Date you recorded the payment.")
    pay.add_argument(
        "--method",
        default="recorded",
        help="Label such as cash, check, or app. Do not enter an account number.",
    )
    pay.add_argument("--memo", default="")
    pay.add_argument("--id", help="Optional payment id.")
    pay.set_defaults(handler=cmd_log_payment)

    correct = sub.add_parser(
        "correct-payment",
        help="Preview or record a reversible correction without editing the original payment.",
    )
    correct.add_argument("--payment", required=True, help="Recorded payment id to correct.")
    correct.add_argument("--amount", required=True, help="Corrected payment amount, including 0.00.")
    correct.add_argument("--date", required=True, type=_date_arg, help="Correction record date.")
    correct.add_argument("--reason", required=True, help="Short explanation; do not include account numbers.")
    correct.add_argument("--id", help="Optional correction id.")
    correct.add_argument("--preview", action="store_true", help="Show the balance effect without writing.")
    correct.set_defaults(handler=cmd_correct_payment)

    undo = sub.add_parser(
        "undo-correction",
        help="Preview or record an immutable undo for a payment correction.",
    )
    undo.add_argument("--correction", required=True, help="Correction id to undo.")
    undo.add_argument("--date", required=True, type=_date_arg, help="Undo record date.")
    undo.add_argument("--reason", required=True, help="Short explanation; do not include account numbers.")
    undo.add_argument("--id", help="Optional undo id.")
    undo.add_argument("--preview", action="store_true", help="Show the balance effect without writing.")
    undo.set_defaults(handler=cmd_undo_correction)

    status = sub.add_parser("status", help="Show cycles, remaining sessions, and 7-day warnings.")
    status.add_argument("--as-of", type=_date_arg, default=None, help="YYYY-MM-DD. Default: today.")
    status.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when any open cycle ends within 7 days.",
    )
    status.set_defaults(handler=cmd_status)

    sessions = sub.add_parser("sessions", help="List billable sessions for a cycle.")
    sessions.add_argument("--cycle", required=True)
    sessions.add_argument("--as-of", type=_date_arg, default=None)
    sessions.add_argument(
        "--all",
        action="store_true",
        help="List every billable session in the window, including dates before --as-of.",
    )
    sessions.set_defaults(handler=cmd_sessions)

    note = sub.add_parser("extend-note", help="Draft an extend-by-N school-weekday note.")
    note.add_argument("--cycle", required=True)
    note.add_argument("--days", required=True, type=_count_arg, help="School weekdays to add.")
    note.add_argument("--as-of", type=_date_arg, default=None)
    note.set_defaults(handler=cmd_extend_note)

    revision = sub.add_parser(
        "preview-revision",
        help="Compare one local calendar revision without accepting or saving it.",
    )
    revision.add_argument("--cycle", required=True)
    revision.add_argument("--revision", required=True, help="Local revision JSON file.")
    revision.add_argument("--as-of", type=_date_arg, default=None)
    revision.set_defaults(handler=cmd_preview_revision)

    seed = sub.add_parser("seed", help="Write the sample tutor cycle used in demos and tests.")
    seed.add_argument("--force", action="store_true", help="Replace an existing ledger file.")
    seed.set_defaults(handler=cmd_seed)

    calendar = sub.add_parser("calendar", help="Inspect the selected school calendar.")
    calendar.add_argument("--on", type=_date_arg, help="Describe one date.")
    calendar.add_argument("--from", dest="start", type=_date_arg, help="Range start.")
    calendar.add_argument("--to", dest="end", type=_date_arg, help="Range end, inclusive.")
    calendar.set_defaults(handler=cmd_calendar)
    return parser


def cmd_add_cycle(args: argparse.Namespace) -> int:
    if args.end is None and args.extend_weekdays < 1:
        raise LedgerError("Provide --end, --extend-weekdays, or both.")
    start_time, end_time = parse_session_time(args.time)
    cycle = PayCycle(
        id=args.id or _new_id("cyc"),
        payee=args.payee,
        service=args.service,
        beneficiary=args.beneficiary,
        coverage_start=args.start,
        named_end=args.end,
        extend_weekdays=args.extend_weekdays,
        weekdays=parse_weekdays(args.weekdays),
        session_start=start_time,
        session_end=end_time,
        session_rate=parse_money(args.rate),
        quoted_amount=None if args.amount is None else parse_money(args.amount),
        half_day_policy=HalfDayPolicy(args.half_day_policy),
        weekend_end_policy=WeekendEndPolicy(args.weekend_end_policy),
        note=args.note,
    )
    path = Path(args.ledger)
    # Resolve the selected calendar and coverage before mutating the ledger.
    # A missing local ICS file must not leave a cycle behind for a retry.
    calendar = _calendar(args)
    standing = project(cycle, calendar, _as_of(args), [])
    with locked_ledger(path):
        ledger = empty_ledger() if not path.exists() else load_ledger(path)
        ledger.add_cycle(cycle)
        save_ledger(path, ledger)
    who = f" for {cycle.beneficiary}" if cycle.beneficiary else ""
    print(f"Added {cycle.id}")
    print(f"  {cycle.service}{who}")
    print(f"  Payee: {cycle.payee}")
    print(
        f"  {format_weekdays(cycle.weekdays)}, "
        f"{format_session_time(cycle.session_start, cycle.session_end)}"
    )
    print(f"  Coverage through {format_date(standing.effective_end)}")
    print(
        f"  {format_units(standing.total_units)} billable sessions, "
        f"agreed {format_money(standing.agreed_amount)}"
    )
    return 0


def cmd_log_payment(args: argparse.Namespace) -> int:
    path = Path(args.ledger)
    payment = Payment(
        id=args.id or _new_id("pay"),
        cycle_id=args.cycle,
        paid_on=args.date,
        amount=parse_money(args.amount, allow_zero=False),
        method=args.method,
        memo=args.memo,
    )
    calendar = _calendar(args)
    with locked_ledger(path):
        ledger = load_ledger(path)
        cycle = ledger.cycle(payment.cycle_id)
        # Validate projection against the proposed state before writing. This keeps
        # save_ledger's atomic replacement while avoiding partial commands.
        proposed_payments = [
            *ledger.effective_payments_for(payment.cycle_id, through=payment.paid_on),
            payment,
        ]
        standing = project(cycle, calendar, payment.paid_on, proposed_payments)
        ledger.log_payment(payment)
        save_ledger(path, ledger)
    print(
        f"Recorded {payment.id}: {format_money(payment.amount)} "
        f"on {payment.paid_on.isoformat()} ({payment.method})"
    )
    print(f"  Balance on {payment.cycle_id}: {format_money(standing.balance)}")
    return 0


def cmd_correct_payment(args: argparse.Namespace) -> int:
    path = Path(args.ledger)
    calendar = _calendar(args)
    with locked_ledger(path):
        ledger = load_ledger(path)
        original = ledger.payment(args.payment)
        correction = PaymentCorrection(
            id=args.id or _new_id("cor"),
            payment_id=original.id,
            cycle_id=original.cycle_id,
            corrected_amount=parse_money(args.amount),
            corrected_on=args.date,
            reason=args.reason,
        )
        preview = preview_payment_correction(ledger, correction, calendar)
        if not args.preview:
            ledger.add_correction(correction)
            save_ledger(path, ledger)
    _render_correction_preview(preview, label="Correction")
    if args.preview:
        print("Preview only; no ledger changes were written.")
    else:
        print(f"Recorded correction {correction.id}; original payment {original.id} is retained.")
    return 0


def cmd_undo_correction(args: argparse.Namespace) -> int:
    path = Path(args.ledger)
    calendar = _calendar(args)
    with locked_ledger(path):
        ledger = load_ledger(path)
        reversal = CorrectionReversal(
            id=args.id or _new_id("rev"),
            correction_id=args.correction,
            reversed_on=args.date,
            reason=args.reason,
        )
        preview = preview_correction_reversal(ledger, reversal, calendar)
        if not args.preview:
            ledger.add_correction_reversal(reversal)
            save_ledger(path, ledger)
    _render_correction_preview(preview, label="Correction undo")
    if args.preview:
        print("Preview only; no ledger changes were written.")
    else:
        print(f"Recorded correction undo {reversal.id}; correction {reversal.correction_id} is retained.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ledger = load_ledger(Path(args.ledger))
    calendar = _calendar(args)
    as_of = _as_of(args)
    label = getattr(calendar, "label", "school calendar")
    print(f"Tutor Pay Ledger — as of {format_date(as_of)}")
    print(f"Calendar: {label}")
    if not ledger.cycles:
        print("No cycles yet. Add one with `tutor-ledger add-cycle`, or run `tutor-ledger seed`.")
        return 0
    warned = False
    standings = [
        project(
            cycle,
            calendar,
            as_of,
            ledger.effective_payments_for(cycle.id, through=as_of),
        )
        for cycle in ledger.cycles
    ]
    standings.sort(key=lambda item: (item.effective_end, item.cycle.id))
    for standing in standings:
        print("")
        print(_render_cycle(standing, ledger))
        if standing.warning:
            warned = True
    if warned and args.strict:
        return 2
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    ledger = load_ledger(Path(args.ledger))
    cycle = ledger.cycle(args.cycle)
    as_of = _as_of(args)
    standing = project(
        cycle,
        _calendar(args),
        as_of,
        ledger.effective_payments_for(cycle.id, through=as_of),
    )
    rows = standing.sessions if args.all else standing.remaining
    who = f", {cycle.beneficiary}" if cycle.beneficiary else ""
    scope = "Sessions" if args.all else "Remaining sessions"
    print(f"{scope} for {cycle.id} ({cycle.service}{who})")
    print(f"As of {format_date(standing.as_of)}. Coverage through {format_date(standing.effective_end)}.")
    print("")
    if not rows:
        print("  No billable sessions in this view.")
    for line in rows:
        extra = f"  {line.name}" if line.name else ""
        print(
            f"  {format_date(line.day):<16}  {_weight_word(line.weight):<4}  "
            f"{format_money(line.amount):>8}{extra}"
        )
    print("")
    if args.all:
        value = sum((line.amount for line in standing.sessions), Decimal("0"))
        print(
            f"{format_units(standing.total_units)} sessions in the window. "
            f"Scheduled value {format_money(value)} at the session rate."
        )
    else:
        value = sum((line.amount for line in standing.remaining), Decimal("0"))
        print(
            f"{format_units(standing.remaining_units)} sessions remaining. "
            f"Scheduled value {format_money(value)} at the session rate."
        )
    print(
        f"Balance on the agreement is {format_money(standing.balance)} "
        f"(agreed {format_money(standing.agreed_amount)}, paid {format_money(standing.paid)})."
    )
    if standing.warning:
        print(f"WARNING: {standing.warning}")
    return 0


def cmd_extend_note(args: argparse.Namespace) -> int:
    if args.days < 1:
        raise LedgerError("Extend-by count must be at least 1.")
    ledger = load_ledger(Path(args.ledger))
    cycle = ledger.cycle(args.cycle)
    calendar = _calendar(args)
    as_of = _as_of(args)
    standing = project(
        cycle,
        calendar,
        as_of,
        ledger.effective_payments_for(cycle.id, through=as_of),
    )
    sys.stdout.write(draft_extend_note(cycle, calendar, args.days, standing))
    return 0


def cmd_preview_revision(args: argparse.Namespace) -> int:
    ledger = load_ledger(Path(args.ledger))
    cycle = ledger.cycle(args.cycle)
    as_of = _as_of(args)
    preview = preview_revision(
        cycle,
        _calendar(args),
        load_revision(args.revision),
        as_of,
        ledger.effective_payments_for(cycle.id, through=as_of),
    )
    _render_revision_preview(preview)
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    path = Path(args.ledger)
    with locked_ledger(path):
        if path.exists() and not args.force:
            raise LedgerError(f"{path} already exists. Pass --force to replace it.")
        save_ledger(path, build_seed_ledger())
    print(f"Wrote sample ledger to {path}")
    print("  Payee: Personal school tutor")
    print("  For: CJ")
    print("  Service: Mathematics, weekdays 3:30–4:30 PM")
    print("  Coverage: Mon Sep 28, 2026 through Fri Oct 16, 2026")
    print("  Recorded payment: $240.00 by check on 2026-09-28")
    return 0


def cmd_calendar(args: argparse.Namespace) -> int:
    calendar = _calendar(args)
    label = getattr(calendar, "label", "school calendar")
    if args.on is not None:
        described = calendar.describe(args.on)
        name = f"  {described.name}" if described.name else ""
        print(f"{format_date(args.on)}  {described.kind.value}{name}")
        return 0
    if args.start is None and args.end is None:
        print(f"Calendar: {label}")
        print("Pass --on YYYY-MM-DD or --from YYYY-MM-DD --to YYYY-MM-DD.")
        return 0
    if args.start is None or args.end is None:
        raise LedgerError("Provide both --from and --to.")
    if args.end < args.start:
        raise LedgerError("Calendar range end is before the start.")
    span = (args.end - args.start).days
    if span > 400:
        raise LedgerError("Calendar range is limited to 400 days.")
    print(f"Calendar: {label}")
    cursor = args.start
    while cursor <= args.end:
        described = calendar.describe(cursor)
        name = f"  {described.name}" if described.name else ""
        print(f"  {format_date(cursor)}  {described.kind.value}{name}")
        cursor += timedelta(days=1)
    return 0


def _render_correction_preview(preview, *, label: str) -> None:
    delta = preview.balance_delta
    sign = "+" if delta >= 0 else ""
    print(f"{label} preview")
    print(f"  Balance before: {format_money(preview.before.balance)}")
    print(f"  Balance after:  {format_money(preview.after.balance)}")
    print(f"  Balance effect: {sign}{format_money(delta)}")


def _render_revision_preview(preview) -> None:
    before = preview.before
    after = preview.after
    print(f"Calendar revision preview for {before.cycle.id}")
    print(f"  Source: {preview.revision.source_name}")
    print(f"  Summary: {preview.revision.summary}")
    print("  Requested dates:")
    for change in preview.changed_days:
        print(
            f"    {change.day.isoformat()}  {change.before.kind.value} -> "
            f"{change.after.kind.value}; scheduled value "
            f"{format_money(change.session_value_before)} -> "
            f"{format_money(change.session_value_after)}"
        )
    value_sign = "+" if preview.session_value_delta >= 0 else ""
    print(
        f"  Sessions: {format_units(before.total_units)} -> "
        f"{format_units(after.total_units)}"
    )
    print(
        f"  Scheduled value: {format_money(preview.scheduled_value_before)} -> "
        f"{format_money(preview.scheduled_value_after)} "
        f"({value_sign}{format_money(preview.session_value_delta)})"
    )
    print(
        f"  Recorded payments unchanged: {format_money(before.paid)} -> "
        f"{format_money(after.paid)}"
    )
    print("Preview only; no calendar or ledger changes were written.")


def _render_cycle(standing, ledger) -> str:
    cycle = standing.cycle
    lines = [cycle.id, f"  Service:      {cycle.service}"]
    if cycle.beneficiary:
        lines.append(f"  For:          {cycle.beneficiary}")
    lines.append(f"  Payee:        {cycle.payee}")
    lines.append(
        "  When:         "
        f"{format_weekdays(cycle.weekdays)}, "
        f"{format_session_time(cycle.session_start, cycle.session_end)}"
    )
    lines.append(
        "  Coverage:     "
        f"{format_date(cycle.coverage_start)} through {format_date(standing.effective_end)}"
    )
    lines.extend(_end_rule_lines(cycle, standing.effective_end))
    lines.append(f"  State:        {standing.state}")
    lines.append(
        "  Billable:     "
        f"{format_units(standing.total_units)} sessions in the window, "
        f"{format_units(standing.remaining_units)} remaining"
    )
    lines.append(f"  Agreed:       {format_money(standing.agreed_amount)}")
    lines.append(f"  Paid as of:   {format_money(standing.paid)}")
    lines.append(f"  Balance:      {format_money(standing.balance)}")
    payments = ledger.payments_for(cycle.id, through=standing.as_of)
    if payments:
        lines.append("  Payments:")
        for payment in payments:
            memo = f"  {payment.memo}" if payment.memo else ""
            lines.append(
                f"    {payment.paid_on.isoformat()}  {format_money(payment.amount)}  "
                f"{payment.method}{memo}"
            )
    corrections = [
        correction
        for correction in ledger.corrections
        if correction.cycle_id == cycle.id and correction.corrected_on <= standing.as_of
    ]
    if corrections:
        lines.append("  Payment corrections:")
        reversal_dates = {
            reversal.correction_id: reversal.reversed_on
            for reversal in ledger.correction_reversals
            if reversal.reversed_on <= standing.as_of
        }
        for correction in corrections:
            state = "reversed" if correction.id in reversal_dates else "active"
            original = ledger.payment(correction.payment_id)
            details = (
                f"    {correction.corrected_on.isoformat()}  {correction.id}  "
                f"{original.id}: {format_money(original.amount)} -> "
                f"{format_money(correction.corrected_amount)}  {state}"
            )
            lines.append(details)
            lines.append(f"      Reason: {correction.reason}")
            if correction.id in reversal_dates:
                lines.append(f"      Reversed on: {reversal_dates[correction.id].isoformat()}")
    if standing.warning:
        lines.append(f"  WARNING:      {standing.warning}")
    elif standing.state == "ended":
        lines.append(f"  Coverage ended {format_date(standing.effective_end)}.")
    return "\n".join(lines)


def _end_rule_lines(cycle: PayCycle, effective_end: date) -> list[str]:
    if cycle.named_end is None:
        return [f"  Span:         {cycle.extend_weekdays} school weekdays from the start."]
    lines: list[str] = []
    if cycle.named_end != effective_end or cycle.named_end.weekday() >= 5:
        lines.append(
            f"  Named end:    {format_date(cycle.named_end)} ({cycle.weekend_end_policy.value})."
        )
    if cycle.named_end.weekday() >= 5 and cycle.weekend_end_policy == WeekendEndPolicy.ROLL_TO_MONDAY:
        lines.append("  Weekend rule: a Saturday or Sunday end covers through the following Monday.")
    if cycle.extend_weekdays:
        lines.append(f"  Extension:    {cycle.extend_weekdays} additional school weekdays after the named end.")
    return lines


def _calendar(args: argparse.Namespace):
    if args.calendar == "fixture":
        return FixtureCalendarProvider().load()
    if args.calendar == "sample-ics":
        return SampleIcsProvider().load()
    if not args.ics:
        raise LedgerError("Pass --ics PATH when --calendar is ics. The feed is read from disk only.")
    if (
        args.ics_effective_from is None
        or args.ics_effective_through is None
        or args.ics_out_of_coverage is None
    ):
        raise LedgerError(
            "Local ICS configuration requires --ics-effective-from, --ics-effective-through, "
            "and --ics-out-of-coverage (closed or error)."
        )
    return IcsFileProvider(
        args.ics,
        effective_from=args.ics_effective_from,
        effective_through=args.ics_effective_through,
        out_of_coverage=args.ics_out_of_coverage,
    ).load()


def _as_of(args: argparse.Namespace) -> date:
    value = getattr(args, "as_of", None)
    return date.today() if value is None else value


def _weight_word(weight: Decimal) -> str:
    if weight == 1:
        return "full"
    if weight == _HALF:
        return "half"
    return format_units(weight)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD.") from exc


def _count_arg(value: str) -> int:
    if not value.isdigit():
        raise argparse.ArgumentTypeError("Use a whole number of weekdays, 0 or more.")
    return int(value)
