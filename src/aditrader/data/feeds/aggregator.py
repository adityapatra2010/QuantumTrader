"""Thread-safe RingBuffer and live Tick-to-Bar Aggregator."""

import threading
from collections import deque
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Generic, TypeVar

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.session import EXCHANGE_TIMEZONE, normalize_to_ist

T = TypeVar("T")


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
    """

    def __init__(
        self,
        symbol: str,
        interval_seconds: int = 60,
        max_tick_history: int = 10_000,
        max_bar_history: int = 1_000,
        on_bar_close: Callable[[Bar], None] | None = None,
    ):
        self.symbol = symbol
        self.interval_seconds = interval_seconds
        self.on_bar_close = on_bar_close

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

    def _get_bucket_start(self, dt: datetime) -> datetime:
        """Floor timestamp to the beginning of the interval window in IST."""
        ist_dt = normalize_to_ist(dt)
        epoch = int(ist_dt.timestamp())
        bucket_epoch = (epoch // self.interval_seconds) * self.interval_seconds
        return datetime.fromtimestamp(bucket_epoch, tz=EXCHANGE_TIMEZONE)

    def process_tick(self, tick: Tick) -> Bar | None:
        """
        Ingest a tick: updates current active candle.

        If a new interval window has commenced, closes and emits the previous Bar.
        Returns the completed Bar if one closed, or None if still building.
        """
        if tick.symbol != self.symbol:
            return None

        ist_time = normalize_to_ist(tick.timestamp)
        bucket_start = self._get_bucket_start(ist_time)
        closed_bar: Bar | None = None

        with self._lock:
            self.tick_buffer.append(tick)

            # Check for interval rollover
            if self._current_bucket_start is not None and bucket_start > self._current_bucket_start:
                # Close current bar
                closed_bar = Bar(
                    timestamp=self._current_bucket_start,
                    open=self._curr_open,
                    high=self._curr_high,
                    low=self._curr_low,
                    close=self._curr_close,
                    volume=self._curr_volume,
                    oi=self._curr_oi or 0,
                )
                self.bar_buffer.append(closed_bar)

                # Reset accumulator for new bucket
                self._current_bucket_start = bucket_start
                self._curr_open = tick.ltp
                self._curr_high = tick.ltp
                self._curr_low = tick.ltp
                self._curr_close = tick.ltp
                self._curr_volume = 1
                self._curr_oi = tick.oi
            elif self._current_bucket_start is None:
                # Initialize first bar
                self._current_bucket_start = bucket_start
                self._curr_open = tick.ltp
                self._curr_high = tick.ltp
                self._curr_low = tick.ltp
                self._curr_close = tick.ltp
                self._curr_volume = 1
                self._curr_oi = tick.oi
            else:
                # Same bucket: update running values
                self._curr_high = max(self._curr_high, tick.ltp)
                self._curr_low = min(self._curr_low, tick.ltp)
                self._curr_close = tick.ltp
                self._curr_volume += 1
                self._curr_oi = tick.oi

        if closed_bar is not None and self.on_bar_close is not None:
            self.on_bar_close(closed_bar)

        return closed_bar

    def flush(self) -> Bar | None:
        """Force flush current active bar at end of session or replay."""
        with self._lock:
            if self._current_bucket_start is None:
                return None

            closed_bar = Bar(
                timestamp=self._current_bucket_start,
                open=self._curr_open,
                high=self._curr_high,
                low=self._curr_low,
                close=self._curr_close,
                volume=self._curr_volume,
                oi=self._curr_oi or 0,
            )
            self.bar_buffer.append(closed_bar)
            self._current_bucket_start = None

        if self.on_bar_close is not None:
            self.on_bar_close(closed_bar)

        return closed_bar
