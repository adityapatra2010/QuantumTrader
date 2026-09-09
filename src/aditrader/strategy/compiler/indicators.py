"""Statically registered, pure-function technical indicators.

Per ADR 007, dynamic code execution (eval, exec) is strictly prohibited.
All indicators are pure, deterministic functions operating on standard
Python numerical lists with zero external runtime script interpretation.
"""

import math
from typing import NamedTuple


class BollingerBandsResult(NamedTuple):
    """Container for Bollinger Bands output."""

    middle: float | None
    upper: float | None
    lower: float | None


class SupertrendResult(NamedTuple):
    """Container for Supertrend output."""

    value: float | None
    direction: int | None  # +1 for Bullish (Uptrend), -1 for Bearish (Downtrend)


def calculate_sma(values: list[float], period: int) -> list[float | None]:
    """Calculate Simple Moving Average (SMA).

    Args:
        values: Numerical series (e.g., closing prices).
        period: Rolling window length (must be > 0).

    Returns:
        List of SMA values matching input length, with None for indices < period - 1.
    """
    n = len(values)
    if period <= 0 or n < period:
        return [None] * n

    result: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, n):
        w_sum = math.fsum(values[i - period + 1 : i + 1])
        result.append(w_sum / period)

    return result


def calculate_ema(values: list[float], period: int) -> list[float | None]:
    """Calculate Exponential Moving Average (EMA).

    Args:
        values: Numerical series.
        period: Smoothing window length (must be > 0).

    Returns:
        List of EMA values matching input length, with None for indices < period - 1.
    """
    n = len(values)
    if period <= 0 or n < period:
        return [None] * n

    result: list[float | None] = [None] * (period - 1)
    alpha = 2.0 / (period + 1)

    # Seed EMA with initial SMA
    initial_sma = sum(values[:period]) / period
    result.append(initial_sma)

    current_ema = initial_sma
    for i in range(period, n):
        current_ema = values[i] * alpha + current_ema * (1.0 - alpha)
        result.append(current_ema)

    return result


def calculate_rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Calculate Relative Strength Index (RSI) using Wilder's Smoothing.

    Args:
        values: Price series.
        period: Lookback window (standard default 14).

    Returns:
        List of RSI values [0.0, 100.0] matching input length.
    """
    n = len(values)
    if period <= 0 or n <= period:
        return [None] * n

    result: list[float | None] = [None] * period

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0.0:
        rsi = 100.0 if avg_gain > 0.0 else 50.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
    result.append(rsi)

    for i in range(period + 1, n):
        diff = values[i] - values[i - 1]
        gain = max(0.0, diff)
        loss = max(0.0, -diff)

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0.0:
            rsi = 100.0 if avg_gain > 0.0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        result.append(rsi)

    return result


def calculate_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float | None]:
    """Calculate Average True Range (ATR) using Wilder's Smoothing.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        period: Smoothing period (default 14).

    Returns:
        List of ATR values matching input length.
    """
    n = len(closes)
    if period <= 0 or n < period or len(highs) != n or len(lows) != n:
        return [None] * n

    true_ranges: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    result: list[float | None] = [None] * (period - 1)
    initial_atr = sum(true_ranges[:period]) / period
    result.append(initial_atr)

    current_atr = initial_atr
    for i in range(period, n):
        current_atr = (current_atr * (period - 1) + true_ranges[i]) / period
        result.append(current_atr)

    return result


def calculate_bollinger_bands(
    values: list[float], period: int = 20, std_dev: float = 2.0
) -> list[BollingerBandsResult]:
    """Calculate Bollinger Bands (Middle SMA, Upper Band, Lower Band).

    Args:
        values: Price series.
        period: Rolling window length (default 20).
        std_dev: Number of standard deviations (default 2.0).

    Returns:
        List of BollingerBandsResult tuples.
    """
    n = len(values)
    if period <= 0 or n < period:
        return [BollingerBandsResult(None, None, None)] * n

    result: list[BollingerBandsResult] = [BollingerBandsResult(None, None, None)] * (period - 1)

    for i in range(period - 1, n):
        window = values[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        upper = mean + std_dev * std
        lower = mean - std_dev * std
        result.append(BollingerBandsResult(middle=mean, upper=upper, lower=lower))

    return result


def calculate_supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> list[SupertrendResult]:
    """Calculate Supertrend indicator.

    Args:
        highs: High price series.
        lows: Low price series.
        closes: Close price series.
        period: ATR lookback period (default 10).
        multiplier: Band multiplier factor (default 3.0).

    Returns:
        List of SupertrendResult named tuples with (value, direction).
        Direction: +1 (Bullish), -1 (Bearish).
    """
    n = len(closes)
    if period <= 0 or n < period or len(highs) != n or len(lows) != n:
        return [SupertrendResult(None, None)] * n

    atr_series = calculate_atr(highs, lows, closes, period=period)
    result: list[SupertrendResult] = [SupertrendResult(None, None)] * (period - 1)

    # Compute bands from index period - 1
    final_upper = 0.0
    final_lower = 0.0
    trend = 1

    for i in range(period - 1, n):
        atr = atr_series[i]
        if atr is None:
            result.append(SupertrendResult(None, None))
            continue

        hl2 = (highs[i] + lows[i]) / 2.0
        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        if i == period - 1:
            final_upper = basic_upper
            final_lower = basic_lower
            trend = 1 if closes[i] >= basic_lower else -1
            st_val = final_lower if trend == 1 else final_upper
            result.append(SupertrendResult(value=st_val, direction=trend))
            continue

        prev_close = closes[i - 1]

        # Final Upper Band
        if basic_upper < final_upper or prev_close > final_upper:
            final_upper = basic_upper

        # Final Lower Band
        if basic_lower > final_lower or prev_close < final_lower:
            final_lower = basic_lower

        # Trend Decision
        if trend == 1:
            if closes[i] < final_lower:
                trend = -1
                st_val = final_upper
            else:
                st_val = final_lower
        else:
            if closes[i] > final_upper:
                trend = 1
                st_val = final_lower
            else:
                st_val = final_upper

        result.append(SupertrendResult(value=st_val, direction=trend))

    return result
