"""Unit tests verifying CSVDataFeed parsing, chronological replay, and session filtering."""

from datetime import datetime
from pathlib import Path

from aditrader.data.feeds.csv_feed import CSVDataFeed
from aditrader.data.session import EXCHANGE_TIMEZONE


def test_csv_feed_load_and_chronological_sort(tmp_path: Path) -> None:
    """Verify CSV feed loads out-of-order rows and sorts them ascending."""
    csv_file = tmp_path / "nifty_test.csv"
    # Write rows deliberately out of order with one duplicate
    csv_content = """timestamp,open,high,low,close,volume,oi
2024-12-02 09:16:00,24010.0,24020.0,24005.0,24015.0,150,50000
2024-12-02 09:15:00,24000.0,24015.0,23995.0,24010.0,100,50000
2024-12-02 09:16:00,24010.0,24020.0,24005.0,24015.0,150,50000
2024-12-02 09:17:00,24015.0,24030.0,24010.0,24025.0,200,50200
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="NIFTY")
    assert len(feed) == 3  # Deduplicated from 4 to 3

    bars = list(feed.stream())
    assert len(bars) == 3

    # Check ascending chronological sequence
    assert bars[0].timestamp == datetime(2024, 12, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
    assert bars[1].timestamp == datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE)
    assert bars[2].timestamp == datetime(2024, 12, 2, 9, 17, tzinfo=EXCHANGE_TIMEZONE)

    # Check OHLCV integrity
    assert bars[0].open == 24000.0
    assert bars[0].high == 24015.0
    assert bars[0].low == 23995.0
    assert bars[0].close == 24010.0
    assert bars[0].volume == 100
    assert bars[0].oi == 50000


def test_csv_feed_session_filter(tmp_path: Path) -> None:
    """Verify session_filter excludes off-market hours."""
    csv_file = tmp_path / "nifty_offmarket.csv"
    csv_content = """timestamp,open,high,low,close,volume,oi
2024-12-02 08:30:00,23900.0,23920.0,23890.0,23910.0,50,40000
2024-12-02 09:15:00,24000.0,24015.0,23995.0,24010.0,100,50000
2024-12-02 16:00:00,24050.0,24060.0,24040.0,24055.0,30,50100
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed_unfiltered = CSVDataFeed(csv_file, symbol="NIFTY", session_filter=False)
    assert len(feed_unfiltered) == 3

    feed_filtered = CSVDataFeed(csv_file, symbol="NIFTY", session_filter=True)
    assert len(feed_filtered) == 1
    assert feed_filtered._bars[0].timestamp.hour == 9
    assert feed_filtered._bars[0].timestamp.minute == 15


def test_csv_feed_get_history_window(tmp_path: Path) -> None:
    """Verify get_history extracts the exact requested window."""
    csv_file = tmp_path / "nifty_history.csv"
    csv_content = """timestamp,open,high,low,close,volume,oi
2024-12-02 09:15:00,24000.0,24015.0,23995.0,24010.0,100,50000
2024-12-02 09:16:00,24010.0,24020.0,24005.0,24015.0,150,50000
2024-12-02 09:17:00,24015.0,24030.0,24010.0,24025.0,200,50200
2024-12-02 09:18:00,24025.0,24035.0,24020.0,24030.0,120,50300
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="NIFTY")
    history = feed.get_history(
        symbol="NIFTY",
        start_time=datetime(2024, 12, 2, 9, 16, tzinfo=EXCHANGE_TIMEZONE),
        end_time=datetime(2024, 12, 2, 9, 17, tzinfo=EXCHANGE_TIMEZONE),
    )
    assert len(history) == 2
    assert history[0].open == 24010.0
    assert history[1].open == 24015.0
