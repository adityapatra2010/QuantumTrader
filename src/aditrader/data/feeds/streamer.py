"""Unified DataFeedStreamer coordinating live feeds, historical replays, and session limits."""

import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Literal

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.adapters.base import AbstractBrokerAdapter
from aditrader.data.feeds.aggregator import TickAggregator
from aditrader.data.feeds.base import DataFeed
from aditrader.data.session import get_session_status, is_market_open, normalize_to_ist


class DataFeedStreamer:
    """
    Stream orchestrator exposing an identical consumer interface for live and historical feeds.

    Acceptance Criteria (SPEC.md Phase 2):
    Live WebSocket feeds and CSV historical files drive the runner loop through an identical interface.
    """

    def __init__(
        self,
        mode: Literal["HISTORICAL", "LIVE", "SYNTHETIC"] = "HISTORICAL",
        feed: DataFeed | None = None,
        adapter: AbstractBrokerAdapter | None = None,
        interval_seconds: int = 60,
        enforce_session_hours: bool = False,
    ):
        self.mode = mode
        self.feed = feed
        self.adapter = adapter
        self.interval_seconds = interval_seconds
        self.enforce_session_hours = enforce_session_hours

        self._aggregators: dict[str, TickAggregator] = {}
        self._bar_subscribers: list[Callable[[Bar], None]] = []
        self._tick_subscribers: list[Callable[[Tick], None]] = []
        self._subscribed_symbols: set[str] = set()
        self._is_running = False
        self._lock = threading.Lock()

    def subscribe_symbol(self, symbol: str) -> None:
        """Subscribe to a symbol and initialize an aggregator for it."""
        with self._lock:
            self._subscribed_symbols.add(symbol)
            if symbol not in self._aggregators:
                self._aggregators[symbol] = TickAggregator(
                    symbol=symbol,
                    interval_seconds=self.interval_seconds,
                    on_bar_close=self._dispatch_bar,
                )

        if self.feed:
            self.feed.subscribe([symbol])
        if self.adapter and self.adapter.is_connected():
            self.adapter.subscribe_ticks([symbol], self.on_live_tick)

    def add_bar_listener(self, listener: Callable[[Bar], None]) -> None:
        """Register a callback for completed Bar events."""
        with self._lock:
            if listener not in self._bar_subscribers:
                self._bar_subscribers.append(listener)

    def add_tick_listener(self, listener: Callable[[Tick], None]) -> None:
        """Register a callback for raw Tick events."""
        with self._lock:
            if listener not in self._tick_subscribers:
                self._tick_subscribers.append(listener)

    def _dispatch_bar(self, bar: Bar) -> None:
        """Dispatch completed bar to all registered listeners."""
        with self._lock:
            listeners = list(self._bar_subscribers)
        for listener in listeners:
            listener(bar)

    def _dispatch_tick(self, tick: Tick) -> None:
        """Dispatch tick to all registered listeners."""
        with self._lock:
            listeners = list(self._tick_subscribers)
        for listener in listeners:
            listener(tick)

    def on_live_tick(self, tick: Tick) -> None:
        """Handler invoked by broker adapter WebSocket for incoming live ticks."""
        if self.enforce_session_hours and not is_market_open(tick.timestamp):
            # Outside market hours: halt processing cleanly
            return

        self._dispatch_tick(tick)

        # Aggregate into bar
        agg = self._aggregators.get(tick.symbol)
        if agg:
            agg.process_tick(tick)

    def stream_historical(self) -> Iterator[Bar]:
        """
        Stream historical bars chronologically from the underlying DataFeed.

        Dispatches to listeners and yields Bar objects.
        """
        if not self.feed:
            raise ValueError("No historical DataFeed configured for historical streaming")

        for bar in self.feed.stream():
            if self.enforce_session_hours and not is_market_open(bar.timestamp):
                continue

            self._dispatch_bar(bar)
            yield bar

    def flush_active_bars(self) -> list[Bar]:
        """Flush currently forming bars from aggregators (e.g. at end of session)."""
        flushed: list[Bar] = []
        with self._lock:
            for agg in self._aggregators.values():
                b = agg.flush()
                if b is not None:
                    flushed.append(b)
        return flushed

    def check_market_session(self, dt: datetime | None = None) -> str:
        """Check status of NSE trading session."""
        ts = dt or datetime.now()
        status = get_session_status(normalize_to_ist(ts))
        return status.value
