"""Unit tests verifying dataset splitters and anti-overfitting harnesses."""

from datetime import UTC, datetime

import pytest

from aditrader.backtesting.splitters import (
    generate_walk_forward_windows,
    split_out_of_sample,
    split_train_test,
)
from aditrader.core.models.market_data import Bar


def _generate_bars(n: int = 100) -> list[Bar]:
    """Generate chronological bar sequence for splitter tests."""
    bars: list[Bar] = []
    base_ts = datetime(2026, 9, 1, 9, 15, tzinfo=UTC).timestamp()
    for i in range(n):
        ts = datetime.fromtimestamp(base_ts + i * 300, tz=UTC)
        bars.append(
            Bar(
                timestamp=ts,
                open=100.0 + i,
                high=102.0 + i,
                low=99.0 + i,
                close=101.0 + i,
                volume=1000,
                oi=50000,
            )
        )
    return bars


def test_split_train_test_no_overlap() -> None:
    """Verify train/test split has no timestamp overlap and strictly partitioned sizes."""
    bars = _generate_bars(100)
    train, test = split_train_test(bars, train_ratio=0.7)

    assert len(train) == 70
    assert len(test) == 30
    assert len(train) + len(test) == 100

    # Strict point-in-time boundary: last train candle < first test candle
    assert train[-1].timestamp < test[0].timestamp


def test_split_out_of_sample_ratio() -> None:
    """Verify out-of-sample split produces accurate 80/20 in-sample/out-of-sample splits."""
    bars = _generate_bars(50)
    in_sample, out_of_sample = split_out_of_sample(bars, in_sample_ratio=0.8)

    assert len(in_sample) == 40
    assert len(out_of_sample) == 10
    assert in_sample[-1].timestamp < out_of_sample[0].timestamp


def test_split_invalid_ratios_and_short_data() -> None:
    """Verify exceptions on invalid split parameters."""
    bars = _generate_bars(5)

    with pytest.raises(ValueError):
        split_train_test(bars, train_ratio=1.5)

    with pytest.raises(ValueError):
        split_train_test(bars, train_ratio=-0.1)

    # Empty data
    with pytest.raises(ValueError):
        split_train_test([], train_ratio=0.7)


def test_generate_walk_forward_windows_rolling() -> None:
    """Verify rolling Walk-Forward Analysis windows step cleanly with zero overlap."""
    bars = _generate_bars(60)
    windows = generate_walk_forward_windows(
        bars, train_size=30, test_size=10, step_size=10, anchored=False
    )

    # Window 0: Train [0:30], Test [30:40]
    # Window 1: Train [10:40], Test [40:50]
    # Window 2: Train [20:50], Test [50:60]
    assert len(windows) == 3

    for idx, w in enumerate(windows):
        assert w.window_index == idx
        assert len(w.train_bars) == 30
        assert len(w.test_bars) == 10
        # Assert zero leakage
        assert w.train_bars[-1].timestamp < w.test_bars[0].timestamp


def test_generate_walk_forward_windows_anchored() -> None:
    """Verify expanding/anchored Walk-Forward Analysis windows."""
    bars = _generate_bars(60)
    windows = generate_walk_forward_windows(
        bars, train_size=20, test_size=10, step_size=10, anchored=True
    )

    # Window 0: Train [0:20], Test [20:30]
    # Window 1: Train [0:30], Test [30:40]
    # Window 2: Train [0:40], Test [40:50]
    # Window 3: Train [0:50], Test [50:60]
    assert len(windows) == 4

    assert len(windows[0].train_bars) == 20
    assert len(windows[1].train_bars) == 30
    assert len(windows[2].train_bars) == 40
    assert len(windows[3].train_bars) == 50

    for w in windows:
        assert w.train_bars[-1].timestamp < w.test_bars[0].timestamp
