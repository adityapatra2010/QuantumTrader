"""Unit and regression tests for CLI remediation fixes.

Verifies:
1. cmd_validate linear strategy without data returns STRUCTURALLY_VALID (DATA_PENDING) exit 0.
2. cmd_validate linear strategy with --bars and --csv runs empirical validation.
3. cmd_backtest and cmd_forward_options numeric input validation fail closed cleanly.
4. cmd_runs and cmd_inspect_run list and display dossiers without crashes.
5. cmd_init_db stamps Alembic head preventing table collision on subsequent alembic upgrade head.
6. Forward options runner in mock mode emits truthful MOCK_REHEARSAL provenance.
7. Strategy registry includes test_ma_crossover and cmd_strategies --detail works.
8. Quoted strategy names in cmd_backtest hints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aditrader.cli.commands import (
    cmd_backtest,
    cmd_dashboard,
    cmd_forward_options,
    cmd_forward_test,
    cmd_init_db,
    cmd_inspect_data,
    cmd_inspect_run,
    cmd_kotak_auth,
    cmd_kotak_discover,
    cmd_kotak_history,
    cmd_runs,
    cmd_smoke_feed,
    cmd_strategies,
    cmd_validate,
)
from aditrader.data.forward_options_runner import (
    ForwardOptionsSessionConfig,
    KotakOptionForwardRunner,
)
from aditrader.strategy.library.templates import get_builtin_templates


class DummyArgs:
    """Helper to simulate argparse.Namespace."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


# ==============================================================================
# 1. Strategy Registry Unification
# ==============================================================================


def test_strategy_registry_includes_test_ma_crossover(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify test_ma_crossover is a registered template and cmd_strategies displays it."""
    templates = get_builtin_templates()
    assert "test_ma_crossover" in templates

    args = DummyArgs(detail="test_ma_crossover")
    exit_code = cmd_strategies(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Strategy:       test_ma_crossover" in captured.out
    assert "Strategy DNA:" in captured.out


# ==============================================================================
# 2. Linear Strategy Validation Paths
# ==============================================================================


def test_cmd_validate_linear_without_data_data_pending(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Linear strategy validated without data returns exit 0 with STRUCTURALLY_VALID (DATA_PENDING)."""
    args = DummyArgs(
        strategy="test_ma_crossover",
        file=None,
        policy="moderate",
        csv=None,
        bars=None,
    )
    exit_code = cmd_validate(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "STRUCTURALLY_VALID (DATA_PENDING)" in captured.out
    assert "Empirical statistical gates" in captured.out
    assert 'aditrader validate --strategy "test_ma_crossover"' in captured.out


def test_cmd_validate_linear_with_synthetic_bars(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Linear strategy validated with --bars runs backtest and evaluates empirical metrics."""
    args = DummyArgs(
        strategy="test_ma_crossover",
        file=None,
        policy="moderate",
        csv=None,
        bars=50,
    )
    exit_code = cmd_validate(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    # Backtest ran and evaluated empirical criteria
    assert "HISTORICAL" in captured.out
    assert "Empirical Metrics:" in captured.out
    assert exit_code in (0, 1)


def test_cmd_validate_linear_with_csv(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Linear strategy validated with --csv runs backtest using the dataset."""
    sample_csv = Path("data/nifty_sample.csv")
    if not sample_csv.is_file():
        pytest.skip("data/nifty_sample.csv not present")

    args = DummyArgs(
        strategy="test_ma_crossover",
        file=None,
        policy="moderate",
        csv=str(sample_csv),
        bars=None,
    )
    cmd_validate(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert "HISTORICAL" in captured.out
    assert "Empirical Metrics:" in captured.out


# ==============================================================================
# 3. Numeric Argument Validation
# ==============================================================================


def test_cmd_backtest_numeric_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cmd_backtest cleanly rejects invalid numbers without unhandled exceptions."""
    # Zero bars
    args = DummyArgs(
        strategy="test_ma_crossover",
        file=None,
        csv=None,
        bars=0,
        capital=100000.0,
        slippage_bps=2.5,
    )
    assert cmd_backtest(args) == 1  # type: ignore[arg-type]
    assert "[ERROR] Invalid --bars" in capsys.readouterr().out

    # Negative capital
    args = DummyArgs(
        strategy="test_ma_crossover",
        file=None,
        csv=None,
        bars=50,
        capital=-500.0,
        slippage_bps=2.5,
    )
    assert cmd_backtest(args) == 1  # type: ignore[arg-type]
    assert "[ERROR] Invalid --capital" in capsys.readouterr().out

    # Negative slippage
    args = DummyArgs(
        strategy="test_ma_crossover",
        file=None,
        csv=None,
        bars=50,
        capital=100000.0,
        slippage_bps=-1.0,
    )
    assert cmd_backtest(args) == 1  # type: ignore[arg-type]
    assert "[ERROR] Invalid --slippage-bps" in capsys.readouterr().out


def test_cmd_forward_options_numeric_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cmd_forward_options cleanly rejects invalid numbers without unhandled exceptions."""
    # Zero capital
    args = DummyArgs(
        strategy="tpl-nifty-ce-premium-ladder-v1",
        capital=0.0,
        slippage_bps=2.5,
        duration=10.0,
        mock=True,
    )
    assert cmd_forward_options(args) == 1  # type: ignore[arg-type]
    assert "[ERROR] Invalid --capital" in capsys.readouterr().out

    # Negative slippage
    args = DummyArgs(
        strategy="tpl-nifty-ce-premium-ladder-v1",
        capital=100000.0,
        slippage_bps=-5.0,
        duration=10.0,
        mock=True,
    )
    assert cmd_forward_options(args) == 1  # type: ignore[arg-type]
    assert "[ERROR] Invalid --slippage-bps" in capsys.readouterr().out

    # Zero duration
    args = DummyArgs(
        strategy="tpl-nifty-ce-premium-ladder-v1",
        capital=100000.0,
        slippage_bps=2.5,
        duration=0.0,
        mock=True,
    )
    assert cmd_forward_options(args) == 1  # type: ignore[arg-type]
    assert "[ERROR] Invalid --duration" in capsys.readouterr().out


# ==============================================================================
# 4. Backtest Suggestion Quoting & Accounting Separation
# ==============================================================================


def test_cmd_backtest_suggests_quoted_strategy(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cmd_backtest suggests quoted strategy name and forward-options command."""
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
    assert 'aditrader validate --strategy "test_ma_crossover"' in captured.out
    assert 'aditrader forward-options --strategy "test_ma_crossover" --mock' in captured.out
    assert (
        "Realized P&L:" in captured.out
        or "Closed Realized PnL:" in captured.out
        or "Net Realized PnL:" in captured.out
    )
    assert "[Caution: <1 day sample]" in captured.out


# ==============================================================================
# 5. Runs Listing & Deep Run Inspection
# ==============================================================================


def test_cmd_runs_and_inspect_run_clean_execution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify cmd_runs lists recorded runs and cmd_inspect_run formats dossier details."""
    # 1. Listing runs
    args_runs = DummyArgs(type=None)
    exit_code_runs = cmd_runs(args_runs)  # type: ignore[arg-type]
    assert exit_code_runs == 0

    # 2. Inspect non-existent run
    args_nonexistent = DummyArgs(id_or_path="fwd_opt_nonexistent_9999")
    exit_code_missing = cmd_inspect_run(args_nonexistent)  # type: ignore[arg-type]
    captured_missing = capsys.readouterr()
    assert exit_code_missing == 1
    assert (
        "[ERROR] Run Dossier not found for query: 'fwd_opt_nonexistent_9999'"
        in captured_missing.out
    )

    # 3. Create a synthetic dossier and inspect it
    fwd_dir = Path("runs/forward")
    fwd_dir.mkdir(parents=True, exist_ok=True)
    test_run_id = "fwd_opt_test_remed"
    dossier_file = fwd_dir / f"forward_dossier_{test_run_id}.json"

    dummy_dossier = {
        "run_id": test_run_id,
        "mode": "MOCK_REHEARSAL",
        "created_at": "2026-09-16T10:00:00+05:30",
        "strategy_id": "test_ma_crossover",
        "underlying": "NIFTY",
        "venue": "AIR_GAPPED_PAPER_BROKER",
        "initial_capital": 500000.0,
        "ending_equity": 501250.0,
        "gross_pnl": 1500.0,
        "net_pnl": 1250.0,
        "total_charges": 250.0,
        "total_orders": 2,
        "total_fills": 2,
        "executed_trades_count": 1,
        "reconciliation_balance": True,
        "event_stream_merkle_root": "a" * 64,
        "trade_ledger_merkle_root": "b" * 64,
        "tamper_digest": "c" * 64,
        "events": [],
        "trades": [],
    }
    dossier_file.write_text(json.dumps(dummy_dossier), encoding="utf-8")

    try:
        args_inspect = DummyArgs(id_or_path=test_run_id)
        exit_code_inspect = cmd_inspect_run(args_inspect)  # type: ignore[arg-type]
        captured_inspect = capsys.readouterr()

        assert exit_code_inspect == 0
        assert test_run_id in captured_inspect.out
        assert "MOCK_REHEARSAL" in captured_inspect.out
        assert "AIR_GAPPED_PAPER_BROKER" in captured_inspect.out
        assert "RECONCILED" in captured_inspect.out
    finally:
        if dossier_file.exists():
            dossier_file.unlink()


# ==============================================================================
# 6. Database Init & Alembic Migration Idempotence
# ==============================================================================


def test_cmd_init_db_and_alembic_stamp_idempotence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify cmd_init_db stamps Alembic version so alembic upgrade head succeeds idempotently."""
    temp_db = tmp_path / "test_alembic_ledger.db"
    db_url = f"sqlite:///{temp_db}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    args = DummyArgs()
    exit_code = cmd_init_db(args)  # type: ignore[arg-type]
    assert exit_code == 0
    assert temp_db.is_file()

    # Now run alembic upgrade head - it should NOT fail with table already exists
    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # Calling upgrade head must not raise an error
    command.upgrade(alembic_cfg, "head")


# ==============================================================================
# 7. Truthful Mock Forward Options Provenance
# ==============================================================================


def test_mock_forward_options_dossier_truthful_provenance(tmp_path: Path) -> None:
    """Verify mock forward options runner records MOCK_REHEARSAL mode and truthful matrix details."""
    fwd_dir = tmp_path / "fwd"
    raw_dir = tmp_path / "raw"
    config = ForwardOptionsSessionConfig(
        mock_mode=True,
        wait_for_market_open=False,
        duration_seconds=1.0,
        snapshot_interval_seconds=0.5,
        output_dir=fwd_dir,
        raw_capture_dir=raw_dir,
    )

    runner = KotakOptionForwardRunner(config=config)
    dossier_path = runner.run()

    assert Path(dossier_path).exists()
    content = json.loads(Path(dossier_path).read_text(encoding="utf-8"))

    # Verify truthful mode
    assert content["mode"] == "MOCK_REHEARSAL"

    # Verify truthful verification matrix
    matrix = content.get("verification_matrix", {})
    assert "data_integrity" in matrix
    assert "Simulated mock option chain" in matrix["data_integrity"]["details"]
    assert "Kotak Neo WebSocket SFeed" not in matrix["data_integrity"]["details"]
    assert "Mock rehearsal forward shadow session." in matrix["historical_replay"]["details"]


# ==============================================================================
# 8. Fail-Closed Real Execution Guards (No Silent Mock Fallback)
# ==============================================================================


def test_cmd_forward_test_fails_closed_without_credentials_or_mock(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward test command without credentials and without --mock must fail closed."""
    # Ensure no Kotak credentials are active
    monkeypatch.delenv("KOTAK_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("KOTAK_MOBILE_NUMBER", raising=False)
    monkeypatch.delenv("KOTAK_UCC", raising=False)
    monkeypatch.delenv("KOTAK_PASSWORD", raising=False)

    args = DummyArgs(
        strategy="test_ma_crossover",
        instrument="NIFTY",
        timeframe="1m",
        capital=1000000.0,
        slippage_bps=5.0,
        mock=False,
        ticks=5,
        bars=None,
        duration=1.0,
        output=None,
        strict_quality=False,
        csv=None,
    )
    exit_code = cmd_forward_test(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL-CLOSED SAFETY VETO" in captured.out
    assert 'aditrader forward-test --strategy "test_ma_crossover" --mock' in captured.out


def test_cmd_forward_test_succeeds_with_mock(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward test command with explicit --mock runs simulated rehearsal cleanly."""
    monkeypatch.delenv("KOTAK_CONSUMER_KEY", raising=False)
    args = DummyArgs(
        strategy="test_ma_crossover",
        instrument="NIFTY",
        timeframe="1s",
        capital=1000000.0,
        slippage_bps=5.0,
        mock=True,
        ticks=5,
        bars=None,
        duration=2.0,
        output=None,
        strict_quality=False,
        csv=None,
    )
    exit_code = cmd_forward_test(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Forward-Testing Session Summary" in captured.out
    assert "SIMULATED_REHEARSAL" in captured.out


def test_cmd_kotak_auth_fails_closed_without_credentials(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kotak auth command without credentials and without --mock must fail closed."""
    monkeypatch.delenv("KOTAK_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("KOTAK_MOBILE_NUMBER", raising=False)
    monkeypatch.delenv("KOTAK_CONSUMER_SECRET", raising=False)
    monkeypatch.delenv("KOTAK_PASSWORD", raising=False)

    args = DummyArgs(mock=False)
    exit_code = cmd_kotak_auth(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL-CLOSED SAFETY VETO" in captured.out
    assert "aditrader kotak-auth --mock" in captured.out


def test_cmd_smoke_feed_fails_closed_without_credentials(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke feed command without credentials and without --mock must fail closed."""
    monkeypatch.delenv("KOTAK_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("KOTAK_MOBILE_NUMBER", raising=False)
    monkeypatch.delenv("KOTAK_PASSWORD", raising=False)

    args = DummyArgs(symbol="NIFTY", ticks=3, timeout=1.0, mock=False)
    exit_code = cmd_smoke_feed(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL-CLOSED SAFETY VETO" in captured.out
    assert "aditrader smoke-feed --symbol NIFTY --mock" in captured.out


def test_cmd_smoke_feed_rejects_zero_or_negative_ticks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Smoke feed command with 0 or negative ticks fails with clean error."""
    args = DummyArgs(symbol="NIFTY", ticks=0, timeout=1.0, mock=True)
    exit_code = cmd_smoke_feed(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Invalid --ticks 0: tick count must be strictly positive." in captured.out


def test_cmd_kotak_discover_fails_closed_without_credentials(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kotak discover command without credentials and without --mock must fail closed."""
    monkeypatch.delenv("KOTAK_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("KOTAK_CONSUMER_SECRET", raising=False)

    args = DummyArgs(mock=False, output_dir=None)
    exit_code = cmd_kotak_discover(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL-CLOSED SAFETY VETO" in captured.out
    assert "aditrader kotak-discover --mock" in captured.out


def test_cmd_kotak_history_fails_closed_without_credentials(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kotak history command without credentials and without --mock must fail closed."""
    monkeypatch.delenv("KOTAK_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("KOTAK_CONSUMER_SECRET", raising=False)

    args = DummyArgs(
        symbol="NIFTY",
        symbol_arg=None,
        timeframe="5m",
        from_date=None,
        to_date=None,
        output=None,
        mock=False,
    )
    exit_code = cmd_kotak_history(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL-CLOSED SAFETY VETO" in captured.out
    assert "aditrader kotak-history --symbol NIFTY --mock" in captured.out


# ==============================================================================
# 9. Dataset Discovery and Dashboard Options
# ==============================================================================


def test_cmd_inspect_data_discovers_datasets_when_no_file_passed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inspect data command without arguments discovers and displays available CSVs."""
    args = DummyArgs(file_opt=None, file=None, csv=None, csv_file=None)
    exit_code = cmd_inspect_data(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Please provide a path to a CSV file to inspect." in captured.out
    assert "Discovered datasets in repository:" in captured.out
    assert "aditrader inspect-data --file data/nifty_sample.csv" in captured.out


def test_cmd_dashboard_no_serve_option(capsys: pytest.CaptureFixture[str]) -> None:
    """Dashboard command with serve=False prints instructions without blocking."""
    args = DummyArgs(port=8050, host="127.0.0.1", serve=False)
    exit_code = cmd_dashboard(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "scheduled for Phase 8" in captured.out
    assert "Run 'aditrader dashboard' to start the live server" in captured.out
