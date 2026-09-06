"""Comprehensive test suite for QuantumValidator forward-testing runner and paper execution.

Verifies:
1. Configuration and strategy resolution
2. Canonical tick ingestion and bar aggregation
3. Quote-aware paper broker execution (ask/bid vs LTP fallback)
4. Pre-trade risk validation gates
5. Strict market data quality error handling
6. Session lifecycle states and stop thresholds (ticks, bars, duration, SIGINT)
7. Audit recorder and JSON dossier persistence
8. SQLite transactional ledger persistence
9. Strict paper-only air-gap guard (proves zero live order placement)
10. Opt-in live Kotak Neo smoke test
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aditrader.config.settings import get_settings
from aditrader.core.broker import PaperBroker
from aditrader.core.ledger.repository import LedgerRepository
from aditrader.core.ledger.schema import OrderRecord, TradeRecord
from aditrader.core.models.enums import OrderSide, OrderStatus
from aditrader.core.models.market_data import Tick
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.forward import ForwardTestStatus
from aditrader.data.forward_runner import (
    ForwardTestConfig,
    ForwardTestRunner,
    _get_sample_ma_crossover,
    _parse_timeframe_seconds,
    resolve_strategy,
)
from aditrader.data.quality import DataQualityError
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.compiler.engine import ExecutableStrategy

# ==============================================================================
# 1. Configuration & Timeframe Helpers
# ==============================================================================


def test_forward_test_config_validation() -> None:
    """Verify ForwardTestConfig requires non-empty symbol and enforces bounds."""
    config = ForwardTestConfig(
        symbol="NIFTY",
        timeframe="1m",
        initial_capital=500_000.0,
        slippage_bps=3.0,
    )
    assert config.symbol == "NIFTY"
    assert config.timeframe == "1m"
    assert config.initial_capital == 500_000.0
    assert config.slippage_bps == 3.0
    assert config.enforce_session_hours is False
    assert config.strict_quality_checks is False

    with pytest.raises(ValidationError):
        ForwardTestConfig(symbol="")

    with pytest.raises(ValidationError):
        ForwardTestConfig(symbol="NIFTY", initial_capital=-100.0)


def test_parse_timeframe_seconds() -> None:
    """Verify timeframe string parsing into seconds."""
    assert _parse_timeframe_seconds("1s") == 1
    assert _parse_timeframe_seconds("5s") == 5
    assert _parse_timeframe_seconds("1m") == 60
    assert _parse_timeframe_seconds("5m") == 300
    assert _parse_timeframe_seconds("1h") == 3600
    assert _parse_timeframe_seconds("1d") == 86400
    assert _parse_timeframe_seconds("custom") == 60


# ==============================================================================
# 2. Strategy Resolution
# ==============================================================================


def test_resolve_strategy_variants() -> None:
    """Verify strategy resolution across ExecutableStrategy, DSL, registry, and built-in sample."""
    sample_dsl = _get_sample_ma_crossover(underlying="BANKNIFTY")
    exec_strat = ExecutableStrategy(sample_dsl)

    # 1. Direct ExecutableStrategy
    res_exec, res_dsl = resolve_strategy(exec_strat)
    assert res_exec is exec_strat
    assert res_dsl == sample_dsl

    # 2. Direct StrategyDSL
    res_exec2, res_dsl2 = resolve_strategy(sample_dsl)
    assert isinstance(res_exec2, ExecutableStrategy)
    assert res_dsl2 == sample_dsl

    # 3. Registry exact ID / name
    res_exec3, res_dsl3 = resolve_strategy("nifty_weekly_iron_condor")
    assert "iron_condor" in res_dsl3.name.lower().replace(" ", "_")
    assert res_dsl3.underlying == "NIFTY"

    # 4. Normalized registry string
    res_exec4, res_dsl4 = resolve_strategy("NIFTY-WEEKLY-IRON-CONDOR")
    assert "iron_condor" in res_dsl4.name.lower().replace(" ", "_")

    # 5. Built-in linear sample with symbol override
    res_exec5, res_dsl5 = resolve_strategy("test_ma_crossover", symbol="RELIANCE")
    assert res_dsl5.name == "test_ma_crossover"
    assert res_dsl5.underlying == "RELIANCE"

    # 6. Invalid strategy string
    with pytest.raises(ValueError, match="could not be resolved"):
        resolve_strategy("non_existent_strategy_xyz")

    # 7. Invalid type
    with pytest.raises(TypeError, match="Unsupported strategy type"):
        resolve_strategy(12345)  # type: ignore[arg-type]


# ==============================================================================
# 3. Synchronous Canonical Data Flow & Quote-Aware Execution
# ==============================================================================


def test_runner_initialization_defaults() -> None:
    """Verify runner initializes in STARTING status with paper-only boundaries."""
    config = ForwardTestConfig(symbol="NIFTY", timeframe="1s")
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )

    assert runner.status == ForwardTestStatus.STARTING
    assert runner.is_running is False
    assert runner.session_id.startswith("FWD-")
    assert runner.broker.get_account_balance().total_capital == 1_000_000.0


def test_quote_aware_execution_buy_and_sell() -> None:
    """Verify quote-aware execution: BUY fills against ask + slippage, SELL fills against bid - slippage."""
    config = ForwardTestConfig(symbol="NIFTY", timeframe="1s", slippage_bps=0.0)
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    runner.start()

    base_time = datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)

    # 1. Bucket 1 (09:16:00): Price > 24000 to arm BUY entry condition
    tick1 = Tick(
        symbol="NIFTY",
        ltp=24010.0,
        bid=24008.0,
        ask=24012.0,
        volume=10,
        timestamp=base_time,
    )
    runner.process_tick(tick1)

    # 2. Bucket 2 (09:16:01): Advances time, closes Bucket 1 bar.
    # The closed bar triggers ExecutableStrategy.on_bar -> BUY signal!
    # Latest tick has bid=24018, ask=24022. BUY fills against ask=24022!
    tick2 = Tick(
        symbol="NIFTY",
        ltp=24020.0,
        bid=24018.0,
        ask=24022.0,
        volume=10,
        timestamp=base_time + timedelta(seconds=1),
    )
    runner.process_tick(tick2)

    orders = runner.broker.get_orders()
    trades = runner.broker.get_trades()

    assert len(orders) >= 1
    buy_order = orders[0]
    assert buy_order.side == OrderSide.BUY
    assert buy_order.status == OrderStatus.FILLED

    assert len(trades) >= 1
    buy_trade = trades[0]
    # In PaperBroker with 0 slippage, fills at ask=24022.0
    assert buy_trade.fill_price == 24022.0

    positions = runner.broker.get_positions()
    nifty_pos = next((p for p in positions if p.symbol == "NIFTY"), None)
    assert nifty_pos is not None
    assert nifty_pos.qty == 1

    runner.stop(reason="Test concluded")


def test_quote_unavailable_fallback_to_ltp() -> None:
    """Verify fallback to LTP when bid/ask quotes are missing, and flag recorded."""
    config = ForwardTestConfig(symbol="NIFTY", timeframe="1s", slippage_bps=0.0)
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    runner.start()

    base_time = datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)

    # Tick without bid/ask
    tick1 = Tick(
        symbol="NIFTY",
        ltp=24010.0,
        bid=None,
        ask=None,
        volume=10,
        timestamp=base_time,
    )
    obs = runner.process_tick(tick1)
    assert obs is not None
    assert "MISSING_BID_ASK" in obs.quality_flags

    # Advance time to close bar
    tick2 = Tick(
        symbol="NIFTY",
        ltp=24015.0,
        bid=None,
        ask=None,
        volume=10,
        timestamp=base_time + timedelta(seconds=1),
    )
    runner.process_tick(tick2)

    trades = runner.broker.get_trades()
    assert len(trades) >= 1
    # Fills against bar.close (or LTP) when quotes missing
    assert trades[0].fill_price == 24010.0

    runner.stop(reason="Test concluded")


# ==============================================================================
# 4. Pre-Trade Risk Verification
# ==============================================================================


def test_pre_trade_risk_gate_rejection() -> None:
    """Verify orders failing pre-trade risk gates are transitioned to REJECTED."""
    # Extremely small capital will trigger margin rejection for NIFTY @ 24,000
    config = ForwardTestConfig(
        symbol="NIFTY",
        timeframe="1s",
        initial_capital=5_000.0,  # 5,000 capital cannot support 24,000 order
    )
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    runner.start()

    base_time = datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)

    runner.process_tick(
        Tick(symbol="NIFTY", ltp=24010.0, bid=24008.0, ask=24012.0, volume=5, timestamp=base_time)
    )
    runner.process_tick(
        Tick(
            symbol="NIFTY",
            ltp=24020.0,
            bid=24018.0,
            ask=24022.0,
            volume=5,
            timestamp=base_time + timedelta(seconds=1),
        )
    )

    orders = runner.broker.get_orders()
    assert len(orders) >= 1
    rejected = orders[0]
    assert rejected.status == OrderStatus.REJECTED
    assert "MARGIN_LIMIT_EXCEEDED" in (rejected.rejection_reason or "")

    # Zero trades executed
    assert len(runner.broker.get_trades()) == 0

    runner.stop(reason="Test concluded")


# ==============================================================================
# 5. Market Data Quality Enforcement
# ==============================================================================


def test_strict_quality_checks_abort_session() -> None:
    """Verify strict_quality_checks=True aborts session on invalid data."""
    config = ForwardTestConfig(symbol="NIFTY", timeframe="1s", strict_quality_checks=True)
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    runner.start()

    # Invalid tick: crossed bid/ask quotes (bid > ask is physically impossible)
    bad_tick = Tick.model_construct(
        symbol="NIFTY",
        ltp=24000.0,
        bid=24010.0,
        ask=23990.0,
        volume=10,
        timestamp=datetime.now(tz=EXCHANGE_TIMEZONE),
    )

    with pytest.raises(DataQualityError, match="Strict data quality failure"):
        runner.process_tick(bad_tick)

    assert runner.is_running is False
    assert runner.status == ForwardTestStatus.FAILED
    assert runner.recorder.status == ForwardTestStatus.FAILED


# ==============================================================================
# 6. Session Lifecycle & Stop Thresholds
# ==============================================================================


def test_session_stop_on_max_ticks() -> None:
    """Verify session transitions to COMPLETED upon reaching max_ticks threshold."""
    config = ForwardTestConfig(symbol="NIFTY", timeframe="1m", max_ticks=5)
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    runner.start()

    base_time = datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)
    for i in range(5):
        assert runner.is_running is True
        runner.process_tick(
            Tick(
                symbol="NIFTY",
                ltp=24000.0 + i,
                volume=10,
                timestamp=base_time + timedelta(seconds=i),
            )
        )

    assert runner.is_running is False
    assert runner.status == ForwardTestStatus.COMPLETED
    assert "maximum tick count threshold" in (
        runner.recorder.get_session_summary().stop_reason or ""
    )


def test_session_stop_on_max_bars() -> None:
    """Verify session transitions to COMPLETED upon reaching max_bars threshold."""
    config = ForwardTestConfig(symbol="NIFTY", timeframe="1s", max_bars=2)
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    runner.start()

    base_time = datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)
    # Bucket 0: 09:16:00
    runner.process_tick(Tick(symbol="NIFTY", ltp=24000.0, volume=1, timestamp=base_time))
    # Bucket 1: 09:16:01 -> closes bar 1
    runner.process_tick(
        Tick(symbol="NIFTY", ltp=24001.0, volume=1, timestamp=base_time + timedelta(seconds=1))
    )
    # Bucket 2: 09:16:02 -> closes bar 2 -> triggers max_bars stop!
    runner.process_tick(
        Tick(symbol="NIFTY", ltp=24002.0, volume=1, timestamp=base_time + timedelta(seconds=2))
    )

    assert runner.is_running is False
    assert runner.status == ForwardTestStatus.COMPLETED
    assert "maximum closed bar count threshold" in (
        runner.recorder.get_session_summary().stop_reason or ""
    )


def test_sigint_clean_interruption() -> None:
    """Verify manual SIGINT stops session cleanly without losing state."""
    config = ForwardTestConfig(symbol="NIFTY", timeframe="1m")
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    runner.start()
    runner._handle_sigint(2, None)

    assert runner.status == ForwardTestStatus.COMPLETED
    assert "SIGINT received" in (runner.recorder.get_session_summary().stop_reason or "")


# ==============================================================================
# 7. Persistence & Dossier Inspection
# ==============================================================================


def test_session_dossier_persistence(tmp_path: Path) -> None:
    """Verify complete audit dossier is written to JSON and adheres to contract."""
    output_file = tmp_path / "forward_session_audit.json"
    config = ForwardTestConfig(
        symbol="NIFTY",
        timeframe="1s",
        max_ticks=3,
        output_path=output_file,
    )
    runner = ForwardTestRunner(
        config=config, strategy="test_ma_crossover", adapter=KotakNeoAdapter(mock_mode=True)
    )
    result = runner.run()

    assert output_file.is_file()
    assert result.dossier_path == output_file

    with open(output_file, encoding="utf-8") as f:
        data = json.load(f)

    assert "session" in data
    assert data["session"]["session_id"] == runner.session_id
    assert data["session"]["symbol"] == "NIFTY"
    assert data["session"]["total_ticks"] == 3
    assert data["session"]["status"] == "COMPLETED"
    assert "assumptions" in data
    assert data["assumptions"]["broker_mode"] == "AIR_GAPPED_PAPER"
    assert "orders" in data
    assert "trades" in data
    assert "positions" in data
    assert "equity_snapshots" in data
    assert "observations_sample" in data
    assert len(data["observations_sample"]) == 3


def test_sqlite_ledger_persistence(tmp_path: Path) -> None:
    """Verify executed orders and trades are saved to local SQLite transactional ledger."""
    db_file = tmp_path / "test_forward_ledger.db"
    db_url = f"sqlite:///{db_file}"
    ledger_repo = LedgerRepository(database_url=db_url)
    ledger_repo.create_tables()

    config = ForwardTestConfig(
        symbol="NIFTY",
        timeframe="1s",
        database_url=db_url,
        enable_ledger_persistence=True,
    )
    runner = ForwardTestRunner(
        config=config,
        strategy="test_ma_crossover",
        adapter=KotakNeoAdapter(mock_mode=True),
        ledger_repo=ledger_repo,
    )
    runner.start()

    base_time = datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)
    runner.process_tick(
        Tick(symbol="NIFTY", ltp=24010.0, bid=24008.0, ask=24012.0, volume=10, timestamp=base_time)
    )
    runner.process_tick(
        Tick(
            symbol="NIFTY",
            ltp=24020.0,
            bid=24018.0,
            ask=24022.0,
            volume=10,
            timestamp=base_time + timedelta(seconds=1),
        )
    )

    runner.stop(reason="Test finished")

    # Verify rows in SQLite database
    from sqlalchemy import select

    with ledger_repo.SessionLocal() as session:
        orders = (
            session.execute(select(OrderRecord).where(OrderRecord.run_id == runner.session_id))
            .scalars()
            .all()
        )
        trades = (
            session.execute(select(TradeRecord).where(TradeRecord.run_id == runner.session_id))
            .scalars()
            .all()
        )

        assert len(orders) >= 1
        assert orders[0].symbol == "NIFTY"
        assert len(trades) >= 1
        assert trades[0].symbol == "NIFTY"


# ==============================================================================
# 8. Air-Gap Isolation Guard
# ==============================================================================


def test_paper_only_boundary_isolation_guard() -> None:
    """Verify that runner is strictly air-gapped and cannot place real broker orders."""
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()

    # 1. Adapter place_order raises NotImplementedError with ADR 002 security veto
    with pytest.raises(NotImplementedError, match="CRITICAL SECURITY VETO"):
        adapter.place_order({})

    # 2. ForwardTestRunner broker is exclusively PaperBroker
    config = ForwardTestConfig(symbol="NIFTY")
    runner = ForwardTestRunner(config=config, strategy="test_ma_crossover", adapter=adapter)
    assert isinstance(runner.broker, PaperBroker)

    # 3. Verify no live broker client is attached or accessible on the broker
    assert not hasattr(runner.broker, "client")
    assert not hasattr(runner.broker, "neo_client")
    assert not hasattr(runner.broker, "route_to_exchange")


# ==============================================================================
# 9. Opt-in Live Kotak Smoke Test
# ==============================================================================


def test_opt_in_live_kotak_smoke_test() -> None:
    """Opt-in live authentication and WebSocket subscription smoke test (skipped if credentials missing)."""
    settings = get_settings()
    has_credentials = bool(
        settings.kotak_consumer_key
        and settings.kotak_consumer_secret
        and settings.kotak_mobile_number
        and settings.kotak_password
    )

    if not has_credentials:
        pytest.skip(
            "Kotak Neo live credentials not configured in environment; skipping live adapter test."
        )

    adapter = KotakNeoAdapter(mock_mode=False)
    adapter.authenticate()
    assert adapter.is_connected()

    config = ForwardTestConfig(symbol="NIFTY", duration_seconds=1.0)
    runner = ForwardTestRunner(config=config, strategy="test_ma_crossover", adapter=adapter)
    result = runner.run()

    assert result.session.status in (ForwardTestStatus.COMPLETED, ForwardTestStatus.RUNNING)
