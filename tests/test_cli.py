"""CLI flows against a temporary ledger. No network and no shared data file."""

import json
import subprocess
import sys
from pathlib import Path

from tutor_pay_ledger.cli import main
from tutor_pay_ledger.seed import SEED_CYCLE_ID

ROOT = Path(__file__).resolve().parents[1]


def _seed(tmp_path: Path) -> Path:
    ledger = tmp_path / "ledger.json"
    assert main(["--ledger", str(ledger), "seed"]) == 0
    return ledger


def test_module_help_runs_offline():
    completed = subprocess.run(
        [sys.executable, "-m", "tutor_pay_ledger", "--help"],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "add-cycle" in completed.stdout
    assert "extend-note" in completed.stdout


def _env() -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def test_status_sessions_warning_and_extend_note(tmp_path: Path, capsys):
    ledger = _seed(tmp_path)
    capsys.readouterr()

    assert main(["--ledger", str(ledger), "status", "--as-of", "2026-10-05", "--strict"]) == 0
    quiet = capsys.readouterr().out
    assert "Personal school tutor" in quiet
    assert "CJ" in quiet
    assert "Mathematics" in quiet
    assert "3:30 PM" in quiet
    assert "13.5" in quiet
    assert "8.5" in quiet
    assert "$540.00" in quiet
    assert "$240.00" in quiet
    assert "$300.00" in quiet
    assert "WARNING" not in quiet

    assert main(["--ledger", str(ledger), "status", "--as-of", "2026-10-09", "--strict"]) == 2
    warned = capsys.readouterr().out
    assert "Coverage ends within 7 days (7 days left)." in warned

    assert main(["--ledger", str(ledger), "sessions", "--cycle", SEED_CYCLE_ID, "--as-of", "2026-10-05"]) == 0
    sessions = capsys.readouterr().out
    assert "Mon Oct 12, 2026" not in sessions
    assert "Fri Oct 16, 2026" in sessions
    assert "half" in sessions

    before = ledger.read_text(encoding="utf-8")
    assert (
        main(
            [
                "--ledger",
                str(ledger),
                "extend-note",
                "--cycle",
                SEED_CYCLE_ID,
                "--days",
                "5",
                "--as-of",
                "2026-10-05",
            ]
        )
        == 0
    )
    note = capsys.readouterr().out
    assert "Fri Oct 23, 2026" in note
    assert "does not move money" in note
    assert ledger.read_text(encoding="utf-8") == before


def test_add_cycle_rolls_a_saturday_end_and_rejects_a_weekend_window(tmp_path: Path, capsys):
    ledger = tmp_path / "ledger.json"
    code = main(
        [
            "--ledger",
            str(ledger),
            "add-cycle",
            "--payee",
            "Neighborhood piano",
            "--service",
            "Piano",
            "--beneficiary",
            "CJ",
            "--start",
            "2026-10-05",
            "--end",
            "2026-10-17",
            "--time",
            "3:30pm-4:30pm",
            "--rate",
            "40",
            "--weekdays",
            "mon,wed",
            "--id",
            "cyc_piano",
        ]
    )
    assert code == 0
    added = capsys.readouterr().out
    assert "Mon Oct 19, 2026" in added

    assert main(["--ledger", str(ledger), "status", "--as-of", "2026-10-05"]) == 0
    status = capsys.readouterr().out
    assert "following Monday" in status
    assert "Neighborhood piano" in status

    rejected = main(
        [
            "--ledger",
            str(ledger),
            "add-cycle",
            "--payee",
            "Neighborhood piano",
            "--service",
            "Piano",
            "--start",
            "2026-10-05",
            "--end",
            "2026-10-16",
            "--time",
            "15:30-16:30",
            "--rate",
            "40",
            "--weekdays",
            "sat",
        ]
    )
    assert rejected == 1
    assert "Monday–Friday only" in capsys.readouterr().err
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert [cycle["id"] for cycle in saved["cycles"]] == ["cyc_piano"]


def test_log_payment_updates_balance_and_refuses_account_numbers(tmp_path: Path, capsys):
    ledger = _seed(tmp_path)
    capsys.readouterr()
    assert (
        main(
            [
                "--ledger",
                str(ledger),
                "log-payment",
                "--cycle",
                SEED_CYCLE_ID,
                "--amount",
                "100.00",
                "--date",
                "2026-10-05",
                "--method",
                "cash",
                "--memo",
                "October top-up",
                "--id",
                "pay_oct_topup",
            ]
        )
        == 0
    )
    assert "$200.00" in capsys.readouterr().out

    before = ledger.read_text(encoding="utf-8")
    refused = main(
        [
            "--ledger",
            str(ledger),
            "log-payment",
            "--cycle",
            SEED_CYCLE_ID,
            "--amount",
            "10.00",
            "--date",
            "2026-10-06",
            "--method",
            "routing 021000021",
            "--memo",
            "nope",
        ]
    )
    assert refused == 1
    assert "bank credentials" in capsys.readouterr().err
    assert ledger.read_text(encoding="utf-8") == before


def test_add_or_payment_calendar_failure_never_writes_a_partial_ledger(tmp_path: Path, capsys):
    new_ledger = tmp_path / "new-ledger.json"
    add = main(
        [
            "--ledger",
            str(new_ledger),
            "--calendar",
            "ics",
            "add-cycle",
            "--payee",
            "Fictional service",
            "--service",
            "Reading",
            "--start",
            "2026-10-05",
            "--end",
            "2026-10-16",
            "--time",
            "3:30pm-4:30pm",
            "--rate",
            "40",
        ]
    )
    assert add == 1
    assert not new_ledger.exists()
    assert "Pass --ics PATH" in capsys.readouterr().err

    ledger = _seed(tmp_path)
    capsys.readouterr()
    before = ledger.read_bytes()
    payment = main(
        [
            "--ledger",
            str(ledger),
            "--calendar",
            "ics",
            "log-payment",
            "--cycle",
            SEED_CYCLE_ID,
            "--amount",
            "10.00",
            "--date",
            "2026-10-05",
        ]
    )
    assert payment == 1
    assert ledger.read_bytes() == before
    assert "Pass --ics PATH" in capsys.readouterr().err


def test_calendar_command_and_seed_guard(tmp_path: Path, capsys):
    ledger = _seed(tmp_path)
    assert main(["--ledger", str(ledger), "seed"]) == 1
    assert "already exists" in capsys.readouterr().err

    assert main(["--ledger", str(ledger), "calendar", "--on", "2026-10-12"]) == 0
    described = capsys.readouterr().out
    assert "holiday" in described
    assert "Indigenous Peoples' Day" in described

    assert main(["--ledger", str(ledger), "--calendar", "sample-ics", "calendar", "--on", "2026-10-16"]) == 0
    assert "half_day" in capsys.readouterr().out


def test_store_round_trip_preserves_the_seed(tmp_path: Path):
    from tutor_pay_ledger.seed import build_seed_ledger
    from tutor_pay_ledger.store import load_ledger, save_ledger

    path = tmp_path / "nested" / "ledger.json"
    original = build_seed_ledger()
    save_ledger(path, original)
    loaded = load_ledger(path)
    assert loaded.cycles[0].id == original.cycles[0].id
    assert loaded.cycles[0].quoted_amount == original.cycles[0].quoted_amount
    assert loaded.cycles[0].weekdays == original.cycles[0].weekdays
    assert loaded.payments[0].amount == original.payments[0].amount
    assert loaded.payments[0].method == "check"
