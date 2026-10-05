# Tutor Pay Ledger

![Tutor Pay Ledger](docs/cover.jpg)

Tutor Pay Ledger is a small payment ledger for recurring **weekday** services. A school tutor is the flagship example (student CJ, mathematics, 3:30–4:30 PM). The same rules cover any service that should follow a school week: piano on Wednesdays, after-school help on Monday and Thursday, a reading block every weekday.

It tracks coverage, not a bank account. You record an agreed rate, a coverage window, and payments you have already made. It drafts a note when you want to extend coverage. It does not store card numbers, routing numbers, or other credentials, and it does not move money.

The cover art is a product illustration (it shows a May 2025 week). The runnable sample below is the October 2026 tutor cycle.

## Rules

Sessions exist only on the weekdays you name, and those weekdays are Monday–Friday. Saturday and Sunday never bill, never count toward an extension, and cannot be added to a weekday window. A calendar feed that marks Saturday as "in session" is ignored for billing.

| Situation | What the ledger does |
| --- | --- |
| Weekend | Not a session. Does not consume an extend-by-N day. |
| Holiday or break | Not a session. Does not consume an extend-by-N day. |
| Half-day, policy `half_rate` (default) | Counts as **one** school weekday. Bills at **half** the session rate. |
| Half-day, policy `skip` | Not a session. Does not consume an extend-by-N day. |
| Weekday the service does not run | Not a session for this cycle (a Wednesday piano lesson does not bill on Monday). |
| Date outside the sample school year | Treated as a break by the fixture calendar, so summer is not billed by accident. An ICS feed does not invent that boundary; unlisted weekdays on a feed count as in session. |

**Named end on a weekend.** Sessions are not held on the weekend, so a coverage end of Saturday or Sunday needs a rule. The default, `roll_to_monday`, moves the boundary to the **following Monday** and that Monday is inside the window. Saturday 17 October 2026 and Sunday 18 October 2026 both cover through Monday 19 October 2026.

If that Monday is a holiday, the boundary still lands on Monday and the day bills nothing. The last billable session may be the Friday before. Use `roll_to_next_session` when the boundary should keep walking until it reaches a day that actually bills (a half-day counts only under `half_rate`). Use `strict` to keep the named weekend date and leave Monday outside the window.

**Extend by N weekdays.** N is a count of billable school weekdays, not calendar days. The walk starts the day after the effective end (or on the coverage start, when you give a count and no end date, and the start itself bills). Weekends, holidays, breaks, and skipped half-days are stepped over and do not use up N.

**Seven-day warning.** A cycle that is still open warns when the effective end is within **7 calendar days** of the as-of date, including the 7th day and including "ends today". Days already past the end are "coverage ended", not a warning. `status --strict` exits with code 2 when any open cycle is inside that window, so a reminder job can notice it. The warning is calendar days, not school days: a Friday end starts warning on the previous Friday.

**Remaining sessions** are billable dates on or after the as-of date, through the effective end. Today is included. The scheduled value of those sessions (rate × weight) is separate from the agreement balance (agreed amount minus payments you logged).

## Run it

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

tutor-ledger seed
tutor-ledger status --as-of 2026-10-05
tutor-ledger sessions --cycle cyc_cj_math_2026oct --as-of 2026-10-05
tutor-ledger calendar --on 2026-10-12
tutor-ledger extend-note --cycle cyc_cj_math_2026oct --days 5 --as-of 2026-10-05
pytest
```

`seed` writes `data/ledger.json` (gitignored). Pass `--ledger path.json` to use another file. Pass `--force` to replace a seed file that is already there.

On 5 October 2026 the sample cycle still has 8.5 sessions and does not warn (the end is 11 calendar days out). On 9 October 2026 it warns: coverage ends within 7 days. `--strict` then exits 2.

Check the calendar the status command is using:

```bash
tutor-ledger calendar --on 2026-10-16
tutor-ledger --calendar sample-ics calendar --from 2026-10-12 --to 2026-10-16
```

Add another service (this one is not tutoring) and record a payment. `--method` is a label such as `cash`, `check`, or `app`.

```bash
tutor-ledger add-cycle \
  --payee "Neighborhood piano" \
  --service "Piano" \
  --beneficiary "CJ" \
  --start 2026-10-05 \
  --end 2026-10-17 \
  --time 3:30pm-4:30pm \
  --weekdays mon,wed \
  --rate 35.00 \
  --weekend-end-policy roll_to_monday

tutor-ledger log-payment \
  --cycle cyc_cj_math_2026oct \
  --amount 100.00 \
  --date 2026-10-05 \
  --method cash \
  --memo "October top-up"
```

The Saturday end date rolls through Monday 19 October 2026. `--amount` on `add-cycle` is optional; when you omit it, the agreed price is the session rate times billable units in the window (half-days at half rate).

`extend-note` only prints a draft. It does not change the ledger and it does not ask anyone for payment details.

A window can also be defined as a count of school weekdays from the start, with no named end:

```bash
tutor-ledger add-cycle \
  --payee "Personal school tutor" \
  --service "Mathematics" \
  --beneficiary "CJ" \
  --start 2026-10-05 \
  --extend-weekdays 10 \
  --time 15:30-16:30 \
  --rate 40.00
```

Giving both `--end` and `--extend-weekdays` keeps the named end (after the weekend rule) and then adds N more school weekdays.

## Sample cycle

Demo and test data only:

| Field | Value |
| --- | --- |
| Payee | Personal school tutor |
| For | CJ |
| Service | Mathematics |
| When | Monday–Friday, 3:30–4:30 PM |
| Coverage | Monday 28 September 2026 through Friday 16 October 2026 |
| Half-day policy | `half_rate` |
| Weekend-end policy | `roll_to_monday` |
| Session rate | $40.00 |
| Billable units | 13.5 (Friday 16 October is an early release) |
| Agreed amount | $540.00 |
| Payment already recorded | $240.00 by check on 28 September 2026 |
| Balance | $300.00 |

Indigenous Peoples' Day, Monday 12 October 2026, is inside the window and is not billed. Extending that cycle by 5 school weekdays runs through Friday 23 October 2026 and estimates $200.00.

## School calendar

`SchoolCalendar` answers one question: what is this civil date for school? Providers:

- **`fixture`** (default) — Sample District 2026–27, a fictional US school year in `tutor_pay_ledger.calendars.fixture`. First day Monday 24 August 2026, last day Friday 11 June 2027 (a half-day). Includes Labor Day, Indigenous Peoples' Day, Veterans Day, Thanksgiving recess, winter break, Martin Luther King Jr. Day, Presidents Day, spring break, Good Friday, Memorial Day, and three half-days (16 October 2026, 18 December 2026, 11 June 2027). This is not a real district's calendar.
- **`sample-ics`** — a short ICS fragment shipped at `src/tutor_pay_ledger/data/sample_district.ics`. Same October closures as the fixture, plus Thanksgiving recess. Offline.
- **`ics`** — `--ics path/to/school.ics` reads a file you already have. It does not download a URL. All-day events become closures. `CATEGORIES` of `HALF-DAY` / `EARLY-RELEASE` (or a summary that says "half" or "early release") become half-days. `BREAK`, `VACATION`, `RECESS`, or a summary that says "break" or "recess", become breaks. Other all-day events are holidays. `DTEND;VALUE=DATE` is exclusive. Timed events are ignored. A later event in the file wins on the same date.

**Update hook.** `CalendarUpdateHook.poll()` is the seam for a bot that watches a school site, an ICS URL, or an inbox drop. `NullCalendarUpdateHook` is the default stub: it returns nothing and never opens a network connection. `ManualRevisionHook` holds one `CalendarRevision` for a test or a hand-applied change. `apply_revision` overlays those days onto a calendar. Weekend overrides still cannot create a Saturday session.

Wire a bot by implementing `poll`, pointing it at a local export, and passing the revision through `apply_revision` before you project a cycle. Keep the fetch outside this library so tests stay offline.

## Layout

```
src/tutor_pay_ledger/
  cli.py            add-cycle, log-payment, status, sessions, extend-note, seed, calendar
  coverage.py       weekday walk, half-day policy, weekend-end rule, 7-day warning
  ledger.py         cycles, payments, standing
  notes.py          extend-by-N draft
  seed.py           CJ / mathematics sample
  store.py          JSON file
  calendars/        fixture, ICS parser, update hook
tests/              offline pytest, no network
docs/cover.jpg
```

The console script is `tutor-ledger`. `python -m tutor_pay_ledger` runs the same entry point.

## Tests

```bash
pytest
```

Tests use the fixture calendar and small in-memory calendars. They do not read the network, and they do not need a ledger file in the repository.
