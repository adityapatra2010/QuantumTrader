"""Local Parquet and columnar caching layer for high-throughput market data persistence."""

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.session import EXCHANGE_TIMEZONE, normalize_to_ist


class LocalDataCache:
    """
    Parquet file cache storing historical bars and ticks locally (ADR 008).

    Prevents repeated remote API calls and enables ultra-fast point-in-time replays.
    """

    def __init__(self, cache_dir: str | Path = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_bar_cache_path(self, symbol: str, timeframe: str) -> Path:
        sanitized = symbol.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{sanitized}_{timeframe}.parquet"

    def _get_tick_cache_path(self, symbol: str, date_key: str) -> Path:
        sanitized = symbol.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{sanitized}_ticks_{date_key}.parquet"

    def save_bars(self, symbol: str, timeframe: str, bars: list[Bar]) -> Path:
        """Serialize a sequence of Bar objects into a Parquet file."""
        if not bars:
            path = self._get_bar_cache_path(symbol, timeframe)
            return path

        timestamps = [b.timestamp.isoformat() for b in bars]
        symbols = [symbol for _ in bars]
        opens = [b.open for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]
        ois = [b.oi for b in bars]

        table = pa.Table.from_arrays(
            [
                pa.array(timestamps, pa.string()),
                pa.array(symbols, pa.string()),
                pa.array(opens, pa.float64()),
                pa.array(highs, pa.float64()),
                pa.array(lows, pa.float64()),
                pa.array(closes, pa.float64()),
                pa.array(volumes, pa.int64()),
                pa.array(ois, pa.int64()),
            ],
            names=[
                "timestamp",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "open_interest",
            ],
        )

        target_path = self._get_bar_cache_path(symbol, timeframe)
        pq.write_table(table, target_path, compression="zstd")
        return target_path

    def load_bars(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Bar]:
        """Load and deserialize cached Bar objects from Parquet file."""
        cache_path = self._get_bar_cache_path(symbol, timeframe)
        if not cache_path.is_file():
            return []

        table = pq.read_table(cache_path)
        pydict = table.to_pydict()

        bars: list[Bar] = []
        n_rows = len(pydict["timestamp"])

        start_ist = normalize_to_ist(start_time) if start_time else None
        end_ist = normalize_to_ist(end_time) if end_time else None

        for i in range(n_rows):
            ts = normalize_to_ist(datetime.fromisoformat(pydict["timestamp"][i]))
            if start_ist and ts < start_ist:
                continue
            if end_ist and ts > end_ist:
                continue

            bar = Bar(
                timestamp=ts,
                open=float(pydict["open"][i]),
                high=float(pydict["high"][i]),
                low=float(pydict["low"][i]),
                close=float(pydict["close"][i]),
                volume=int(pydict["volume"][i]),
                oi=int(pydict["open_interest"][i]),
            )
            bars.append(bar)

        bars.sort(key=lambda b: b.timestamp)
        return bars

    def save_ticks(self, symbol: str, date_key: str, ticks: list[Tick]) -> Path:
        """Serialize a sequence of Tick objects into a Parquet file."""
        target_path = self._get_tick_cache_path(symbol, date_key)
        if not ticks:
            return target_path

        timestamps = [t.timestamp.isoformat() for t in ticks]
        symbols = [t.symbol for t in ticks]
        ltps = [t.ltp for t in ticks]
        volumes = [t.volume for t in ticks]
        bids = [t.bid for t in ticks]
        asks = [t.ask for t in ticks]
        ois = [t.oi for t in ticks]

        table = pa.Table.from_arrays(
            [
                pa.array(timestamps, pa.string()),
                pa.array(symbols, pa.string()),
                pa.array(ltps, pa.float64()),
                pa.array(volumes, pa.int64()),
                pa.array(bids, pa.float64()),
                pa.array(asks, pa.float64()),
                pa.array(ois, pa.int64()),
            ],
            names=[
                "timestamp",
                "symbol",
                "ltp",
                "volume",
                "bid",
                "ask",
                "open_interest",
            ],
        )

        pq.write_table(table, target_path, compression="zstd")
        return target_path

    def load_ticks(self, symbol: str, date_key: str) -> list[Tick]:
        """Load and deserialize cached Tick objects from Parquet file."""
        cache_path = self._get_tick_cache_path(symbol, date_key)
        if not cache_path.is_file():
            return []

        table = pq.read_table(cache_path)
        pydict = table.to_pydict()

        ticks: list[Tick] = []
        n_rows = len(pydict["timestamp"])

        for i in range(n_rows):
            ts = datetime.fromisoformat(pydict["timestamp"][i])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=EXCHANGE_TIMEZONE)

            tick = Tick(
                symbol=pydict["symbol"][i],
                ltp=float(pydict["ltp"][i]),
                volume=int(pydict["volume"][i]),
                bid=float(pydict["bid"][i]),
                ask=float(pydict["ask"][i]),
                oi=int(pydict["open_interest"][i]),
                timestamp=ts,
            )
            ticks.append(tick)

        return ticks

    def clear(self, symbol: str | None = None) -> None:
        """Clear cache files for symbol or all cached files."""
        pattern = f"{symbol}*.parquet" if symbol else "*.parquet"
        for p in self.cache_dir.glob(pattern):
            p.unlink()
