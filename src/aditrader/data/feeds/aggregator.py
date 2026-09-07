"""Thread-safe RingBuffer and live Tick-to-Bar Aggregator with data quality guards."""

import threading
from collections import deque
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Generic, Literal, TypeVar

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.session import EXCHANGE_TIMEZONE, normalize_to_ist

T = TypeVar("T")


class OutOfOrderTickError(ValueError):
    """Raised when an incoming tick timestamp is earlier than closed bar boundaries."""


class DuplicateTickError(ValueError):
    """Raised when an identical duplicate tick is detected in strict mode."""


class RingBuffer(Generic[T]):
    """
    Thread-safe fixed-capacity circular buffer (ADR 008).

    Prevents unbounded memory growth in high-frequency tick and bar ingestion.
    """

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("RingBuffer capacity must be strictly positive")
        self.capacity = capacity
        self._buffer: deque[T] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, item: T) -> None:
        """Add an item to the ring buffer, evicting oldest item if at capacity."""
        with self._lock:
            self._buffer.append(item)

    def extend(self, items: list[T]) -> None:
        """Append multiple items thread-safely."""
        with self._lock:
            self._buffer.extend(items)

    def get_latest(self) -> T | None:
        """Retrieve the most recently added item without removing it."""
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def get_all(self) -> list[T]:
        """Return a snapshot list of all buffered items in chronological order."""
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Clear all buffered items."""
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __iter__(self) -> Iterator[T]:
        with self._lock:
            return iter(list(self._buffer))


class TickAggregator:
    """
    Aggregates incoming streaming Ticks into immutable OHLCV Bar events (1m, 3m, 5m, etc.).

    Thread-safe; maintains low-latency ring buffers for recent ticks and closed bars.
    Guarantees out-of-order detection, duplicate handling, and volume aggregation modes.
    """

    def __init__(
        self,
        symbol: str,
        interval_seconds: int = 60,
        max_tick_history: int = 10_000,
        max_bar_history: int = 1_000,
        on_bar_close: Callable[[Bar], None] | None = None,
        volume_mode: Literal["TICK_COUNT", "CUMULATIVE", "INCREMENTAL", "TRADED_VOLUME"] = (
            "TICK_COUNT"
        ),
        strict: bool = False,
        ignore_duplicates: bool = True,
    ):
        self.symbol = symbol
        self.interval_seconds = interval_seconds
        self.on_bar_close = on_bar_close
        self.volume_mode = volume_mode
        self.strict = strict
        self.ignore_duplicates = ignore_duplicates

        self.tick_buffer: RingBuffer[Tick] = RingBuffer(max_tick_history)
        self.bar_buffer: RingBuffer[Bar] = RingBuffer(max_bar_history)

        self._lock = threading.Lock()
        self._current_bucket_start: datetime | None = None
        self._curr_open: float = 0.0
        self._curr_high: float = 0.0
        self._curr_low: float = 0.0
        self._curr_close: float = 0.0
        self._curr_volume: int = 0
        self._curr_oi: int | None = None
        self._curr_tick_count: int = 0
        self._curr_pv_sum: float = 0.0

        # Quality tracking metrics
        self._last_tick_time: datetime | None = None
        self._last_tick: Tick | None = None
        self._last_session_volume: int | None = None
        self._out_of_order_count: int = 0
        self._duplicate_count: int = 0
        self._total_ticks_processed: int = 0
        self._bars_emitted: int = 0
        self._is_synthetic: bool = False

    def _get_bucket_start(self, dt: datetime) -> datetime:
        """Floor timestamp to the beginning of the interval window in IST."""
        ist_dt = normalize_to_ist(dt)
        epoch = int(ist_dt.timestamp())
        bucket_epoch = (epoch // self.interval_seconds) * self.interval_seconds
        return datetime.fromtimestamp(bucket_epoch, tz=EXCHANGE_TIMEZONE)

    def _calculate_volume_delta(self, tick: Tick) -> int:
        """Calculate volume contribution based on configured volume_mode."""
        if self.volume_mode == "TICK_COUNT":
            return 1

        if self.volume_mode == "INCREMENTAL":
            return max(0, tick.volume)

        # CUMULATIVE or TRADED_VOLUME mode: session cumulative volume deltas
        if self._last_session_volume is None:
            self._last_session_volume = tick.volume
            return max(0, tick.volume)

        if tick.volume >= self._last_session_volume:
            delta = tick.volume - self._last_session_volume
            self._last_session_volume = tick.volume
            return delta

        # Session volume reset or rollover
        self._last_session_volume = tick.volume
        return max(0, tick.volume)

    def process_tick(self, tick: Tick) -> Bar | None:
        """
        Ingest a tick: updates current active candle.

        If a new interval window has commenced, closes and emits the previous Bar.
        Returns the completed Bar if one closed, or None if still building.

        Raises:
            OutOfOrderTickError: If tick timestamp belongs to an already-closed bucket (strict mode).
            DuplicateTickError: If duplicate tick received (strict mode with ignore_duplicates=False).
        """
        if tick.symbol != self.symbol:
            return None

        ist_time = normalize_to_ist(tick.timestamp)
        bucket_start = self._get_bucket_start(ist_time)
        closed_bar: Bar | None = None

        with self._lock:
            self._total_ticks_processed += 1
            if tick.is_synthetic:
                self._is_synthetic = True

            # 1. Out of order detection
            if self._current_bucket_start is not None and bucket_start < self._current_bucket_start:
                self._out_of_order_count += 1
                if self.strict:
                    raise OutOfOrderTickError(
                        f"Out-of-order tick at {ist_time.isoformat()} arrived after active bucket {self._current_bucket_start.isoformat()}"
                    )
                # Drop to prevent past tick from contaminating the current candle
                return None

            if (
                self._current_bucket_start is not None
                and bucket_start == self._current_bucket_start
                and self._last_tick_time is not None
                and ist_time < self._last_tick_time
            ):
                self._out_of_order_count += 1
                if self.strict:
                    raise OutOfOrderTickError(
                        f"Retrograde tick timestamp {ist_time.isoformat()} < previous {self._last_tick_time.isoformat()}"
                    )

            # 2. Duplicate detection
            if (
                self._last_tick is not None
                and ist_time == normalize_to_ist(self._last_tick.timestamp)
                and tick.ltp == self._last_tick.ltp
                and tick.volume == self._last_tick.volume
            ):
                self._duplicate_count += 1
                if self.strict and not self.ignore_duplicates:
                    raise DuplicateTickError(
                        f"Duplicate tick detected at timestamp {ist_time.isoformat()}"
                    )
                if self.ignore_duplicates:
                    # Skip duplicate to avoid artificial volume inflation
                    return None

            self.tick_buffer.append(tick)
            delta_vol = self._calculate_volume_delta(tick)

            # 3. Check for interval rollover
            if self._current_bucket_start is not None and bucket_start > self._current_bucket_start:
                # Close current bar
                vwap = (
                    round(self._curr_pv_sum / self._curr_volume, 2)
                    if self._curr_volume > 0
                    else self._curr_close
                )
                closed_bar = Bar(
                    timestamp=self._current_bucket_start,
                    symbol=self.symbol,
                    open=self._curr_open,
                    high=self._curr_high,
                    low=self._curr_low,
                    close=self._curr_close,
                    volume=self._curr_volume,
                    oi=self._curr_oi or 0,
                    vwap=vwap,
                    tick_count=self._curr_tick_count,
                    source="TICK_AGGREGATOR",
                    timeframe=f"{self.interval_seconds}s",
                    is_synthetic=self._is_synthetic,
                )
                self.bar_buffer.append(closed_bar)
                self._bars_emitted += 1

                # Reset accumulator for new bucket
                self._current_bucket_start = bucket_start
                self._curr_open = tick.ltp
                self._curr_high = tick.ltp
                self._curr_low = tick.ltp
                self._curr_close = tick.ltp
                self._curr_volume = delta_vol
                self._curr_oi = tick.oi
                self._curr_tick_count = 1
                vol_weight = 1 if self.volume_mode == "TICK_COUNT" else delta_vol
                self._curr_pv_sum = tick.ltp * vol_weight
            elif self._current_bucket_start is None:
                # Initialize first bar
                self._current_bucket_start = bucket_start
                self._curr_open = tick.ltp
                self._curr_high = tick.ltp
                self._curr_low = tick.ltp
                self._curr_close = tick.ltp
                self._curr_volume = delta_vol
                self._curr_oi = tick.oi
                self._curr_tick_count = 1
                vol_weight = 1 if self.volume_mode == "TICK_COUNT" else delta_vol
                self._curr_pv_sum = tick.ltp * vol_weight
            else:
                # Same bucket: update running values
                self._curr_high = max(self._curr_high, tick.ltp)
                self._curr_low = min(self._curr_low, tick.ltp)
                self._curr_close = tick.ltp
                self._curr_volume += delta_vol
                if tick.oi is not None:
                    self._curr_oi = tick.oi
                self._curr_tick_count += 1
                vol_weight = 1 if self.volume_mode == "TICK_COUNT" else delta_vol
                self._curr_pv_sum += tick.ltp * vol_weight

            self._last_tick = tick
            self._last_tick_time = ist_time

        if closed_bar is not None and self.on_bar_close is not None:
            self.on_bar_close(closed_bar)

        return closed_bar

    def flush(self, emit_callback: bool = False) -> Bar | None:
        """Force flush current active bar at end of session or replay.

        Args:
            emit_callback: If True, invokes on_bar_close callback. Defaults to False
                           to prevent incomplete partial bars during engine shutdown
                           from triggering strategy signals or paper fills.
        """
        with self._lock:
            if self._current_bucket_start is None:
                return None

            vwap = (
                round(self._curr_pv_sum / self._curr_volume, 2)
                if self._curr_volume > 0
                else self._curr_close
            )
            closed_bar = Bar(
                timestamp=self._current_bucket_start,
                symbol=self.symbol,
                open=self._curr_open,
                high=self._curr_high,
                low=self._curr_low,
                close=self._curr_close,
                volume=self._curr_volume,
                oi=self._curr_oi or 0,
                vwap=vwap,
                tick_count=self._curr_tick_count,
                source="TICK_AGGREGATOR",
                timeframe=f"{self.interval_seconds}s",
                is_synthetic=self._is_synthetic,
            )
            self.bar_buffer.append(closed_bar)
            self._bars_emitted += 1
            self._current_bucket_start = None

        if emit_callback and self.on_bar_close is not None:
            self.on_bar_close(closed_bar)

        return closed_bar

    @property
    def quality_stats(self) -> dict[str, int]:
        """Return diagnostic metrics of ticks processed, rejected, and bars emitted."""
        with self._lock:
            return {
                "total_ticks": self._total_ticks_processed,
                "out_of_order": self._out_of_order_count,
                "duplicates": self._duplicate_count,
                "bars_emitted": self._bars_emitted,
            }
