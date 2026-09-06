"""Unit tests verifying RingBuffer bounds and TickAggregator candle formation."""

import threading
from datetime import datetime

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.feeds.aggregator import RingBuffer, TickAggregator
from aditrader.data.session import EXCHANGE_TIMEZONE


def test_ring_buffer_capacity_eviction_and_order() -> None:
    """Verify RingBuffer maintains capacity limit and evicts oldest items FIFO."""
    rb: RingBuffer[int] = RingBuffer(capacity=3)
    assert len(rb) == 0

    rb.append(10)
    rb.append(20)
    rb.append(30)
    assert len(rb) == 3
    assert rb.get_all() == [10, 20, 30]
    assert rb.get_latest() == 30

    # 4th item evicts 10
    rb.append(40)
    assert len(rb) == 3
    assert rb.get_all() == [20, 30, 40]
    assert rb.get_latest() == 40

    rb.clear()
    assert len(rb) == 0
    assert rb.get_latest() is None


def test_ring_buffer_thread_safety() -> None:
    """Verify concurrent appends maintain buffer integrity."""
    rb: RingBuffer[int] = RingBuffer(capacity=100)

    def worker(start: int) -> None:
        for i in range(start, start + 50):
            rb.append(i)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(50,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(rb) == 100


def test_tick_aggregator_single_bar_accumulation_and_rollover() -> None:
    """Verify aggregator rolls over ticks into Bar upon interval expiration."""
    closed_bars: list[Bar] = []

    def on_close(b: Bar) -> None:
        closed_bars.append(b)

    agg = TickAggregator(
        symbol="NIFTY",
        interval_seconds=60,  # 1-minute bars
        on_bar_close=on_close,
    )

    t0 = datetime(2024, 12, 2, 9, 15, 5, tzinfo=EXCHANGE_TIMEZONE)
    t1 = datetime(2024, 12, 2, 9, 15, 25, tzinfo=EXCHANGE_TIMEZONE)
    t2 = datetime(2024, 12, 2, 9, 15, 50, tzinfo=EXCHANGE_TIMEZONE)

    # Ingest 3 ticks in minute 9:15
    tick0 = Tick(
        symbol="NIFTY", ltp=24000.0, bid=23999.0, ask=24001.0, volume=100, oi=50000, timestamp=t0
    )
    tick1 = Tick(
        symbol="NIFTY", ltp=24020.0, bid=24019.0, ask=24021.0, volume=150, oi=50000, timestamp=t1
    )
    tick2 = Tick(
        symbol="NIFTY", ltp=23990.0, bid=23989.0, ask=23991.0, volume=180, oi=50000, timestamp=t2
    )

    assert agg.process_tick(tick0) is None
    assert agg.process_tick(tick1) is None
    assert agg.process_tick(tick2) is None
    assert len(closed_bars) == 0

    # Ingest tick in minute 9:16 -> should trigger closure of 9:15 bar
    t3 = datetime(2024, 12, 2, 9, 16, 2, tzinfo=EXCHANGE_TIMEZONE)
    tick3 = Tick(
        symbol="NIFTY", ltp=24005.0, bid=24004.0, ask=24006.0, volume=220, oi=50200, timestamp=t3
    )

    closed = agg.process_tick(tick3)
    assert closed is not None
    assert len(closed_bars) == 1
    assert closed_bars[0] == closed

    # Check closed 9:15 bar OHLC envelope
    assert closed.timestamp == datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    assert closed.open == 24000.0
    assert closed.high == 24020.0
    assert closed.low == 23990.0
    assert closed.close == 23990.0
    assert closed.volume == 3  # 3 ticks accumulated
    assert closed.oi == 50000


def test_tick_aggregator_flush() -> None:
    """Verify flush forces the closure of the active in-progress candle."""
    agg = TickAggregator(symbol="NIFTY", interval_seconds=60)
    t0 = datetime(2024, 12, 2, 9, 15, 10, tzinfo=EXCHANGE_TIMEZONE)
    tick0 = Tick(
        symbol="NIFTY", ltp=24000.0, bid=23999.0, ask=24001.0, volume=100, oi=50000, timestamp=t0
    )

    agg.process_tick(tick0)
    assert len(agg.bar_buffer) == 0

    flushed = agg.flush()
    assert flushed is not None
    assert flushed.open == 24000.0
    assert flushed.close == 24000.0
    assert len(agg.bar_buffer) == 1
