"""Comprehensive regression tests for NSE Derivative Quote CSV format support."""

import argparse
from datetime import date
from pathlib import Path

import pytest

from aditrader.cli.commands import cmd_forward_test, cmd_inspect_data
from aditrader.data.feeds.csv_feed import CSVDataFeed
from aditrader.data.feeds.nse_csv import (
    NSECSVFormat,
    NSECSVInspector,
    NSECSVParser,
    _clean_header,
    _extract_underlying_from_filename,
    _parse_date_only,
    _parse_float,
    _parse_int,
)

REAL_RELIANCE_CSV = Path(
    "/home/aditya/Downloads/Quote-Derivative-RELIANCE-07-03-2026-07-09-2026.csv"
)

DummyArgs = argparse.Namespace


SAMPLE_DERIVATIVE_CSV = """\ufeffDate,Expiry Date,Option Type,Strike Price,Open Price,High Price,Low Price,Close Price,Last Price,Settlement Price,Volume,Value  (₹ Lakhs) ,Premium Value  (₹ Lakhs) ,Open Interest,Change in OI
04-Sep-2026,29-Sep-2026,CE,"1,370.00","6.55","12.70","6.25","10.55","9.85","10.55","48,01,500","6,62,77,34,900.00","4,96,79,900.00","12,11,000","29,000"
04-Sep-2026,27-Oct-2026,CE,"1,170.00","-","-","-","166.35","-","167.75","-","-","-","-","-"
04-Sep-2026,29-Sep-2026,PE,"1,300.00","15.00","18.50","12.00","14.50","14.20","14.50","20,000","2,60,00,000.00","3,00,000.00","50,000","-5,000"
04-Sep-2026,29-Sep-2026,XX,"-","1,313.50","1,341.90","1,312.50","1,335.60","1,334.20","1,335.60","1,55,04,500","20,69,18,51,400.00","20,69,18,51,400.00","12,90,35,500","-82,500"
"""


def test_clean_header_normalization() -> None:
    """Verify header cleaning strips BOM, angle brackets, and collapses internal spaces."""
    assert _clean_header("\ufeffDate") == "date"
    assert _clean_header("Value  (₹ Lakhs) ") == "value (₹ lakhs)"
    assert _clean_header("Premium Value  (₹ Lakhs) ") == "premium value (₹ lakhs)"
    assert _clean_header("<OPEN_PRICE>") == "open_price"
    assert _clean_header("  Strike   Price  ") == "strike price"


def test_numeric_parsing_helpers() -> None:
    """Verify numeric parser handles Indian number formatting, commas, dashes, and signs."""
    assert _parse_float("1,370.00") == 1370.0
    assert _parse_float("  -  ") is None
    assert _parse_float("") is None
    assert _parse_float("invalid") is None
    assert _parse_float("-12.50") == -12.50

    assert _parse_int("48,01,500") == 4801500
    assert _parse_int("-82,500") == -82500
    assert _parse_int("-") is None
    assert _parse_int(None) is None


def test_date_and_expiry_flexible_parsing() -> None:
    """Verify date parsing for NSE date representations."""
    d1 = _parse_date_only("04-Sep-2026")
    assert d1 == date(2026, 9, 4)

    d2 = _parse_date_only("29-Sep-2026")
    assert d2 == date(2026, 9, 29)

    d3 = _parse_date_only("07-03-2026")
    assert d3 == date(2026, 3, 7)

    d4 = _parse_date_only("2026-09-04")
    assert d4 == date(2026, 9, 4)

    assert _parse_date_only("not-a-date") is None


def test_extract_underlying_from_filename() -> None:
    """Verify underlying extraction from standard NSE derivative quote filenames."""
    path1 = Path("/tmp/Quote-Derivative-RELIANCE-07-03-2026-07-09-2026.csv")
    assert _extract_underlying_from_filename(str(path1)) == "RELIANCE"

    path2 = Path("/tmp/Quote-Derivative-NIFTY-01-01-2026-01-02-2026.csv")
    assert _extract_underlying_from_filename(str(path2)) == "NIFTY"

    path3 = Path("/tmp/other_data.csv")
    assert _extract_underlying_from_filename(str(path3)) is None


def test_detect_format_derivative_quote(tmp_path: Path) -> None:
    """Verify NSECSVParser identifies DERIVATIVE_QUOTE format correctly from file and columns."""
    csv_file = tmp_path / "derivative.csv"
    csv_file.write_text(SAMPLE_DERIVATIVE_CSV, encoding="utf-8")

    # From file path
    fmt = NSECSVParser.detect_format(csv_file)
    assert fmt == NSECSVFormat.DERIVATIVE_QUOTE

    # From column list
    cols = ["Date", "Expiry Date", "Option Type", "Strike Price", "Open Price", "Settlement Price"]
    assert NSECSVParser.detect_format(cols) == NSECSVFormat.DERIVATIVE_QUOTE

    # Ensure CM Bhavcopy is not detected as derivative quote
    cm_csv = tmp_path / "cm.csv"
    cm_csv.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN\n"
        "RELIANCE,EQ,2800,2820,2795,2810,2812,2790,100000,281000000,15-JAN-2024,5200,INE002A01018\n",
        encoding="utf-8",
    )
    assert NSECSVParser.detect_format(cm_csv) == NSECSVFormat.CM_BHAVCOPY


def test_parse_derivative_quotes_structure(tmp_path: Path) -> None:
    """Verify parsing all 15 columns into typed DerivativeQuoteRecord objects."""
    csv_file = tmp_path / "Quote-Derivative-RELIANCE-07-03-2026-07-09-2026.csv"
    csv_file.write_text(SAMPLE_DERIVATIVE_CSV, encoding="utf-8")

    quotes, warnings = NSECSVParser.parse_derivative_quotes(csv_file, symbol="RELIANCE")

    assert len(quotes) == 4
    record_map = {q.contract_symbol: q for q in quotes}

    q_call = record_map["RELIANCE 29-Sep-2026 CE 1370"]
    assert q_call.underlying == "RELIANCE"
    assert q_call.symbol == "RELIANCE"
    assert q_call.option_type == "CE"
    assert q_call.strike_price == 1370.00
    assert q_call.expiry_date == date(2026, 9, 29)
    assert q_call.open_price == 6.55
    assert q_call.high_price == 12.70
    assert q_call.low_price == 6.25
    assert q_call.close_price == 10.55
    assert q_call.last_price == 9.85
    assert q_call.settlement_price == 10.55
    assert q_call.volume == 4801500
    assert q_call.open_interest == 1211000
    assert q_call.change_in_oi == 29000
    assert q_call.contract_symbol == "RELIANCE 29-Sep-2026 CE 1370"

    # Untraded row
    q_untraded = record_map["RELIANCE 27-Oct-2026 CE 1170"]
    assert q_untraded.open_price is None
    assert q_untraded.high_price is None
    assert q_untraded.low_price is None
    assert q_untraded.close_price == 166.35
    assert q_untraded.last_price is None
    assert q_untraded.settlement_price == 167.75
    assert q_untraded.volume == 0
    assert q_untraded.open_interest is None

    # Futures row
    q_fut = record_map["RELIANCE 29-Sep-2026 FUT"]
    assert q_fut.option_type == "XX"
    assert q_fut.strike_price is None
    assert q_fut.open_price == 1313.50
    assert q_fut.change_in_oi == -82500
    assert q_fut.contract_symbol == "RELIANCE 29-Sep-2026 FUT"


def test_zero_false_ohlc_warnings_for_untraded_rows(tmp_path: Path) -> None:
    """Verify parse_file handles untraded rows without emitting corrupt OHLC warnings."""
    csv_file = tmp_path / "derivative.csv"
    csv_file.write_text(SAMPLE_DERIVATIVE_CSV, encoding="utf-8")

    bars, warnings = NSECSVParser.parse_file(csv_file, symbol="RELIANCE")

    # Out of 4 rows: 1 untraded CE (skipped for bars), 1 traded CE, 1 traded PE, 1 traded XX
    assert len(bars) == 3
    symbols = [b.symbol for b in bars]
    assert "RELIANCE 29-Sep-2026 CE 1370" in symbols
    assert "RELIANCE 29-Sep-2026 PE 1300" in symbols
    assert "RELIANCE 29-Sep-2026 FUT" in symbols

    # Crucially, zero warnings emitted
    assert len(warnings) == 0


def test_no_synthetic_bid_ask_fabrication(tmp_path: Path) -> None:
    """Verify that derivative quote parser never fabricates synthetic bid/ask quotes."""
    csv_file = tmp_path / "derivative.csv"
    csv_file.write_text(SAMPLE_DERIVATIVE_CSV, encoding="utf-8")

    bars, warnings = NSECSVParser.parse_file(csv_file, symbol="RELIANCE")

    for bar in bars:
        assert getattr(bar, "bid", None) is None, "Bid price must not be synthetically fabricated"
        assert getattr(bar, "ask", None) is None, "Ask price must not be synthetically fabricated"


def test_vwap_computation_distinction(tmp_path: Path) -> None:
    """Verify VWAP computation uses premium turnover for options and contracts/turnover for futures."""
    csv_file = tmp_path / "derivative.csv"
    csv_file.write_text(SAMPLE_DERIVATIVE_CSV, encoding="utf-8")

    bars, warnings = NSECSVParser.parse_file(csv_file, symbol="RELIANCE")

    bar_map = {b.symbol: b for b in bars}
    pe_bar = bar_map["RELIANCE 29-Sep-2026 PE 1300"]
    # Premium Value (₹ Lakhs) = 3.00, volume = 20,000 -> VWAP = (3.0 * 100000) / 20000 = 15.0
    assert pe_bar.vwap is not None
    assert round(pe_bar.vwap, 2) == 15.00


def test_dataset_inspector_derivative_report(tmp_path: Path) -> None:
    """Verify NSECSVInspector generates rich metadata for derivative quote files."""
    csv_file = tmp_path / "Quote-Derivative-RELIANCE-07-03-2026-07-09-2026.csv"
    csv_file.write_text(SAMPLE_DERIVATIVE_CSV, encoding="utf-8")

    inspector = NSECSVInspector()
    report = inspector.inspect_file(csv_file)

    assert report.detected_format == "NSE_DERIVATIVE_QUOTE"
    assert report.is_replayable is False
    assert report.is_valid_replayable is False
    assert report.replay_ineligibility_reason is not None
    assert "options execution is air-gapped" in report.replay_ineligibility_reason
    assert report.total_derivative_rows == 4
    assert report.underlying_symbols == ["RELIANCE"]
    assert len(report.expiries_found) == 2
    assert "CE" in report.option_types
    assert "PE" in report.option_types
    assert "XX" in report.option_types
    assert len(report.warnings) == 0
    assert len(report.quality_warnings) == 0


def test_replay_air_gap_prevention(tmp_path: Path) -> None:
    """Verify CSVDataFeed rejects multi-contract derivative quotes to uphold ADR 002/011 air gap."""
    csv_file = tmp_path / "Quote-Derivative-RELIANCE-07-03-2026-07-09-2026.csv"
    csv_file.write_text(SAMPLE_DERIVATIVE_CSV, encoding="utf-8")

    with pytest.raises(ValueError, match="NSE_DERIVATIVE_QUOTE"):
        CSVDataFeed(csv_file, symbol="RELIANCE", timeframe="1d")

    # CLI forward-test command must also refuse and exit cleanly with code 1
    args = DummyArgs(
        strategy="test_ma_crossover",
        csv=str(csv_file),
        symbol="RELIANCE",
        timeframe="1d",
        output="output",
        start_capital=100000.0,
    )
    ret = cmd_forward_test(args)
    assert ret == 1


@pytest.mark.skipif(
    not REAL_RELIANCE_CSV.exists(), reason="Real Reliance derivative CSV not present"
)
def test_real_reliance_download_dataset() -> None:
    """Verify 100% fidelity on the actual ~/Downloads/Quote-Derivative-RELIANCE... CSV."""
    inspector = NSECSVInspector()
    report = inspector.inspect_file(REAL_RELIANCE_CSV)

    assert report.detected_format == "NSE_DERIVATIVE_QUOTE"
    assert report.total_lines == 27160
    assert report.total_derivative_rows == 27159
    assert report.parsed_bars == 18690
    assert len(report.warnings) == 0, f"Expected 0 warnings, got: {report.warnings[:5]}"
    assert report.underlying_symbols == ["RELIANCE"]
    assert len(report.expiries_found) >= 9
    assert "CE" in report.option_types
    assert "PE" in report.option_types
    assert "XX" in report.option_types
    assert report.is_replayable is False

    # CLI inspect-data command runs and exits with code 0
    args = DummyArgs(
        file=str(REAL_RELIANCE_CSV),
        symbol="RELIANCE",
        format=None,
        max_rows=10,
    )
    ret = cmd_inspect_data(args)
    assert ret == 0
