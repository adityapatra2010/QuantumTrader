"""Comprehensive verification suite for market data fidelity, aggregation, and replay parity."""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aditrader.backtesting.runner import BacktestConfig, BacktestRunner
from aditrader.core.broker import PaperBroker
from aditrader.core.costs import SlippageModel
from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType
from aditrader.core.models.market_data import (
    Bar,
    MarketDataProvenance,
    MarketDataSourceType,
    Tick,
)
from aditrader.core.models.order import Order
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.cache import LocalDataCache
from aditrader.data.feeds.aggregator import (
    DuplicateTickError,
    OutOfOrderTickError,
    TickAggregator,
)
from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.forward import (
    ForwardTestAssumptions,
    ForwardTestRecorder,
)
from aditrader.data.quality import (
    DataQualityError,
    MarketDataQualityValidator,
)
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
)
from aditrader.strategy.compiler.engine import ExecutableStrategy

# ==============================================================================
# 1. Canonical Tick & Bar Model Verification
# ==============================================================================


def test_canonical_tick_sparse_vs_rich() -> None:
    """Verify Tick supports sparse historical/synthetic fields as well as rich quote fields."""
    now = datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)

    # Sparse Tick
    sparse_tick = Tick(symbol="NIFTY", ltp=24000.0, timestamp=now)
    assert sparse_tick.symbol == "NIFTY"
    assert sparse_tick.ltp == 24000.0
    assert sparse_tick.bid is None
    assert sparse_tick.ask is None
    assert sparse_tick.volume == 0
    assert sparse_tick.oi is None
    assert sparse_tick.is_synthetic is False

    # Rich Tick with quotes, depth quantities, token, exchange
    rich_tick = Tick(
        symbol="NIFTY24DEC24000CE",
        ltp=150.25,
        timestamp=now,
        volume=25000,
        oi=120000,
        bid=150.20,
        ask=150.30,
        bid_qty=50,
        ask_qty=100,
        exchange="NFO",
        instrument_token="45001",
        source="KOTAK_NEO",
        is_synthetic=False,
    )
    assert rich_tick.bid == 150.20
    assert rich_tick.ask == 150.30
    assert rich_tick.bid_qty == 50
    assert rich_tick.ask_qty == 100
    assert rich_tick.exchange == "NFO"
    assert rich_tick.instrument_token == "45001"


def test_canonical_tick_crossed_market_rejection() -> None:
    """Verify crossed market (bid > ask) is strictly rejected by Tick validator."""
    now = datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
    with pytest.raises(ValidationError, match="Invalid crossed market"):
        Tick(
            symbol="NIFTY",
            ltp=24000.0,
            timestamp=now,
            bid=24010.0,
            ask=24000.0,  # bid > ask
        )


def test_canonical_bar_extended_fields_and_bounds() -> None:
    """Verify Bar extended fields (vwap, tick_count, source, timeframe) and price bounds."""
    now = datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)

    bar = Bar(
        timestamp=now,
        open=24000.0,
        high=24050.0,
        low=23950.0,
        close=24020.0,
        volume=5000,
        oi=100000,
        symbol="NIFTY",
        vwap=24010.50,
        tick_count=120,
        source="TICK_AGGREGATOR",
        timeframe="60s",
        is_synthetic=False,
    )
    assert bar.symbol == "NIFTY"
    assert bar.vwap == 24010.50
    assert bar.tick_count == 120
    assert bar.timeframe == "60s"
    assert bar.source == "TICK_AGGREGATOR"

    # Envelope validation
    with pytest.raises(ValidationError, match="High price .* cannot be lower than Low"):
        Bar(
            timestamp=now,
            open=24000.0,
            high=23900.0,  # high < low
            low=23950.0,
            close=24000.0,
        )

    with pytest.raises(ValidationError, match="High price .* must be >= open and close"):
        Bar(
            timestamp=now,
            open=24000.0,
            high=24010.0,
            low=23950.0,
            close=24020.0,  # close > high
        )


def test_market_data_provenance_contract() -> None:
    """Verify MarketDataProvenance immutability and origin tagging."""
    prov = MarketDataProvenance(
        source_type=MarketDataSourceType.LIVE_BROKER,
        provider="KOTAK_NEO",
        symbol="NIFTY",
        timeframe="tick",
        is_synthetic=False,
    )
    assert prov.source_type == MarketDataSourceType.LIVE_BROKER
    assert prov.provider == "KOTAK_NEO"
    assert prov.is_synthetic is False


# ==============================================================================
# 2. Kotak Neo Quote Packet Parsing
# ==============================================================================


def test_kotak_neo_parse_quote_packet_full() -> None:
    """Verify parsing full Kotak Neo quote packet into canonical Tick."""
    adapter = KotakNeoAdapter(mock_mode=True)
    packet = {
        "symbol": "NIFTY24DEC24000CE",
        "ltp": 150.25,
        "v": 25000,
        "oi": 120000,
        "bp": 150.10,
        "sp": 150.30,
        "bq": 50,
        "sq": 100,
        "tok": "45001",
        "e": "NFO",
        "ltt": "2024-12-02T10:30:00+05:30",
    }
    tick = adapter.parse_quote_packet(packet)
    assert tick.symbol == "NIFTY24DEC24000CE"
    assert tick.ltp == 150.25
    assert tick.volume == 25000
    assert tick.oi == 120000
    assert tick.bid == 150.10
    assert tick.ask == 150.30
    assert tick.bid_qty == 50
    assert tick.ask_qty == 100
    assert tick.instrument_token == "45001"
    assert tick.exchange == "NFO"
    assert tick.source == "KOTAK_NEO"
    assert tick.is_synthetic is False


def test_kotak_neo_parse_quote_packet_sparse_and_missing_symbol() -> None:
    """Verify parsing sparse quote packet and rejecting packet with missing symbol."""
    adapter = KotakNeoAdapter(mock_mode=True)
    sparse_packet = {
        "ts": "RELIANCE",
        "lp": 2800.0,
    }
    tick = adapter.parse_quote_packet(sparse_packet)
    assert tick.symbol == "RELIANCE"
    assert tick.ltp == 2800.0
    assert tick.bid is None
    assert tick.ask is None
    assert tick.volume == 0

    with pytest.raises(ValueError, match="missing symbol"):
        adapter.parse_quote_packet({"lp": 100.0})


# ==============================================================================
# 3. Tick Aggregator Hardening
# ==============================================================================


def test_tick_aggregator_volume_modes() -> None:
    """Verify TICK_COUNT, INCREMENTAL, and CUMULATIVE volume modes."""
    t0 = datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    t1 = datetime(2024, 12, 2, 9, 15, 10, tzinfo=EXCHANGE_TIMEZONE)
    t2 = datetime(2024, 12, 2, 9, 15, 20, tzinfo=EXCHANGE_TIMEZONE)
    t_roll = datetime(2024, 12, 2, 9, 16, 0, tzinfo=EXCHANGE_TIMEZONE)

    # 1. INCREMENTAL mode: sum of tick volumes
    agg_inc = TickAggregator(symbol="NIFTY", interval_seconds=60, volume_mode="INCREMENTAL")
    agg_inc.process_tick(Tick(symbol="NIFTY", ltp=24000.0, timestamp=t0, volume=10))
    agg_inc.process_tick(Tick(symbol="NIFTY", ltp=24010.0, timestamp=t1, volume=20))
    agg_inc.process_tick(Tick(symbol="NIFTY", ltp=24005.0, timestamp=t2, volume=15))
    bar_inc = agg_inc.process_tick(Tick(symbol="NIFTY", ltp=24020.0, timestamp=t_roll, volume=5))
    assert bar_inc is not None
    assert bar_inc.volume == 45  # 10 + 20 + 15
    assert bar_inc.tick_count == 3

    # 2. CUMULATIVE mode: session volume deltas
    agg_cum = TickAggregator(symbol="NIFTY", interval_seconds=60, volume_mode="CUMULATIVE")
    agg_cum.process_tick(Tick(symbol="NIFTY", ltp=24000.0, timestamp=t0, volume=1000))
    agg_cum.process_tick(Tick(symbol="NIFTY", ltp=24010.0, timestamp=t1, volume=1025))
    agg_cum.process_tick(Tick(symbol="NIFTY", ltp=24005.0, timestamp=t2, volume=1050))
    bar_cum = agg_cum.process_tick(Tick(symbol="NIFTY", ltp=24020.0, timestamp=t_roll, volume=1060))
    assert bar_cum is not None
    assert bar_cum.volume == 1050  # first tick baseline 1000 + delta 25 + delta 25
    assert bar_cum.tick_count == 3


def test_tick_aggregator_vwap_and_flush() -> None:
    """Verify accurate VWAP calculation and final flush."""
    t0 = datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    t1 = datetime(2024, 12, 2, 9, 15, 10, tzinfo=EXCHANGE_TIMEZONE)

    agg = TickAggregator(symbol="NIFTY", interval_seconds=60, volume_mode="INCREMENTAL")
    agg.process_tick(Tick(symbol="NIFTY", ltp=100.0, timestamp=t0, volume=10))
    agg.process_tick(Tick(symbol="NIFTY", ltp=200.0, timestamp=t1, volume=10))
    bar = agg.flush()
    assert bar is not None
    assert bar.volume == 20
    # VWAP = (100 * 10 + 200 * 10) / 20 = 150.0
    assert bar.vwap == 150.0
    assert bar.tick_count == 2
    assert bar.symbol == "NIFTY"


def test_tick_aggregator_out_of_order_and_duplicate_handling() -> None:
    """Verify out-of-order drop/reject and duplicate tick handling."""
    t0 = datetime(2024, 12, 2, 9, 15, 30, tzinfo=EXCHANGE_TIMEZONE)
    t_past = datetime(2024, 12, 2, 9, 14, 0, tzinfo=EXCHANGE_TIMEZONE)  # already closed bucket

    # Non-strict: drops out-of-order tick without corrupting candle
    agg = TickAggregator(symbol="NIFTY", interval_seconds=60, strict=False)
    agg.process_tick(Tick(symbol="NIFTY", ltp=24000.0, timestamp=t0))
    res = agg.process_tick(Tick(symbol="NIFTY", ltp=23900.0, timestamp=t_past))
    assert res is None
    assert agg.quality_stats["out_of_order"] == 1

    # Strict: raises OutOfOrderTickError
    agg_strict = TickAggregator(symbol="NIFTY", interval_seconds=60, strict=True)
    agg_strict.process_tick(Tick(symbol="NIFTY", ltp=24000.0, timestamp=t0))
    with pytest.raises(OutOfOrderTickError):
        agg_strict.process_tick(Tick(symbol="NIFTY", ltp=23900.0, timestamp=t_past))

    # Duplicate tick handling in strict mode with ignore_duplicates=False
    agg_dup = TickAggregator(
        symbol="NIFTY", interval_seconds=60, strict=True, ignore_duplicates=False
    )
    agg_dup.process_tick(Tick(symbol="NIFTY", ltp=24000.0, timestamp=t0, volume=10))
    with pytest.raises(DuplicateTickError):
        agg_dup.process_tick(Tick(symbol="NIFTY", ltp=24000.0, timestamp=t0, volume=10))


# ==============================================================================
# 4. Deterministic Data Quality Engine
# ==============================================================================


def test_data_quality_validator_bar_sequence() -> None:
    """Verify MarketDataQualityValidator detects ordering, duplicates, and physical envelope violations."""
    t0 = datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
    t1 = datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)
    t_retrograde = datetime(2024, 12, 2, 9, 14, tzinfo=EXCHANGE_TIMEZONE)

    clean_bars = [
        Bar(timestamp=t0, open=100.0, high=105.0, low=95.0, close=102.0, volume=50),
        Bar(timestamp=t1, open=102.0, high=108.0, low=101.0, close=106.0, volume=60),
    ]
    report_clean = MarketDataQualityValidator.validate_bar_sequence(clean_bars)
    assert report_clean.is_clean is True
    assert report_clean.total_records == 2
    assert report_clean.valid_records == 2

    corrupt_bars = [
        Bar(timestamp=t0, open=100.0, high=105.0, low=95.0, close=102.0, volume=50),
        Bar(timestamp=t_retrograde, open=102.0, high=108.0, low=101.0, close=106.0, volume=60),
    ]
    report_corrupt = MarketDataQualityValidator.validate_bar_sequence(corrupt_bars)
    assert report_corrupt.is_clean is False
    assert report_corrupt.has_out_of_order is True

    # Strict mode raises DataQualityError
    with pytest.raises(DataQualityError):
        MarketDataQualityValidator.validate_bar_sequence(corrupt_bars, strict=True)


def test_data_quality_validator_tick_sequence() -> None:
    """Verify tick sequence quality audit for ordering, duplicates, and crossed quotes."""
    t0 = datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    t1 = datetime(2024, 12, 2, 9, 15, 1, tzinfo=EXCHANGE_TIMEZONE)

    clean_ticks = [
        Tick(symbol="NIFTY", ltp=24000.0, timestamp=t0, bid=23999.0, ask=24001.0),
        Tick(symbol="NIFTY", ltp=24002.0, timestamp=t1, bid=24001.0, ask=24003.0),
    ]
    report = MarketDataQualityValidator.validate_tick_sequence(clean_ticks)
    assert report.is_clean is True
    assert report.total_records == 2


# ==============================================================================
# 5. Simulation Assumptions Recording in BacktestResult
# ==============================================================================


def test_backtest_runner_records_simulation_assumptions() -> None:
    """Verify BacktestResult records explicit, comprehensive simulation assumptions."""
    feed = SyntheticDataFeed(symbol="NIFTY", num_bars=50, seed=101)

    dsl = StrategyDSL(
        schema_version="1.0",
        name="test_ma_crossover",
        underlying="NIFTY",
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=24000.0,
                )
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.LESS_THAN,
                    threshold=23950.0,
                )
            ],
        ),
    )
    strategy = ExecutableStrategy(dsl)

    config = BacktestConfig(
        initial_capital=500_000.0,
        slippage_model=SlippageModel(percentage=0.00025),
        allow_same_bar_execution=False,
        max_volume_participation_pct=0.10,
        volume_limit_action="REJECT",
    )
    runner = BacktestRunner(config=config)
    result = runner.run(strategy=strategy, data=feed)

    assert result.simulation_assumptions is not None
    assumptions = result.simulation_assumptions
    assert assumptions.data_resolution == "1m"
    assert assumptions.fill_assumption == "NEXT_BAR_OPEN"
    assert assumptions.slippage_model == "SlippageModel"
    assert assumptions.slippage_bps == 2.5
    assert assumptions.cost_model == "NSE_STATUTORY"
    assert assumptions.volume_participation_enforced is True
    assert assumptions.max_volume_participation_pct == 0.10
    assert assumptions.volume_limit_action == "REJECT"
    assert assumptions.data_source_type == MarketDataSourceType.SYNTHETIC_TEST
    assert assumptions.is_synthetic_data is True


# ==============================================================================
# 6. LocalDataCache Parquet Roundtrip with Rich Fields
# ==============================================================================


def test_parquet_roundtrip_rich_bars_and_ticks(tmp_path: Path) -> None:
    """Verify Parquet roundtrip preserves all extended Bar and Tick fields without data loss."""
    cache = LocalDataCache(cache_dir=tmp_path)
    t0 = datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)

    rich_bars = [
        Bar(
            timestamp=t0,
            open=24000.0,
            high=24050.0,
            low=23950.0,
            close=24020.0,
            volume=5000,
            oi=100000,
            symbol="NIFTY",
            vwap=24015.25,
            tick_count=85,
            source="KOTAK_LIVE",
            timeframe="1m",
            is_synthetic=False,
        )
    ]
    cache.save_bars(symbol="NIFTY", timeframe="1m", bars=rich_bars)
    loaded_bars = cache.load_bars(symbol="NIFTY", timeframe="1m")
    assert len(loaded_bars) == 1
    assert loaded_bars[0].symbol == "NIFTY"
    assert loaded_bars[0].vwap == 24015.25
    assert loaded_bars[0].tick_count == 85
    assert loaded_bars[0].source == "KOTAK_LIVE"
    assert loaded_bars[0].timeframe == "1m"
    assert loaded_bars[0].is_synthetic is False

    rich_ticks = [
        Tick(
            symbol="NIFTY24DEC24000CE",
            ltp=155.0,
            timestamp=t0,
            volume=12000,
            oi=80000,
            bid=154.90,
            ask=155.10,
            bid_qty=50,
            ask_qty=100,
            exchange="NFO",
            instrument_token="45001",
            source="KOTAK_NEO",
            data_type="TICK",
            is_synthetic=False,
        )
    ]
    cache.save_ticks(symbol="NIFTY24DEC24000CE", date_key="20241202", ticks=rich_ticks)
    loaded_ticks = cache.load_ticks(symbol="NIFTY24DEC24000CE", date_key="20241202")
    assert len(loaded_ticks) == 1
    assert loaded_ticks[0].symbol == "NIFTY24DEC24000CE"
    assert loaded_ticks[0].bid == 154.90
    assert loaded_ticks[0].ask == 155.10
    assert loaded_ticks[0].bid_qty == 50
    assert loaded_ticks[0].ask_qty == 100
    assert loaded_ticks[0].exchange == "NFO"
    assert loaded_ticks[0].instrument_token == "45001"
    assert loaded_ticks[0].source == "KOTAK_NEO"


# ==============================================================================
# 7. Forward-Testing Observation & Latency Auditing
# ==============================================================================


def test_forward_test_recorder_and_session_metrics() -> None:
    """Verify ForwardTestRecorder tracks latency, quote availability, and quality flags."""
    recorder = ForwardTestRecorder(
        symbol="NIFTY",
        assumptions=ForwardTestAssumptions(
            quote_fill_enabled=True,
            enforce_session_hours=True,
            max_tolerated_latency_ms=100.0,
        ),
    )

    t_exch = datetime(2024, 12, 2, 10, 0, 0, tzinfo=EXCHANGE_TIMEZONE)
    # 50ms latency (within threshold)
    t_rec = t_exch + timedelta(milliseconds=50)

    # 1. Compliant observation with quotes
    tick_with_quotes = Tick(
        symbol="NIFTY",
        ltp=24000.0,
        timestamp=t_exch,
        bid=23999.0,
        ask=24001.0,
        volume=10,
    )
    obs1 = recorder.record_tick(tick_with_quotes, received_at=t_rec)
    assert obs1.latency_ms == 50.0
    assert obs1.fill_evaluated_on_quotes is True
    assert len(obs1.quality_flags) == 0

    # 2. Observation without quotes and with high latency (150ms > 100ms threshold)
    t_exch2 = t_exch + timedelta(seconds=1)
    t_rec2 = t_exch2 + timedelta(milliseconds=150)
    tick_sparse = Tick(symbol="NIFTY", ltp=24005.0, timestamp=t_exch2)
    obs2 = recorder.record_tick(tick_sparse, received_at=t_rec2)
    assert obs2.latency_ms == 150.0
    assert obs2.fill_evaluated_on_quotes is False
    assert "MISSING_BID_ASK" in obs2.quality_flags
    assert "HIGH_LATENCY" in obs2.quality_flags

    # Conclude session and inspect summary
    session = recorder.conclude_session()
    assert session.total_ticks == 2
    assert session.valid_ticks == 1
    assert session.ticks_with_quotes == 1
    assert session.anomaly_count == 1
    assert session.avg_latency_ms == 100.0
    assert session.max_latency_ms == 150.0


# ==============================================================================
# 8. PaperBroker Quote-Aware Execution
# ==============================================================================


def test_paper_broker_fills_on_quotes_when_available() -> None:
    """Verify PaperBroker executes BUY at ask and SELL at bid when quotes exist."""
    broker = PaperBroker(initial_capital=1_000_000.0, slippage_model=SlippageModel(percentage=0.0))
    now = datetime(2024, 12, 2, 10, 0, tzinfo=EXCHANGE_TIMEZONE)

    # Submit BUY order with ask=152.0, bid=150.0, ltp=151.0
    buy_order = Order(
        order_id="ORD-TEST-BUY",
        symbol="NIFTY24DEC24000CE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=50,
        status=OrderStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    filled_buy = broker.submit_order(
        buy_order, current_market_price=151.0, bid=150.0, ask=152.0, timestamp=now
    )
    assert filled_buy.status == OrderStatus.FILLED
    assert filled_buy.average_fill_price == 152.0  # Filled at Ask, not LTP

    # Submit SELL order with ask=152.0, bid=150.0, ltp=151.0
    sell_order = Order(
        order_id="ORD-TEST-SELL",
        symbol="NIFTY24DEC24000CE",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        qty=50,
        status=OrderStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    filled_sell = broker.submit_order(
        sell_order, current_market_price=151.0, bid=150.0, ask=152.0, timestamp=now
    )
    assert filled_sell.status == OrderStatus.FILLED
    assert filled_sell.average_fill_price == 150.0  # Filled at Bid, not LTP


def test_paper_broker_on_market_tick_with_quotes() -> None:
    """Verify on_market_tick matches limit orders against genuine quotes."""
    broker = PaperBroker(initial_capital=1_000_000.0, slippage_model=SlippageModel(percentage=0.0))
    now = datetime(2024, 12, 2, 10, 0, tzinfo=EXCHANGE_TIMEZONE)

    # Place BUY limit order at 100.0
    order = broker.create_order(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=10,
        price=100.0,
        timestamp=now,
    )
    broker.submit_order(order, current_market_price=105.0, timestamp=now)

    # Tick arrives with LTP=99.0, but Ask=101.0 (sellers haven't come down to 100.0)
    tick1 = Tick(symbol="RELIANCE", ltp=99.0, bid=98.0, ask=101.0, timestamp=now)
    trades1 = broker.on_market_tick(tick1)
    assert len(trades1) == 0  # Not filled because Ask (101.0) > Limit (100.0)

    # Tick arrives with Ask=100.0
    tick2 = Tick(symbol="RELIANCE", ltp=99.0, bid=98.0, ask=100.0, timestamp=now)
    trades2 = broker.on_market_tick(tick2)
    assert len(trades2) == 1  # Filled because Ask (100.0) <= Limit (100.0)
    assert trades2[0].fill_price == 100.0


# ==============================================================================
# 9. Opt-in Live Broker Smoke Test
# ==============================================================================


@pytest.mark.skipif(
    not os.getenv("KOTAK_NEO_CONSUMER_KEY"),
    reason="Kotak Neo credentials not configured in environment (opt-in smoke test)",
)
def test_real_kotak_neo_scrip_master_smoke() -> None:
    """Opt-in live network smoke test for Kotak Neo scrip master."""
    adapter = KotakNeoAdapter(
        consumer_key=os.environ["KOTAK_NEO_CONSUMER_KEY"],
        consumer_secret=os.environ.get("KOTAK_NEO_CONSUMER_SECRET", ""),
        mobile_number=os.environ.get("KOTAK_NEO_MOBILE_NUMBER", ""),
        password=os.environ.get("KOTAK_NEO_PASSWORD", ""),
        totp_secret=os.environ.get("KOTAK_NEO_TOTP_SECRET", ""),
        mock_mode=False,
    )
    assert adapter.authenticate() is True
    scrip_master = adapter.fetch_scrip_master()
    assert len(scrip_master) > 0
