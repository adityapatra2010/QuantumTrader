"""Deterministic synthetic market data generator for offline simulation and stress testing."""

import random
from collections.abc import Iterator
from datetime import datetime, timedelta

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.feeds.base import DataFeed
from aditrader.data.session import EXCHANGE_TIMEZONE, normalize_to_ist


class SyntheticDataFeed(DataFeed):
    """
    Generates deterministic synthetic OHLCV bars and ticks for unit testing and offline simulation.
    """

    def __init__(
        self,
        symbol: str,
        start_price: float = 24000.0,
        volatility: float = 0.001,
        drift: float = 0.0,
        interval_seconds: int = 60,
        start_time: datetime | None = None,
        num_bars: int = 100,
        seed: int = 42,
    ):
        self.symbol = symbol
        self.start_price = start_price
        self.volatility = volatility
        self.drift = drift
        self.interval_seconds = interval_seconds
        self.start_time = (
            normalize_to_ist(start_time)
            if start_time
            else datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
        )
        self.num_bars = num_bars
        self.seed = seed

        self._subscribed_symbols: set[str] = {symbol}
        self._bars: list[Bar] = []
        self._generate()

    def _generate(self) -> None:
        """Generate synthetic bars using seeded random walks."""
        rng = random.Random(self.seed)
        current_time = self.start_time
        current_price = self.start_price

        for _ in range(self.num_bars):
            # Generate 4 intermediate prices within the bar
            shocks = [rng.gauss(self.drift, self.volatility) for _ in range(4)]
            prices = [round(current_price * (1.0 + s), 2) for s in shocks]

            open_p = current_price
            close_p = prices[-1]
            high_p = max(open_p, close_p, max(prices))
            low_p = min(open_p, close_p, min(prices))
            volume = rng.randint(100, 5000)
            oi = rng.randint(50000, 200000)

            bar = Bar(
                timestamp=current_time,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=volume,
                oi=oi,
            )
            self._bars.append(bar)

            current_price = close_p
            current_time += timedelta(seconds=self.interval_seconds)

    def generate_ticks_for_bar(self, bar: Bar, num_ticks: int = 10) -> list[Tick]:
        """Generate intermediate ticks reconstructing the path of a given Bar."""
        rng = random.Random(self.seed + int(bar.timestamp.timestamp()))
        ticks: list[Tick] = []

        step = (bar.close - bar.open) / max(1, num_ticks - 1)
        tick_dt = timedelta(seconds=self.interval_seconds / max(1, num_ticks))

        curr_t = bar.timestamp
        curr_p = bar.open
        for i in range(num_ticks):
            if i == num_ticks - 1:
                price = bar.close
            else:
                noise = rng.uniform(-0.1, 0.1) * (bar.high - bar.low)
                price = round(curr_p + (step * i) + noise, 2)
                price = min(bar.high, max(bar.low, price))

            spread = round(price * 0.0002, 2)  # 2 bps spread
            bid = round(price - (spread / 2.0), 2)
            ask = round(price + (spread / 2.0), 2)

            tick = Tick(
                symbol=self.symbol,
                ltp=price,
                bid=bid,
                ask=ask,
                volume=rng.randint(10, 200),
                oi=bar.oi,
                timestamp=curr_t,
            )
            ticks.append(tick)
            curr_t += tick_dt

        return ticks

    def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to symbols."""
        self._subscribed_symbols.update(symbols)

    def get_history(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "1m",
    ) -> list[Bar]:
        """Return generated bars matching symbol and time range."""
        if symbol != self.symbol:
            return []
        start_ist = normalize_to_ist(start_time)
        end_ist = normalize_to_ist(end_time)
        return [b for b in self._bars if start_ist <= b.timestamp <= end_ist]

    def stream(self) -> Iterator[Bar]:
        """Stream generated bars sequentially."""
        if self.symbol in self._subscribed_symbols:
            yield from self._bars

    def __len__(self) -> int:
        return len(self._bars)
