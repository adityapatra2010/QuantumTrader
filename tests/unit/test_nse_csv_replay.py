"""Comprehensive unit tests verifying NSE CSV replay, Bhavcopy variants, and dataset inspection."""

from datetime import date
from pathlib import Path

import pytest

from aditrader.cli.commands import cmd_inspect_data
from aditrader.data.feeds.csv_feed import CSVDataFeed
from aditrader.data.feeds.nse_csv import (
    NSECSVFormat,
    NSECSVInspector,
    parse_flexible_timestamp,
)
from aditrader.data.session import EXCHANGE_TIMEZONE


class DummyArgs:
    """Helper mock for CLI arguments."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def test_parse_flexible_timestamp_formats() -> None:
    """Verify timestamp parsing across varied ISO, Bhavcopy, and split date/time formats."""
    # Split date + time
    ts1 = parse_flexible_timestamp("2024-01-15", "09:15:00")
    assert ts1.year == 2024 and ts1.month == 1 and ts1.day == 15
    assert ts1.hour == 9 and ts1.minute == 15 and ts1.second == 0
    assert ts1.tzinfo == EXCHANGE_TIMEZONE

    # Bhavcopy dd-MMM-yyyy
    ts2 = parse_flexible_timestamp("01-JAN-2024", "15:30:00")
    assert ts2.date() == date(2024, 1, 1)
    assert ts2.hour == 15 and ts2.minute == 30

    # Date string normalized to IST
    ts3 = parse_flexible_timestamp("2024-05-10")
    assert ts3.date() == date(2024, 5, 10)
    assert ts3.tzinfo == EXCHANGE_TIMEZONE

    # Invalid timestamp raises ValueError
    with pytest.raises(ValueError, match="Could not parse timestamp"):
        parse_flexible_timestamp("invalid-date-string")


def test_intraday_csv_with_separate_date_and_time(tmp_path: Path) -> None:
    """Verify intraday CSV with separate Date and Time columns loads without dropping rows."""
    csv_file = tmp_path / "nifty_intraday.csv"
    csv_content = """Date,Time,Open,High,Low,Close,Volume
2024-01-15,09:15:00,21500.0,21520.0,21490.0,21510.0,1500
2024-01-15,09:16:00,21510.0,21525.0,21505.0,21515.0,1200
2024-01-15,09:17:00,21515.0,21530.0,21510.0,21520.0,1800
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="NIFTY", timeframe="1m")
    assert len(feed) == 3

    bars = list(feed.stream())
    assert len(bars) == 3
    assert bars[0].timestamp.hour == 9 and bars[0].timestamp.minute == 15
    assert bars[1].timestamp.hour == 9 and bars[1].timestamp.minute == 16
    assert bars[2].timestamp.hour == 9 and bars[2].timestamp.minute == 17
    assert bars[0].volume == 1500
    assert bars[1].volume == 1200
    assert bars[2].volume == 1800


def test_nse_cm_bhavcopy_parsing(tmp_path: Path) -> None:
    """Verify parsing of NSE Capital Market Bhavcopy with TOTTRDQTY and TOTTRDVAL."""
    csv_file = tmp_path / "cm_bhav.csv"
    csv_content = """SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN
RELIANCE,EQ,2800.0,2820.0,2795.0,2810.0,2812.0,2790.0,100000,281000000.0,15-JAN-2024,5200,INE002A01018
TCS,EQ,3800.0,3830.0,3790.0,3820.0,3815.0,3780.0,50000,191000000.0,15-JAN-2024,3100,INE467B01029
RELIANCE,BL,2805.0,2805.0,2805.0,2805.0,2805.0,2800.0,10000,28050000.0,15-JAN-2024,1,INE002A01018
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="RELIANCE", timeframe="1d")
    assert len(feed) == 1
    bar = feed._bars[0]
    assert bar.symbol == "RELIANCE"
    assert bar.open == 2800.0
    assert bar.close == 2810.0
    assert bar.volume == 100000
    assert bar.tick_count == 5200
    assert bar.vwap == 2810.0  # 281,000,000 / 100,000


def test_nse_fo_bhavcopy_parsing(tmp_path: Path) -> None:
    """Verify parsing of NSE Derivatives FO Bhavcopy with CONTRACTS and OPEN_INT."""
    csv_file = tmp_path / "fo_bhav.csv"
    csv_content = """INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP
OPTIDX,NIFTY,25-JAN-2024,21500.0,CE,150.0,180.0,140.0,165.0,165.0,2500,4125.0,85000,5000,15-JAN-2024
OPTIDX,NIFTY,25-JAN-2024,21500.0,PE,120.0,140.0,110.0,125.0,125.0,1800,2250.0,62000,-1200,15-JAN-2024
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="NIFTY21500.0CE", timeframe="1d")
    assert len(feed) == 1
    bar = feed._bars[0]
    assert bar.symbol == "NIFTY21500.0CE"
    assert bar.open == 150.0
    assert bar.high == 180.0
    assert bar.close == 165.0
    assert bar.volume == 2500
    assert bar.oi == 85000


def test_nse_index_historical_with_commas(tmp_path: Path) -> None:
    """Verify parsing of NSE historical index CSV with comma-separated numbers."""
    csv_file = tmp_path / "nifty_index.csv"
    csv_content = """Date,Open,High,Low,Close,Shares Traded,Turnover (Rs. Cr)
15-Jan-2024,"21,500.50","21,550.00","21,480.25","21,520.10","25,432,100","1,234.56"
16-Jan-2024,"21,525.00","21,580.00","21,510.00","21,570.00","22,100,500","1,050.20"
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="NIFTY", timeframe="1d")
    assert len(feed) == 2
    assert feed._bars[0].open == 21500.50
    assert feed._bars[0].volume == 25432100
    assert feed._bars[1].close == 21570.00


def test_price_envelope_and_invalid_row_filtering(tmp_path: Path) -> None:
    """Verify rows with high < low or negative prices are recorded in warnings and rejected."""
    csv_file = tmp_path / "corrupt_bars.csv"
    csv_content = """timestamp,open,high,low,close,volume
2024-01-15 09:15:00,100.0,105.0,95.0,102.0,100
2024-01-15 09:16:00,100.0,90.0,110.0,95.0,100
2024-01-15 09:17:00,-10.0,10.0,5.0,8.0,100
2024-01-15 09:18:00,102.0,108.0,100.0,105.0,150
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="TEST")
    # Rows 2 and 3 should be rejected, leaving rows 1 and 4
    assert len(feed) == 2
    assert len(feed.warnings) >= 2
    assert any("Invalid OHLC price envelope" in w for w in feed.warnings)
    assert any("Non-positive OHLC price" in w for w in feed.warnings)


def test_csv_feed_stream_ticks_truthful_quotes(tmp_path: Path) -> None:
    """Verify stream_ticks yields canonical Tick objects with bid=None and ask=None."""
    csv_file = tmp_path / "ticks_test.csv"
    csv_content = """timestamp,open,high,low,close,volume,oi
2024-01-15 09:15:00,21500.0,21520.0,21490.0,21510.0,150,50000
2024-01-15 09:16:00,21510.0,21525.0,21505.0,21515.0,200,50100
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    feed = CSVDataFeed(csv_file, symbol="NIFTY")
    ticks = list(feed.stream_ticks())

    assert len(ticks) == 2
    for t in ticks:
        assert t.symbol == "NIFTY"
        assert t.source == "CSV_REPLAY"
        assert t.is_synthetic is False
        # Research truthfulness invariant: NO synthetic quotes fabricated
        assert t.bid is None
        assert t.ask is None
        assert t.bid_qty is None
        assert t.ask_qty is None

    assert ticks[0].ltp == 21510.0
    assert ticks[0].volume == 150
    assert ticks[0].oi == 50000


def test_dataset_inspector_reporting(tmp_path: Path) -> None:
    """Verify NSECSVInspector generates comprehensive diagnostics."""
    csv_file = tmp_path / "nifty_sample.csv"
    csv_content = """Date,Time,Open,High,Low,Close,Volume,OI
2024-01-15,09:15:00,21500.0,21520.0,21490.0,21510.0,150,50000
2024-01-15,09:16:00,21510.0,21525.0,21505.0,21515.0,200,50100
2024-01-15,09:17:00,21515.0,21530.0,21510.0,21525.0,180,50200
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    rep = NSECSVInspector.inspect_file(csv_file)
    assert rep.detected_format == NSECSVFormat.INTRADAY
    assert rep.is_valid_replayable is True
    assert rep.parsed_bars == 3
    assert rep.timeframe_detected == "1m"
    assert rep.has_volume is True
    assert rep.has_oi is True
    assert "date" in rep.columns_found
    assert "time" in rep.columns_found


def test_cli_cmd_inspect_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify aditrader inspect-data CLI outputs formatted terminal report."""
    csv_file = tmp_path / "report_sample.csv"
    csv_file.write_text(
        "timestamp,open,high,low,close,volume\n2024-01-15 09:15:00,100,105,95,102,500\n",
        encoding="utf-8",
    )

    args = DummyArgs(file=str(csv_file), symbol=None)
    exit_code = cmd_inspect_data(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Market Data Dataset Inspector" in captured.out
    assert "Replay Ready:     YES - VALID" in captured.out
    assert "Parsed Bars:      1" in captured.out
    assert "Quality Check:    CLEAN" in captured.out
