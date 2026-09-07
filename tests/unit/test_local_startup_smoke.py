"""Deterministic offline smoke test for QuantumValidator local startup and CLI workflows."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from aditrader.cli import build_parser
from aditrader.cli.commands import (
    cmd_backtest,
    cmd_dashboard,
    cmd_doctor,
    cmd_forward_test,
    cmd_init_db,
    cmd_search,
    cmd_status,
    cmd_strategies,
    cmd_validate,
)


class DummyArgs:
    """Helper to mock argparse namespace."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_cli_parser_registered_commands() -> None:
    """Verify all canonical operations are registered in the CLI parser."""
    parser = build_parser()
    subparsers = [action for action in parser._actions if action.dest == "subcommand"]
    assert len(subparsers) == 1
    choices = subparsers[0].choices
    assert choices is not None
    assert "doctor" in choices
    assert "status" in choices
    assert "init-db" in choices
    assert "strategies" in choices
    assert "search" in choices
    assert "validate" in choices
    assert "backtest" in choices
    assert "dashboard" in choices
    assert "forward-test" in choices


def test_cmd_doctor_offline_readiness(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_doctor checks runtime, dependencies, directories, and returns 0."""
    args = DummyArgs()
    exit_code = cmd_doctor(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "[READY]" in captured.out
    assert "Python Runtime:" in captured.out
    assert "Core Dependencies:" in captured.out
    assert "SYSTEM READY FOR OFFLINE RESEARCH & LOCAL REPLAY" in captured.out
    # Missing optional keys must not fail the doctor check
    assert "[OPTIONAL/MISSING]" in captured.out


def test_cmd_status_reporting(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_status reports environment, database state, and strategy count."""
    args = DummyArgs()
    exit_code = cmd_status(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "AdiTrader / QuantumValidator — Status" in captured.out
    assert "Strategy Library:  4 registered built-in templates" in captured.out
    assert "Nifty Weekly Iron Condor" in captured.out


def test_cmd_init_db_in_temp_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify cmd_init_db initializes all SQLite tables cleanly."""
    temp_db = tmp_path / "test_ledger.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{temp_db}")

    args = DummyArgs()
    exit_code = cmd_init_db(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "[READY] Database successfully initialized with" in captured.out
    assert "orders" in captured.out
    assert "trades" in captured.out
    assert "positions" in captured.out
    assert temp_db.is_file()


def test_cmd_strategies_listing_and_detail(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_strategies lists catalog and displays DNA detail."""
    # 1. Listing
    args_list = DummyArgs(detail=None)
    exit_code = cmd_strategies(args_list)  # type: ignore[arg-type]
    out_list = capsys.readouterr().out
    assert exit_code == 0
    assert "Registered Strategy Templates" in out_list
    assert "Nifty Weekly Iron Condor" in out_list

    # 2. Detail
    args_detail = DummyArgs(detail="iron_condor")
    exit_code_detail = cmd_strategies(args_detail)  # type: ignore[arg-type]
    out_detail = capsys.readouterr().out
    assert exit_code_detail == 0
    assert "Strategy:       Nifty Weekly Iron Condor" in out_detail
    assert "Strategy DNA:" in out_detail
    assert "Direction:      Delta-Neutral" in out_detail
    assert "Option Legs:    4 defined" in out_detail


def test_cmd_search_scrip_contracts(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_search finds contracts in mock adapter."""
    args = DummyArgs(query="NIFTY", limit=5)
    exit_code = cmd_search(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Search Results for: 'NIFTY'" in captured.out
    assert "NIFTY" in captured.out
    assert "NIFTY24DEC24000CE" in captured.out


def test_cmd_validate_options_strategy(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_validate evaluates option strategy under institutional policy."""
    args = DummyArgs(strategy="iron_condor", file=None, policy="institutional")
    exit_code = cmd_validate(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Validating Strategy: 'Nifty Weekly Iron Condor' (Policy: Institutional)" in captured.out
    assert "Final Verdict:         APPROVED" in captured.out
    assert "Validation Path:       THEORETICAL (THEORETICAL)" in captured.out


def test_cmd_backtest_linear_asset(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_backtest runs deterministic simulation with recorded assumptions."""
    args = DummyArgs(
        strategy="test_ma_crossover",
        file=None,
        csv=None,
        bars=50,
        capital=500_000.0,
        slippage_bps=2.5,
    )
    exit_code = cmd_backtest(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Backtest Simulation: 'test_ma_crossover' on NIFTY" in captured.out
    assert "Processed Bars:        50" in captured.out
    assert "Recorded Simulation Assumptions:" in captured.out
    assert "NEXT_BAR_OPEN" in captured.out
    assert "NSE_STATUTORY" in captured.out


def test_cmd_backtest_options_air_gap_guard(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_backtest rejects option strategies with air-gap error (ADR 011)."""
    args = DummyArgs(
        strategy="iron_condor",
        file=None,
        csv=None,
        bars=50,
        capital=500_000.0,
        slippage_bps=2.5,
    )
    exit_code = cmd_backtest(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[AIR-GAP GUARD]" in captured.out
    assert "strictly prohibits silent proxy simulation of multi-leg option" in captured.out


def test_cmd_dashboard_roadmap_notice(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_dashboard informs user of Phase 8 schedule."""
    args = DummyArgs()
    exit_code = cmd_dashboard(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "scheduled for Phase 8" in captured.out


def test_cmd_forward_test_usage_and_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_forward_test displays usage guide without args and runs cleanly with strategy."""
    # 1. Usage guide without args
    args_empty = DummyArgs(strategy=None)
    exit_code_empty = cmd_forward_test(args_empty)  # type: ignore[arg-type]
    captured_empty = capsys.readouterr()

    assert exit_code_empty == 0
    assert "Forward-Testing & Paper-Trading Runner" in captured_empty.out
    assert "NO REAL ORDERS ARE EVER ROUTED" in captured_empty.out

    # 2. Runnable session with mock rehearsal
    dossier_out = tmp_path / "smoke_forward_session.json"
    args_run = DummyArgs(
        strategy="test_ma_crossover",
        instrument="NIFTY",
        timeframe="1m",
        capital=1_000_000.0,
        slippage_bps=2.5,
        mock=True,
        ticks=5,
        bars=None,
        duration=None,
        output=str(dossier_out),
        strict_quality=False,
    )
    exit_code_run = cmd_forward_test(args_run)  # type: ignore[arg-type]
    captured_run = capsys.readouterr()

    assert exit_code_run == 0
    assert "Forward-Testing Session Summary" in captured_run.out
    assert "COMPLETED" in captured_run.out
    assert dossier_out.is_file()


def test_cli_main_entrypoint_execution() -> None:
    """Verify CLI entrypoint dispatches subprocess cleanly."""
    res = subprocess.run(
        [sys.executable, "-m", "aditrader.cli", "doctor"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "SYSTEM READY FOR OFFLINE RESEARCH & LOCAL REPLAY" in res.stdout
