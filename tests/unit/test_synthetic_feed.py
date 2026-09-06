"""Unit tests verifying SyntheticDataFeed determinism, price envelope integrity, and tick generation."""

from datetime import datetime

from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.session import EXCHANGE_TIMEZONE


def test_synthetic_feed_determinism() -> None:
    """Verify seeded generation produces identical bar sequences across instances."""
    start = datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
    feed1 = SyntheticDataFeed(symbol="BANKNIFTY", seed=12345, start_time=start, num_bars=50)
    feed2 = SyntheticDataFeed(symbol="BANKNIFTY", seed=12345, start_time=start, num_bars=50)

    bars1 = list(feed1.stream())
    bars2 = list(feed2.stream())

    assert len(bars1) == 50
    assert len(bars2) == 50

    for b1, b2 in zip(bars1, bars2, strict=True):
        assert b1.timestamp == b2.timestamp
        assert b1.open == b2.open
        assert b1.high == b2.high
        assert b1.low == b2.low
        assert b1.close == b2.close
        assert b1.volume == b2.volume


def test_synthetic_feed_price_envelope() -> None:
    """Verify all generated bars adhere to the high/low/open/close envelope."""
    feed = SyntheticDataFeed(symbol="NIFTY", seed=99, num_bars=100)
    for bar in feed.stream():
        assert bar.high >= bar.low
        assert bar.high >= max(bar.open, bar.close)
        assert bar.low <= min(bar.open, bar.close)
        assert bar.volume > 0


def test_synthetic_tick_generation() -> None:
    """Verify intermediate ticks generated for a bar are realistic and bounded."""
    feed = SyntheticDataFeed(symbol="NIFTY", seed=77, num_bars=5)
    bar = list(feed.stream())[0]

    ticks = feed.generate_ticks_for_bar(bar, num_ticks=10)
    assert len(ticks) == 10
    assert ticks[0].symbol == "NIFTY"

    for t in ticks:
        assert bar.low <= t.ltp <= bar.high
        assert t.bid is not None and t.ask is not None
        assert t.bid <= t.ltp <= t.ask
        assert t.volume > 0
