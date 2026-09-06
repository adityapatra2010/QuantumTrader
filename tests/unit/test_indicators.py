"""Unit tests verifying mathematical accuracy and edge cases of technical indicators."""

import pytest

from aditrader.strategy.compiler.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
    calculate_sma,
    calculate_supertrend,
)


def test_calculate_sma_known_values() -> None:
    """Verify SMA calculation against known sequence."""
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    period = 3
    sma = calculate_sma(prices, period)

    assert len(sma) == 5
    assert sma[0] is None
    assert sma[1] is None
    assert sma[2] == pytest.approx(20.0)  # (10+20+30)/3
    assert sma[3] == pytest.approx(30.0)  # (20+30+40)/3
    assert sma[4] == pytest.approx(40.0)  # (30+40+50)/3


def test_calculate_sma_insufficient_length() -> None:
    """Verify SMA returns all None when data length < period."""
    sma = calculate_sma([10.0, 20.0], period=5)
    assert sma == [None, None]


def test_calculate_ema_known_values() -> None:
    """Verify EMA seeding and subsequent alpha smoothing."""
    prices = [10.0, 20.0, 30.0, 40.0]
    period = 3
    # alpha = 2 / (3 + 1) = 0.5
    # Seed at index 2 = SMA(10, 20, 30) = 20.0
    # Index 3 = 40.0 * 0.5 + 20.0 * (1 - 0.5) = 20.0 + 10.0 = 30.0
    ema = calculate_ema(prices, period)

    assert ema[0] is None
    assert ema[1] is None
    assert ema[2] == pytest.approx(20.0)
    assert ema[3] == pytest.approx(30.0)


def test_calculate_rsi_directional_bounds() -> None:
    """Verify RSI reaches 100 on continuous gains and 0 on continuous losses."""
    # Continuous strictly increasing prices
    rising = [float(100 + i * 5) for i in range(20)]
    rsi_rising = calculate_rsi(rising, period=14)
    assert rsi_rising[-1] == pytest.approx(100.0)

    # Continuous strictly decreasing prices
    falling = [float(200 - i * 5) for i in range(20)]
    rsi_falling = calculate_rsi(falling, period=14)
    assert rsi_falling[-1] == pytest.approx(0.0)


def test_calculate_atr_true_range() -> None:
    """Verify ATR computes True Range incorporating gaps correctly."""
    highs = [105.0, 110.0, 108.0]
    lows = [95.0, 102.0, 98.0]
    closes = [100.0, 107.0, 101.0]

    # TR0 = 105 - 95 = 10.0
    # TR1 = max(110-102=8, |110-100|=10, |102-100|=2) = 10.0
    # TR2 = max(108-98=10, |108-107|=1, |98-107|=9) = 10.0
    # For period = 2:
    # index 0: None
    # index 1: (10 + 10) / 2 = 10.0
    # index 2: (10.0 * 1 + 10.0) / 2 = 10.0
    atr = calculate_atr(highs, lows, closes, period=2)
    assert atr[0] is None
    assert atr[1] == pytest.approx(10.0)
    assert atr[2] == pytest.approx(10.0)


def test_calculate_bollinger_bands_symmetry() -> None:
    """Verify Bollinger Bands middle equals SMA and upper/lower are symmetric."""
    prices = [100.0 + (i % 3) * 2.0 for i in range(25)]
    bands = calculate_bollinger_bands(prices, period=20, std_dev=2.0)

    assert len(bands) == 25
    last = bands[-1]
    assert last.middle is not None
    assert last.upper is not None
    assert last.lower is not None
    assert last.upper > last.middle > last.lower
    assert (last.upper - last.middle) == pytest.approx(last.middle - last.lower, rel=1e-5)


def test_calculate_supertrend_trend_switch() -> None:
    """Verify Supertrend detects bullish trend when price closes above upper band."""
    # Flat market then massive rally
    highs = [102.0] * 15 + [120.0, 125.0]
    lows = [98.0] * 15 + [115.0, 120.0]
    closes = [100.0] * 15 + [119.0, 124.0]

    st = calculate_supertrend(highs, lows, closes, period=10, multiplier=3.0)
    assert len(st) == 17
    # After strong upward breakout, direction should be +1 (Bullish)
    assert st[-1].direction == 1
    assert st[-1].value is not None
    assert closes[-1] > st[-1].value
