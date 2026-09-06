"""Chronological dataset partitioning and anti-overfitting harnesses.

Per .agents/skills/backtesting-engine.md:
Enforces zero lookahead bias and guarantees strict point-in-time separation:
train_bars[-1].timestamp < test_bars[0].timestamp across all splits.
"""

from typing import NamedTuple

from aditrader.core.models.market_data import Bar


class WalkForwardWindow(NamedTuple):
    """Container for a single Walk-Forward Analysis (WFA) step."""

    window_index: int
    train_bars: list[Bar]
    test_bars: list[Bar]


def split_train_test(bars: list[Bar], train_ratio: float = 0.7) -> tuple[list[Bar], list[Bar]]:
    """Chronologically partition bars into in-sample (train) and out-of-sample (test) sets.

    Args:
        bars: Chronologically sorted historical candle bars.
        train_ratio: Fraction of data allocated to training (must be 0.0 < ratio < 1.0).

    Returns:
        Tuple of (train_bars, test_bars).

    Raises:
        ValueError: If input is empty or train_ratio is out of range.
    """
    n = len(bars)
    if n < 2:
        raise ValueError(f"Need at least 2 bars for train/test split, got {n}")
    if not (0.0 < train_ratio < 1.0):
        raise ValueError(f"train_ratio must be between 0.0 and 1.0, got {train_ratio}")

    split_idx = int(n * train_ratio)
    if split_idx == 0:
        split_idx = 1
    elif split_idx == n:
        split_idx = n - 1

    train_bars = bars[:split_idx]
    test_bars = bars[split_idx:]

    # Assert zero lookahead / chronological ordering
    if train_bars[-1].timestamp >= test_bars[0].timestamp:
        raise ValueError(
            f"Chronological ordering violation: train end ({train_bars[-1].timestamp}) "
            f"must be strictly before test start ({test_bars[0].timestamp})"
        )

    return train_bars, test_bars


def split_out_of_sample(
    bars: list[Bar], in_sample_ratio: float = 0.8
) -> tuple[list[Bar], list[Bar]]:
    """Alias for chronological Out-of-Sample (OOS) partitioning."""
    return split_train_test(bars, train_ratio=in_sample_ratio)


def generate_walk_forward_windows(
    bars: list[Bar],
    train_size: int,
    test_size: int,
    step_size: int | None = None,
    anchored: bool = False,
) -> list[WalkForwardWindow]:
    """Generate rolling or anchored Walk-Forward Analysis (WFA) windows.

    Args:
        bars: Chronologically ordered candle bars.
        train_size: Number of bars in training window.
        test_size: Number of bars in testing window.
        step_size: Number of bars to advance each iteration (defaults to test_size).
        anchored: If True, training window always starts at bar 0 (expanding window).

    Returns:
        List of WalkForwardWindow named tuples.

    Raises:
        ValueError: If parameters are invalid or bar history is insufficient.
    """
    n = len(bars)
    if train_size <= 0 or test_size <= 0:
        raise ValueError("train_size and test_size must be positive integers")

    step = step_size if step_size is not None and step_size > 0 else test_size
    min_required = train_size + test_size
    if n < min_required:
        raise ValueError(
            f"Insufficient bars for walk-forward analysis: need at least {min_required}, got {n}"
        )

    windows: list[WalkForwardWindow] = []
    window_idx = 0

    while True:
        actual_train_start = 0 if anchored else window_idx * step
        end_train_idx = (
            (train_size + window_idx * step) if anchored else (actual_train_start + train_size)
        )
        start_test_idx = end_train_idx
        end_test_idx = start_test_idx + test_size

        if end_test_idx > n:
            break

        train_slice = bars[actual_train_start:end_train_idx]
        test_slice = bars[start_test_idx:end_test_idx]

        # Verify no overlap
        if train_slice[-1].timestamp >= test_slice[0].timestamp:
            raise ValueError(
                f"Overlap detected in window {window_idx}: "
                f"train end {train_slice[-1].timestamp} >= test start {test_slice[0].timestamp}"
            )

        windows.append(
            WalkForwardWindow(
                window_index=window_idx,
                train_bars=train_slice,
                test_bars=test_slice,
            )
        )

        window_idx += 1

    return windows
