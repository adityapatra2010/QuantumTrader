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
        symbols = [b.symbol for b in bars]
        opens = [b.open for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]
        ois = [b.oi for b in bars]
        vwaps = [b.vwap for b in bars]
        tick_counts = [b.tick_count for b in bars]
        sources = [b.source for b in bars]
        timeframes = [b.timeframe for b in bars]
        is_synthetics = [b.is_synthetic for b in bars]

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
                pa.array(vwaps, pa.float64()),
                pa.array(tick_counts, pa.int64()),
                pa.array(sources, pa.string()),
                pa.array(timeframes, pa.string()),
                pa.array(is_synthetics, pa.bool_()),
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
                "vwap",
                "tick_count",
                "source",
                "timeframe",
                "is_synthetic",
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

        vwap_col = pydict.get("vwap")
        tc_col = pydict.get("tick_count")
        src_col = pydict.get("source")
        tf_col = pydict.get("timeframe")
        syn_col = pydict.get("is_synthetic")
        sym_col = pydict.get("symbol")

        for i in range(n_rows):
            ts = normalize_to_ist(datetime.fromisoformat(pydict["timestamp"][i]))
            if start_ist and ts < start_ist:
                continue
            if end_ist and ts > end_ist:
                continue

            vwap = float(vwap_col[i]) if vwap_col and vwap_col[i] is not None else None
            tick_count = int(tc_col[i]) if tc_col and tc_col[i] is not None else None
            source = str(src_col[i]) if src_col and src_col[i] is not None else None
            tf = str(tf_col[i]) if tf_col and tf_col[i] is not None else None
            is_syn = bool(syn_col[i]) if syn_col and syn_col[i] is not None else False
            bar_sym = str(sym_col[i]) if sym_col and sym_col[i] is not None else None

            bar = Bar(
                timestamp=ts,
                open=float(pydict["open"][i]),
                high=float(pydict["high"][i]),
                low=float(pydict["low"][i]),
                close=float(pydict["close"][i]),
                volume=int(pydict["volume"][i]),
                oi=int(pydict["open_interest"][i]),
                symbol=bar_sym,
                vwap=vwap,
                tick_count=tick_count,
                source=source,
                timeframe=tf,
                is_synthetic=is_syn,
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
        bid_qtys = [t.bid_qty for t in ticks]
        ask_qtys = [t.ask_qty for t in ticks]
        exchanges = [t.exchange for t in ticks]
        tokens = [t.instrument_token for t in ticks]
        sources = [t.source for t in ticks]
        data_types = [t.data_type for t in ticks]
        is_synthetics = [t.is_synthetic for t in ticks]

        table = pa.Table.from_arrays(
            [
                pa.array(timestamps, pa.string()),
                pa.array(symbols, pa.string()),
                pa.array(ltps, pa.float64()),
                pa.array(volumes, pa.int64()),
                pa.array(bids, pa.float64()),
                pa.array(asks, pa.float64()),
                pa.array(ois, pa.int64()),
                pa.array(bid_qtys, pa.int64()),
                pa.array(ask_qtys, pa.int64()),
                pa.array(exchanges, pa.string()),
                pa.array(tokens, pa.string()),
                pa.array(sources, pa.string()),
                pa.array(data_types, pa.string()),
                pa.array(is_synthetics, pa.bool_()),
            ],
            names=[
                "timestamp",
                "symbol",
                "ltp",
                "volume",
                "bid",
                "ask",
                "open_interest",
                "bid_qty",
                "ask_qty",
                "exchange",
                "instrument_token",
                "source",
                "data_type",
                "is_synthetic",
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

        bid_col = pydict.get("bid")
        ask_col = pydict.get("ask")
        oi_col = pydict.get("open_interest")
        bid_qty_col = pydict.get("bid_qty")
        ask_qty_col = pydict.get("ask_qty")
        exch_col = pydict.get("exchange")
        tok_col = pydict.get("instrument_token")
        src_col = pydict.get("source")
        dt_col = pydict.get("data_type")
        syn_col = pydict.get("is_synthetic")

        for i in range(n_rows):
            ts = datetime.fromisoformat(pydict["timestamp"][i])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=EXCHANGE_TIMEZONE)

            bid = float(bid_col[i]) if bid_col and bid_col[i] is not None else None
            ask = float(ask_col[i]) if ask_col and ask_col[i] is not None else None
            oi = int(oi_col[i]) if oi_col and oi_col[i] is not None else None
            bid_qty = int(bid_qty_col[i]) if bid_qty_col and bid_qty_col[i] is not None else None
            ask_qty = int(ask_qty_col[i]) if ask_qty_col and ask_qty_col[i] is not None else None
            exch = str(exch_col[i]) if exch_col and exch_col[i] is not None else None
            tok = str(tok_col[i]) if tok_col and tok_col[i] is not None else None
            source = str(src_col[i]) if src_col and src_col[i] is not None else None
            data_type = str(dt_col[i]) if dt_col and dt_col[i] is not None else "TICK"
            is_syn = bool(syn_col[i]) if syn_col and syn_col[i] is not None else False

            tick = Tick(
                symbol=pydict["symbol"][i],
                ltp=float(pydict["ltp"][i]),
                volume=int(pydict["volume"][i]),
                bid=bid,
                ask=ask,
                oi=oi,
                bid_qty=bid_qty,
                ask_qty=ask_qty,
                exchange=exch,
                instrument_token=tok,
                source=source,
                data_type=data_type,
                is_synthetic=is_syn,
                timestamp=ts,
            )
            ticks.append(tick)

        return ticks

    def clear(self, symbol: str | None = None) -> None:
        """Clear cache files for symbol or all cached files."""
        pattern = f"{symbol}*.parquet" if symbol else "*.parquet"
        for p in self.cache_dir.glob(pattern):
            p.unlink()
