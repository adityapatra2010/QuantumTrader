"""Unit tests verifying DataFeedStreamer unified interface for live and replay feeds."""

from datetime import datetime

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.feeds.streamer import DataFeedStreamer
from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.session import EXCHANGE_TIMEZONE


def test_streamer_historical_replay() -> None:
    """Verify DataFeedStreamer in historical mode dispatches bars to subscribers."""
    start = datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
    feed = SyntheticDataFeed(symbol="NIFTY", start_time=start, num_bars=10, seed=42)

    streamer = DataFeedStreamer(mode="HISTORICAL", feed=feed)
    received_bars: list[Bar] = []

    streamer.add_bar_listener(lambda b: received_bars.append(b))
    streamer.subscribe_symbol("NIFTY")

    yielded_bars = list(streamer.stream_historical())
    assert len(yielded_bars) == 10
    assert len(received_bars) == 10
    assert yielded_bars == received_bars


def test_streamer_live_tick_aggregation() -> None:
    """Verify DataFeedStreamer connects adapter ticks to aggregator and dispatches bars."""
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()

    streamer = DataFeedStreamer(mode="LIVE", adapter=adapter, interval_seconds=60)
    received_ticks: list[Tick] = []
    received_bars: list[Bar] = []

    streamer.add_tick_listener(lambda t: received_ticks.append(t))
    streamer.add_bar_listener(lambda b: received_bars.append(b))
    streamer.subscribe_symbol("NIFTY")

    t1 = datetime(2024, 12, 2, 9, 15, 10, tzinfo=EXCHANGE_TIMEZONE)
    t2 = datetime(2024, 12, 2, 9, 16, 5, tzinfo=EXCHANGE_TIMEZONE)

    tick1 = Tick(
        symbol="NIFTY", ltp=24000.0, bid=23999.0, ask=24001.0, volume=100, oi=50000, timestamp=t1
    )
    tick2 = Tick(
        symbol="NIFTY", ltp=24020.0, bid=24019.0, ask=24021.0, volume=120, oi=50000, timestamp=t2
    )

    adapter.emit_mock_tick(tick1)
    assert len(received_ticks) == 1
    assert len(received_bars) == 0

    # tick2 is in the next minute, which rolls over the 9:15 candle
    adapter.emit_mock_tick(tick2)
    assert len(received_ticks) == 2
    assert len(received_bars) == 1
    assert received_bars[0].open == 24000.0


def test_streamer_session_hours_filtering() -> None:
    """Verify streamer ignores ticks outside NSE hours when session enforcement is active."""
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()

    streamer = DataFeedStreamer(
        mode="LIVE", adapter=adapter, interval_seconds=60, enforce_session_hours=True
    )
    received_ticks: list[Tick] = []
    streamer.add_tick_listener(lambda t: received_ticks.append(t))
    streamer.subscribe_symbol("NIFTY")

    # Off-market tick at 08:30 IST
    t_off = datetime(2024, 12, 2, 8, 30, 0, tzinfo=EXCHANGE_TIMEZONE)
    tick_off = Tick(
        symbol="NIFTY", ltp=24000.0, bid=23999.0, ask=24001.0, volume=100, oi=50000, timestamp=t_off
    )
    adapter.emit_mock_tick(tick_off)
    assert len(received_ticks) == 0

    # On-market tick at 09:15 IST
    t_on = datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    tick_on = Tick(
        symbol="NIFTY", ltp=24000.0, bid=23999.0, ask=24001.0, volume=100, oi=50000, timestamp=t_on
    )
    adapter.emit_mock_tick(tick_on)
    assert len(received_ticks) == 1
