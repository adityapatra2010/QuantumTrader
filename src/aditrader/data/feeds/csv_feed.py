"""Deterministic historical CSV candle replay feed enforcing strict point-in-time sequencing."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.feeds.base import DataFeed
from aditrader.data.feeds.nse_csv import NSECSVParser, parse_flexible_timestamp
from aditrader.data.session import normalize_to_ist


class CSVDataFeed(DataFeed):
    """
    Historical OHLCV data feed reading from CSV files.

    Guarantees:
    1. Strict exchange timezone localization (Asia/Kolkata).
    2. Deterministic chronological replay (no look-ahead leakage).
    3. Price envelope validation via immutable Bar models.
    4. Truthful quote replay (never fabricates synthetic bid/ask quotes).
    """

    def __init__(
        self,
        file_path: str | Path,
        symbol: str,
        timeframe: str = "1m",
        session_filter: bool = False,
    ):
        self.file_path = Path(file_path)
        self.symbol = symbol
        self.timeframe = timeframe
        self.session_filter = session_filter
        self._bars: list[Bar] = []
        self._warnings: list[str] = []
        self._subscribed_symbols: set[str] = {symbol}
        self._load_and_validate()

    @property
    def warnings(self) -> list[str]:
        """Diagnostic warnings produced during CSV parsing and normalization."""
        return list(self._warnings)

    def _load_and_validate(self) -> None:
        """Parse, validate, and chronologically sort historical bars from CSV."""
        if not self.file_path.is_file():
            raise FileNotFoundError(f"CSV historical file not found: {self.file_path}")

        bars, warnings = NSECSVParser.parse_file(
            file_path=self.file_path,
            symbol=self.symbol,
            timeframe=self.timeframe,
            session_filter=self.session_filter,
        )
        self._bars = bars
        self._warnings = warnings

    def _parse_timestamp(self, ts_str: str) -> datetime:
        """Parse various ISO and standard date formats (backward-compatible)."""
        return parse_flexible_timestamp(ts_str)

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
        """Fetch historical bars within the given window."""
        start_ist = normalize_to_ist(start_time)
        end_ist = normalize_to_ist(end_time)
        if symbol != self.symbol:
            return []
        return [b for b in self._bars if start_ist <= b.timestamp <= end_ist]

    def stream(self) -> Iterator[Bar]:
        """Chronologically yield immutable Bar instances one by one."""
        if self.symbol in self._subscribed_symbols:
            yield from self._bars

    def stream_ticks(self) -> Iterator[Tick]:
        """
        Chronologically yield authentic Tick objects without fabricating synthetic bid/ask quotes.

        Missing quotes remain strictly None to preserve research truthfulness.
        """
        if self.symbol in self._subscribed_symbols:
            for b in self._bars:
                yield Tick(
                    symbol=self.symbol,
                    ltp=b.close,
                    bid=None,
                    ask=None,
                    volume=b.volume,
                    oi=b.oi,
                    timestamp=b.timestamp,
                    source="CSV_REPLAY",
                    is_synthetic=False,
                )

    def __len__(self) -> int:
        """Return number of loaded bars."""
        return len(self._bars)
