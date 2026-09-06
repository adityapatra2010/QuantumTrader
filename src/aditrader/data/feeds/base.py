"""Abstract DataFeed interface defining unified consumer protocol for all market data streams."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime

from aditrader.core.models.market_data import Bar


class DataFeed(ABC):
    """
    Abstract contract for market data feeds (historical CSV replay, synthetic generator, live streamer).

    Ensures upstream strategy engines and runners interact with an identical interface.
    """

    @abstractmethod
    def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to market data updates for the specified symbols."""
        pass

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "1m",
    ) -> list[Bar]:
        """Fetch historical bars up to point-in-time."""
        pass

    @abstractmethod
    def stream(self) -> Iterator[Bar]:
        """
        Yield immutable Bar objects chronologically.

        Guarantees point-in-time determinism with zero look-ahead bias.
        """
        pass
