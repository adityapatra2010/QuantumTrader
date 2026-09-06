"""Unit tests verifying local Parquet caching of Bar and Tick datasets."""

from datetime import datetime
from pathlib import Path

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.cache import LocalDataCache
from aditrader.data.session import EXCHANGE_TIMEZONE


def test_parquet_bar_cache_roundtrip(tmp_path: Path) -> None:
    """Verify writing Bar objects to Parquet and reading back reproduces identical data."""
    cache = LocalDataCache(cache_dir=tmp_path)

    t1 = datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    t2 = datetime(2024, 12, 2, 9, 16, 0, tzinfo=EXCHANGE_TIMEZONE)

    bars = [
        Bar(
            timestamp=t1,
            open=24000.0,
            high=24015.0,
            low=23995.0,
            close=24010.0,
            volume=100,
            oi=50000,
        ),
        Bar(
            timestamp=t2,
            open=24010.0,
            high=24025.0,
            low=24005.0,
            close=24020.0,
            volume=150,
            oi=50100,
        ),
    ]

    saved_path = cache.save_bars(symbol="NIFTY", timeframe="1m", bars=bars)
    assert saved_path.is_file()

    loaded = cache.load_bars(symbol="NIFTY", timeframe="1m")
    assert len(loaded) == 2
    assert loaded[0] == bars[0]
    assert loaded[1] == bars[1]


def test_parquet_tick_cache_roundtrip(tmp_path: Path) -> None:
    """Verify writing Tick objects to Parquet and reading back accurately."""
    cache = LocalDataCache(cache_dir=tmp_path)

    t1 = datetime(2024, 12, 2, 9, 15, 5, tzinfo=EXCHANGE_TIMEZONE)
    ticks = [
        Tick(
            symbol="NIFTY",
            ltp=24005.0,
            bid=24004.0,
            ask=24006.0,
            volume=100,
            oi=50000,
            timestamp=t1,
        ),
    ]

    saved_path = cache.save_ticks(symbol="NIFTY", date_key="20241202", ticks=ticks)
    assert saved_path.is_file()

    loaded = cache.load_ticks(symbol="NIFTY", date_key="20241202")
    assert len(loaded) == 1
    assert loaded[0] == ticks[0]


def test_parquet_cache_window_filtering(tmp_path: Path) -> None:
    """Verify loading from Parquet filters by start and end timestamps."""
    cache = LocalDataCache(cache_dir=tmp_path)

    t1 = datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    t2 = datetime(2024, 12, 2, 9, 16, 0, tzinfo=EXCHANGE_TIMEZONE)
    t3 = datetime(2024, 12, 2, 9, 17, 0, tzinfo=EXCHANGE_TIMEZONE)

    bars = [
        Bar(
            timestamp=t1,
            open=24000.0,
            high=24010.0,
            low=23990.0,
            close=24005.0,
            volume=100,
            oi=50000,
        ),
        Bar(
            timestamp=t2,
            open=24005.0,
            high=24020.0,
            low=24000.0,
            close=24015.0,
            volume=120,
            oi=50000,
        ),
        Bar(
            timestamp=t3,
            open=24015.0,
            high=24030.0,
            low=24010.0,
            close=24025.0,
            volume=140,
            oi=50000,
        ),
    ]

    cache.save_bars(symbol="NIFTY", timeframe="1m", bars=bars)

    # Filter to only t2
    loaded = cache.load_bars(symbol="NIFTY", timeframe="1m", start_time=t2, end_time=t2)
    assert len(loaded) == 1
    assert loaded[0] == bars[1]
