"""Deterministic historical CSV candle replay feed enforcing strict point-in-time sequencing."""

import csv
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from aditrader.core.models.market_data import Bar
from aditrader.data.feeds.base import DataFeed
from aditrader.data.session import is_market_open, normalize_to_ist


class CSVDataFeed(DataFeed):
    """
    Historical OHLCV data feed reading from CSV files.

    Guarantees:
    1. Strict exchange timezone localization (Asia/Kolkata).
    2. Deterministic chronological replay (no look-ahead leakage).
    3. Price envelope validation via immutable Bar models.
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
        self._subscribed_symbols: set[str] = {symbol}
        self._load_and_validate()

    def _load_and_validate(self) -> None:
        """Parse, validate, and chronologically sort historical bars from CSV."""
        if not self.file_path.is_file():
            raise FileNotFoundError(f"CSV historical file not found: {self.file_path}")

        loaded: list[Bar] = []
        with open(self.file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize column keys to lowercase
                cleaned_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

                # Parse timestamp
                ts_raw = (
                    cleaned_row.get("timestamp")
                    or cleaned_row.get("datetime")
                    or cleaned_row.get("date")
                )
                if not ts_raw:
                    continue

                ts = self._parse_timestamp(ts_raw)
                ist_ts = normalize_to_ist(ts)

                if self.session_filter and not is_market_open(ist_ts):
                    continue

                open_p = float(cleaned_row["open"])
                high_p = float(cleaned_row["high"])
                low_p = float(cleaned_row["low"])
                close_p = float(cleaned_row["close"])
                volume = int(float(cleaned_row.get("volume", 0)))
                oi = int(float(cleaned_row.get("oi", 0)))

                vwap_raw = cleaned_row.get("vwap")
                vwap = float(vwap_raw) if vwap_raw and float(vwap_raw) > 0 else None
                tc_raw = cleaned_row.get("tick_count", cleaned_row.get("ticks"))
                tick_count = int(float(tc_raw)) if tc_raw and int(float(tc_raw)) >= 0 else None

                bar = Bar(
                    timestamp=ist_ts,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                    volume=volume,
                    oi=oi,
                    symbol=self.symbol,
                    vwap=vwap,
                    tick_count=tick_count,
                    source="CSV_HISTORICAL",
                    timeframe=self.timeframe,
                    is_synthetic=False,
                )
                loaded.append(bar)

        # Sort strictly ascending by timestamp (prevents look-ahead / out-of-order bugs)
        loaded.sort(key=lambda b: b.timestamp)

        # Deduplicate identical timestamps if any
        deduped: list[Bar] = []
        seen_ts: set[datetime] = set()
        for b in loaded:
            if b.timestamp not in seen_ts:
                deduped.append(b)
                seen_ts.add(b.timestamp)

        self._bars = deduped

    def _parse_timestamp(self, ts_str: str) -> datetime:
        """Parse various ISO and standard date formats."""
        for fmt in (
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%d-%m-%Y %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        # Fallback to fromisoformat
        return datetime.fromisoformat(ts_str)

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

    def __len__(self) -> int:
        """Return number of loaded bars."""
        return len(self._bars)
