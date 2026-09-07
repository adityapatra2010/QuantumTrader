"""Comprehensive NSE CSV detection, parsing, and inspection engine.

Supports:
1. NSE Intraday 1m/5m/15m OHLCV (separate Date + Time columns or unified timestamp).
2. NSE Capital Market (CM) Bhavcopy (SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES).
3. NSE Futures & Options (FO) Bhavcopy (INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH, LOW, CLOSE, CONTRACTS, OPEN_INT, TIMESTAMP).
4. NSE Historical Index CSV (Date, Open, High, Low, Close, Shares Traded, Turnover).
5. Generic OHLCV CSV with standard header variations.

Guarantees:
- Strict Asia/Kolkata timezone normalization.
- Robust parsing of formatted numbers with commas, empty values, or dashes.
- Refusal to fabricate synthetic bid/ask quotes (leaves bid/ask as None).
- Chronological sorting with detection of out-of-order rows and duplicates.
- Static data-quality inspection and pre-replay diagnostic reporting.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from datetime import date, datetime
from datetime import time as dt_time
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.market_data import Bar, DerivativeQuoteRecord
from aditrader.data.session import is_market_open, normalize_to_ist


class NSECSVFormat(StrEnum):
    """Classification of recognized NSE and generic CSV market-data formats."""

    INTRADAY = "NSE_INTRADAY"
    CM_BHAVCOPY = "NSE_CM_BHAVCOPY"
    FO_BHAVCOPY = "NSE_FO_BHAVCOPY"
    INDEX_HISTORY = "NSE_INDEX_HISTORY"
    DERIVATIVE_QUOTE = "NSE_DERIVATIVE_QUOTE"
    GENERIC_OHLCV = "GENERIC_OHLCV"
    UNKNOWN = "UNKNOWN"


class CSVInspectionReport(BaseModel):
    """Comprehensive diagnostic report summarizing dataset layout and replay suitability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str = Field(..., description="Absolute or relative path to inspected CSV file")
    file_size_bytes: int = Field(..., ge=0, description="Size of file on disk in bytes")
    detected_format: NSECSVFormat = Field(..., description="Detected schema classification")
    total_lines: int = Field(..., ge=0, description="Total raw lines in file including header")
    parsed_bars: int = Field(..., ge=0, description="Count of successfully parsed OHLCV bars")
    symbols: list[str] = Field(default_factory=list, description="Symbols discovered in dataset")
    timeframe_detected: str = Field(..., description="Estimated timeframe (e.g. '1m', '5m', '1d')")
    start_time: str | None = Field(default=None, description="Earliest timestamp in ISO IST format")
    end_time: str | None = Field(default=None, description="Latest timestamp in ISO IST format")
    columns_found: list[str] = Field(
        default_factory=list, description="Cleaned column header names"
    )
    has_volume: bool = Field(default=False, description="True if non-zero volume is present")
    has_oi: bool = Field(default=False, description="True if open interest is present")
    has_vwap: bool = Field(default=False, description="True if VWAP is present or calculable")
    has_tick_count: bool = Field(default=False, description="True if trade/tick count is present")
    quality_warnings: list[str] = Field(
        default_factory=list, description="Diagnostic warnings found during inspection"
    )
    is_valid_replayable: bool = Field(
        ..., description="True if file satisfies minimum bar count and schema requirements"
    )
    underlying_symbols: list[str] = Field(
        default_factory=list,
        description="Root underlying symbols discovered in derivative datasets",
    )
    expiries_found: list[str] = Field(
        default_factory=list, description="Derivative expiration dates discovered"
    )
    option_types: list[str] = Field(
        default_factory=list, description="Option types discovered (e.g. 'CE', 'PE', 'XX')"
    )
    derivative_fields: list[str] = Field(
        default_factory=list, description="Recognized derivative specific fields"
    )
    total_derivative_rows: int | None = Field(
        default=None,
        description="Total derivative observation rows including untraded contracts",
    )
    replay_ineligibility_reason: str | None = Field(
        default=None,
        description="Explanation why dataset cannot be replayed directly in linear paper runner",
    )

    @property
    def is_replayable(self) -> bool:
        """Convenience alias for is_valid_replayable."""
        return self.is_valid_replayable

    @property
    def warnings(self) -> list[str]:
        """Convenience alias for quality_warnings."""
        return self.quality_warnings


def _clean_header(header: str) -> str:
    """Normalize CSV header by stripping BOM, excess whitespace, angle brackets, and lowercase."""
    s = re.sub(r"[\ufeff<>]", "", header)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _extract_underlying_from_filename(filename: str) -> str | None:
    """Attempt to extract root underlying symbol from standard NSE file naming patterns."""
    clean_name = Path(filename).name
    # Pattern 1: Quote-Derivative-RELIANCE-07-03-2026-07-09-2026.csv
    # Pattern 2: Quote-Equity-RELIANCE-07-03-2026-07-09-2026.csv
    m = re.match(
        r"^Quote-(?:Derivative|Equity)-([A-Za-z0-9_&]+)(?:-\d{2}-\d{2}-\d{4}.*)?",
        clean_name,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()
    # Pattern 3: RELIANCE_derivative.csv or RELIANCE-derivatives.csv
    m2 = re.match(
        r"^([A-Za-z0-9_&]+)[_-](?:derivative|derivatives|options|futures)",
        clean_name,
        re.IGNORECASE,
    )
    if m2:
        return m2.group(1).upper()
    return None


def _parse_float(val: Any) -> float | None:
    """Safely convert strings with commas, currency symbols, or null values to float."""
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("₹", "").replace("$", "")
    if not s or s in ("-", "null", "none", "nan", "n/a", "na"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_int(val: Any) -> int | None:
    """Safely convert numerical strings to integer."""
    flt = _parse_float(val)
    if flt is None:
        return None
    try:
        return int(round(flt))
    except (ValueError, OverflowError):
        return None


# Date formats commonly found in NSE feeds and public data vendors
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%d-%b-%y",
    "%d-%B-%y",
    "%d%m%Y",
    "%Y%m%d",
    "%Y/%m/%d",
)

# Time formats commonly found in intraday CSV files
_TIME_FORMATS = (
    "%H:%M:%S",
    "%H:%M",
    "%I:%M:%S %p",
    "%I:%M %p",
    "%H%M%S",
    "%H%M",
)

# Combined datetime formats
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d-%b-%Y %H:%M:%S",
    "%d-%B-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%d-%b-%Y %H:%M",
    "%Y%m%d %H:%M:%S",
    "%Y%m%d %H:%M",
)


def _parse_date_only(s: str) -> date | None:
    """Attempt to parse a date string."""
    clean = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time_only(s: str) -> dt_time | None:
    """Attempt to parse a time string."""
    clean = s.strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(clean, fmt).time()
        except ValueError:
            continue
    return None


def parse_flexible_timestamp(
    ts_str: str,
    time_str: str | None = None,
) -> datetime:
    """
    Parse timestamp string into timezone-aware Asia/Kolkata datetime.

    Handles unified ISO strings, NSE bhavcopy dates ('01-JAN-2024'), and
    split date/time columns ('2024-01-15' + '09:15:00').
    """
    ts_str = ts_str.strip()
    if time_str:
        time_str = time_str.strip()
        combined = f"{ts_str} {time_str}"
        # Try combined formats first
        for fmt in _DATETIME_FORMATS:
            try:
                dt = datetime.strptime(combined, fmt)
                return normalize_to_ist(dt)
            except ValueError:
                continue

        # Fallback: parse separate parts
        d = _parse_date_only(ts_str)
        t = _parse_time_only(time_str)
        if d and t:
            dt = datetime.combine(d, t)
            return normalize_to_ist(dt)

    # If no separate time or combined parsing failed, check if ts_str contains both
    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(ts_str, fmt)
            return normalize_to_ist(dt)
        except ValueError:
            continue

    # Try ISO format
    try:
        dt = datetime.fromisoformat(ts_str)
        return normalize_to_ist(dt)
    except ValueError:
        pass

    # Try date-only formats (default to 09:15:00 market open for daily bars)
    d = _parse_date_only(ts_str)
    if d:
        dt = datetime.combine(d, dt_time(9, 15, 0))
        return normalize_to_ist(dt)

    raise ValueError(f"Could not parse timestamp '{ts_str}' (time='{time_str}')")


class NSECSVParser:
    """
    High-fidelity parser for Indian equity & derivative CSV market data.

    Enforces:
    - Timezone localization to Asia/Kolkata
    - Deduplication of bars with identical timestamps
    - Ascending chronological ordering (anti-lookahead protection)
    - Rejection of invalid price envelopes (high < low, non-positive close)
    """

    @classmethod
    def detect_format(cls, columns_or_path: Sequence[str] | str | Path) -> NSECSVFormat:
        """Classify CSV format based on header column signature or file path."""
        if isinstance(columns_or_path, (str, Path)):
            path = Path(columns_or_path)
            if not path.is_file():
                return NSECSVFormat.UNKNOWN
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as f:
                    sample = f.read(4096)
                    f.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                        delimiter = dialect.delimiter
                    except Exception:
                        delimiter = ","
                    reader = csv.reader(f, delimiter=delimiter)
                    first_row = next(reader, [])
                    cols = {_clean_header(c) for c in first_row if c.strip()}
            except Exception:
                return NSECSVFormat.UNKNOWN
        else:
            cols = {_clean_header(c) for c in columns_or_path if c}

        # NSE Derivative Quote download (Quote-Derivative-*.csv)
        if (
            {"expiry date", "option type", "strike price"}.issubset(cols)
            or {"strike price", "settlement price"}.issubset(cols)
            or {"option type", "settlement price", "change in oi"}.issubset(cols)
        ):
            return NSECSVFormat.DERIVATIVE_QUOTE

        # NSE FO Bhavcopy signature
        if {"instrument", "symbol", "strike_pr", "option_typ"}.issubset(cols) or {
            "instrument",
            "symbol",
            "contracts",
            "open_int",
        }.issubset(cols):
            return NSECSVFormat.FO_BHAVCOPY

        # NSE CM Bhavcopy signature
        if {"symbol", "series", "tottrdqty"}.issubset(cols) or {
            "symbol",
            "series",
            "tottrdval",
        }.issubset(cols):
            return NSECSVFormat.CM_BHAVCOPY

        # NSE Index Historical export
        if (
            {"shares traded", "turnover"}.intersection(cols)
            or "shares traded" in cols
            or any("turnover" in c for c in cols)
        ) and ("date" in cols or "timestamp" in cols):
            return NSECSVFormat.INDEX_HISTORY

        # Intraday 1m/5m data with separate time column
        has_time = any(c in cols for c in ("time", "bar_time", "timestamp_time"))
        has_date = any(c in cols for c in ("date", "bar_date"))
        has_ohlc = {"open", "high", "low", "close"}.issubset(cols)
        if has_time and has_date and has_ohlc:
            return NSECSVFormat.INTRADAY

        # Generic OHLCV
        if has_ohlc and any(c in cols for c in ("timestamp", "datetime", "date", "time")):
            return NSECSVFormat.GENERIC_OHLCV

        return NSECSVFormat.UNKNOWN

    @classmethod
    def parse_file(
        cls,
        file_path: str | Path,
        symbol: str | None = None,
        timeframe: str = "1m",
        session_filter: bool = False,
    ) -> tuple[list[Bar], list[str]]:
        """
        Parse CSV file into canonical Bar objects.

        Returns:
            (bars, warnings)
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Market data CSV not found: {path}")

        with open(path, encoding="utf-8-sig") as f:
            sample = f.read(4096)
            f.seek(0)
            # Detect delimiter
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ","

            reader = csv.reader(f, delimiter=delimiter)
            try:
                raw_header = next(reader)
            except StopIteration:
                return [], ["File is completely empty."]

            header_map = {_clean_header(col): idx for idx, col in enumerate(raw_header) if col}
            csv_format = cls.detect_format(list(header_map.keys()))

            # Reset file pointer to read rows with DictReader
            f.seek(0)
            dict_reader = csv.DictReader(f, delimiter=delimiter)

            bars: list[Bar] = []
            warnings: list[str] = []
            row_idx = 1
            has_seen_out_of_order = False
            last_ts: datetime | None = None

            for raw_row in dict_reader:
                row_idx += 1
                row = {_clean_header(k): v.strip() for k, v in raw_row.items() if k}

                underlying_candidate = _extract_underlying_from_filename(path.name)
                # Extract symbol
                row_symbol = (
                    row.get("symbol")
                    or row.get("ticker")
                    or row.get("scrip")
                    or underlying_candidate
                    or symbol
                    or "UNKNOWN"
                ).strip()

                # Format-specific symbol resolution and filtering
                if csv_format == NSECSVFormat.DERIVATIVE_QUOTE:
                    underlying = (
                        (
                            row.get("symbol")
                            or row.get("underlying")
                            or underlying_candidate
                            or (
                                symbol
                                if symbol
                                and not any(k in symbol.upper() for k in (" CE ", " PE ", " FUT"))
                                else None
                            )
                            or "UNKNOWN"
                        )
                        .strip()
                        .upper()
                    )

                    opt_typ_raw = row.get("option type", "").strip().upper()
                    strike_raw = row.get("strike price", "").strip()
                    expiry_raw = row.get("expiry date", "").strip()

                    if opt_typ_raw in ("CE", "CALL"):
                        opt_typ = "CE"
                    elif opt_typ_raw in ("PE", "PUT"):
                        opt_typ = "PE"
                    elif opt_typ_raw in ("XX", "FUT", "FUTURES", "-"):
                        opt_typ = "XX"
                    else:
                        warnings.append(f"Row {row_idx}: Invalid option type '{opt_typ_raw}'.")
                        continue

                    if opt_typ in ("CE", "PE"):
                        strike_val = _parse_float(strike_raw)
                        if strike_val is None or strike_val <= 0:
                            warnings.append(
                                f"Row {row_idx}: Missing or malformed strike price '{strike_raw}' for option type {opt_typ}."
                            )
                            continue
                        strike_str = f"{strike_val:g}"
                        row_symbol = f"{underlying} {expiry_raw} {opt_typ} {strike_str}"
                    else:
                        row_symbol = f"{underlying} {expiry_raw} FUT"

                    if symbol:
                        clean_target = symbol.strip().upper()
                        if (
                            clean_target != underlying
                            and clean_target != row_symbol.upper()
                            and clean_target not in row_symbol.upper()
                        ):
                            continue

                elif csv_format == NSECSVFormat.CM_BHAVCOPY:
                    # By default accept 'EQ' series if series column exists
                    series = row.get("series", "EQ").strip()
                    if series not in ("EQ", "") and symbol and symbol != row_symbol:
                        continue
                    if symbol and row_symbol.upper() != symbol.upper():
                        continue
                elif csv_format == NSECSVFormat.FO_BHAVCOPY:
                    # Construct composite symbol if available (e.g., NIFTY24DEC24000CE)
                    strike = row.get("strike_pr", "").strip()
                    opt_typ = row.get("option_typ", "").strip()
                    if strike and opt_typ and opt_typ != "XX":
                        composite = f"{row_symbol}{strike}{opt_typ}"
                        if symbol and symbol.upper() not in (row_symbol.upper(), composite.upper()):
                            continue
                        row_symbol = composite
                    elif symbol and row_symbol.upper() != symbol.upper():
                        continue
                else:
                    if symbol and row_symbol.upper() != symbol.upper():
                        continue

                # Extract timestamp
                ts_raw = (
                    row.get("timestamp")
                    or row.get("datetime")
                    or row.get("date")
                    or row.get("<date>")
                )
                time_raw = row.get("time") or row.get("bar_time") or row.get("<time>")

                if not ts_raw:
                    warnings.append(f"Row {row_idx}: Missing timestamp/date column.")
                    continue

                try:
                    ts = parse_flexible_timestamp(ts_raw, time_raw)
                except Exception as exc:
                    warnings.append(f"Row {row_idx}: Failed to parse timestamp '{ts_raw}' ({exc}).")
                    continue

                if session_filter and not is_market_open(ts):
                    continue

                # Parse OHLC
                o_val = _parse_float(row.get("open price") or row.get("open") or row.get("<open>"))
                h_val = _parse_float(row.get("high price") or row.get("high") or row.get("<high>"))
                l_val = _parse_float(row.get("low price") or row.get("low") or row.get("<low>"))
                c_val = _parse_float(
                    row.get("close price") or row.get("close") or row.get("<close>")
                )

                if (
                    csv_format == NSECSVFormat.DERIVATIVE_QUOTE
                    and o_val is None
                    and h_val is None
                    and l_val is None
                ):
                    # Benign untraded derivative contract on this date
                    continue

                if o_val is None or h_val is None or l_val is None or c_val is None:
                    warnings.append(f"Row {row_idx}: Missing or invalid OHLC prices.")
                    continue

                if o_val <= 0 or h_val <= 0 or l_val <= 0 or c_val <= 0:
                    warnings.append(f"Row {row_idx}: Non-positive OHLC price encountered.")
                    continue

                if h_val < l_val or h_val < max(o_val, c_val) or l_val > min(o_val, c_val):
                    warnings.append(
                        f"Row {row_idx} ({ts.isoformat()}): Invalid OHLC price envelope "
                        f"O={o_val} H={h_val} L={l_val} C={c_val}."
                    )
                    continue

                # Volume resolution
                vol_val = (
                    _parse_int(row.get("volume"))
                    or _parse_int(row.get("vol"))
                    or _parse_int(row.get("<vol>"))
                    or _parse_int(row.get("tottrdqty"))
                    or _parse_int(row.get("contracts"))
                    or _parse_int(row.get("shares traded"))
                    or 0
                )
                vol_raw = row.get("volume") or row.get("vol")
                if (
                    vol_raw is not None
                    and vol_raw.strip()
                    and vol_raw.strip() not in ("-", "null", "none")
                ):
                    vol_num = _parse_float(vol_raw)
                    if vol_num is not None and vol_num < 0:
                        warnings.append(f"Row {row_idx}: Negative volume encountered: {vol_raw}.")
                        continue

                # Open Interest resolution
                oi_val = (
                    _parse_int(row.get("oi"))
                    or _parse_int(row.get("open_int"))
                    or _parse_int(row.get("open interest"))
                    or _parse_int(row.get("open_interest"))
                    or 0
                )
                oi_raw = row.get("open interest") or row.get("open_int") or row.get("oi")
                if (
                    oi_raw is not None
                    and oi_raw.strip()
                    and oi_raw.strip() not in ("-", "null", "none")
                ):
                    oi_num = _parse_float(oi_raw)
                    if oi_num is not None and oi_num < 0:
                        warnings.append(
                            f"Row {row_idx}: Negative open interest encountered: {oi_raw}."
                        )
                        continue

                # Tick Count resolution
                tc_val = (
                    _parse_int(row.get("tick_count"))
                    or _parse_int(row.get("ticks"))
                    or _parse_int(row.get("totaltrades"))
                    or _parse_int(row.get("no_of_trades"))
                )

                # VWAP resolution
                vwap_val = _parse_float(row.get("vwap"))
                if vwap_val is None and vol_val > 0:
                    if csv_format == NSECSVFormat.DERIVATIVE_QUOTE:
                        prem_val = _parse_float(
                            row.get("premium value (₹ lakhs)") or row.get("premium value")
                        )
                        val_lakhs = _parse_float(row.get("value (₹ lakhs)") or row.get("value"))
                        opt_typ_check = row.get("option type", "").strip().upper()
                        if (
                            opt_typ_check in ("CE", "PE", "CALL", "PUT")
                            and prem_val is not None
                            and prem_val > 0
                        ):
                            candidate = prem_val / vol_val
                            if l_val <= candidate <= h_val:
                                vwap_val = round(candidate, 4)
                        elif opt_typ_check in ("XX", "FUT", "FUTURES", "-") and (
                            val_lakhs is not None or prem_val is not None
                        ):
                            turnover = (
                                val_lakhs if val_lakhs is not None and val_lakhs > 0 else prem_val
                            )
                            if turnover is not None and turnover > 0:
                                candidate = turnover / vol_val
                                if l_val <= candidate <= h_val:
                                    vwap_val = round(candidate, 4)
                    else:
                        tottrdval = _parse_float(row.get("tottrdval"))
                        if tottrdval is not None and tottrdval > 0:
                            candidate = tottrdval / vol_val
                            if l_val <= candidate <= h_val:
                                vwap_val = round(candidate, 2)

                # Monotonic ordering check
                if (
                    csv_format != NSECSVFormat.DERIVATIVE_QUOTE
                    and last_ts is not None
                    and ts < last_ts
                ):
                    has_seen_out_of_order = True
                last_ts = ts

                bar = Bar(
                    timestamp=ts,
                    open=round(o_val, 4),
                    high=round(h_val, 4),
                    low=round(l_val, 4),
                    close=round(c_val, 4),
                    volume=max(0, vol_val),
                    oi=max(0, oi_val) if oi_val is not None else 0,
                    symbol=row_symbol,
                    vwap=round(vwap_val, 4) if vwap_val is not None and vwap_val > 0 else None,
                    tick_count=tc_val if tc_val is not None and tc_val >= 0 else None,
                    source=(
                        "NSE_DERIVATIVE_QUOTE"
                        if csv_format == NSECSVFormat.DERIVATIVE_QUOTE
                        else "CSV_HISTORICAL"
                    ),
                    timeframe=timeframe,
                    is_synthetic=False,
                )
                bars.append(bar)

        if has_seen_out_of_order:
            warnings.append("Dataset contained out-of-order timestamps; chronologically sorted.")

        # Strict ascending sort by timestamp, then symbol
        bars.sort(key=lambda b: (b.timestamp, b.symbol or ""))

        # Deduplication using composite key (symbol, timestamp)
        deduped: list[Bar] = []
        seen_keys: set[tuple[str | None, datetime]] = set()
        duplicate_count = 0
        for b in bars:
            key = (b.symbol, b.timestamp)
            if key not in seen_keys:
                deduped.append(b)
                seen_keys.add(key)
            else:
                duplicate_count += 1

        if duplicate_count > 0:
            warnings.append(f"Deduplicated {duplicate_count} bars with duplicate timestamps.")

        return deduped, warnings

    @classmethod
    def parse_derivative_quotes(
        cls,
        file_path: str | Path,
        symbol: str | None = None,
    ) -> tuple[list[DerivativeQuoteRecord], list[str]]:
        """
        Parse NSE derivative quote CSV into canonical DerivativeQuoteRecord objects.

        Faithfully normalizes all 15 official NSE columns:
        Date, Expiry Date, Option Type, Strike Price, Open Price, High Price, Low Price,
        Close Price, Last Price, Settlement Price, Volume, Value, Premium Value,
        Open Interest, Change in OI.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Market data CSV not found: {path}")

        extracted_underlying = _extract_underlying_from_filename(path.name)

        with open(path, encoding="utf-8-sig", errors="replace") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ","

            f.seek(0)
            dict_reader = csv.DictReader(f, delimiter=delimiter)

            records: list[DerivativeQuoteRecord] = []
            warnings: list[str] = []
            row_idx = 1

            for raw_row in dict_reader:
                row_idx += 1
                row = {_clean_header(k): v.strip() for k, v in raw_row.items() if k}

                underlying = (
                    (
                        row.get("symbol")
                        or row.get("underlying")
                        or extracted_underlying
                        or (
                            symbol
                            if symbol
                            and not any(k in symbol.upper() for k in (" CE ", " PE ", " FUT"))
                            else None
                        )
                        or "UNKNOWN"
                    )
                    .strip()
                    .upper()
                )

                opt_typ_raw = row.get("option type", "").strip().upper()
                if opt_typ_raw in ("CE", "CALL"):
                    opt_typ: Literal["CE", "PE", "XX"] = "CE"
                elif opt_typ_raw in ("PE", "PUT"):
                    opt_typ = "PE"
                elif opt_typ_raw in ("XX", "FUT", "FUTURES", "-"):
                    opt_typ = "XX"
                else:
                    warnings.append(f"Row {row_idx}: Invalid option type '{opt_typ_raw}'.")
                    continue

                expiry_raw = row.get("expiry date", "").strip()
                exp_date = _parse_date_only(expiry_raw)
                if exp_date is None:
                    warnings.append(f"Row {row_idx}: Failed to parse expiry date '{expiry_raw}'.")
                    continue

                strike_raw = row.get("strike price", "").strip()
                strike_val: float | None = None
                if opt_typ in ("CE", "PE"):
                    strike_val = _parse_float(strike_raw)
                    if strike_val is None or strike_val <= 0:
                        warnings.append(
                            f"Row {row_idx}: Missing or malformed strike price '{strike_raw}' for option type {opt_typ}."
                        )
                        continue
                    strike_str = f"{strike_val:g}"
                    trading_symbol = f"{underlying} {expiry_raw} {opt_typ} {strike_str}"
                else:
                    trading_symbol = f"{underlying} {expiry_raw} FUT"

                # Symbol filtering if target symbol was requested
                if symbol:
                    clean_target = symbol.strip().upper()
                    if (
                        clean_target != underlying
                        and clean_target != trading_symbol.upper()
                        and clean_target not in trading_symbol.upper()
                    ):
                        continue

                date_raw = row.get("date", "").strip()
                if not date_raw:
                    warnings.append(f"Row {row_idx}: Missing observation date.")
                    continue

                try:
                    ts = parse_flexible_timestamp(date_raw)
                except Exception as exc:
                    warnings.append(
                        f"Row {row_idx}: Failed to parse observation date '{date_raw}' ({exc})."
                    )
                    continue

                o_val = _parse_float(row.get("open price") or row.get("open"))
                h_val = _parse_float(row.get("high price") or row.get("high"))
                l_val = _parse_float(row.get("low price") or row.get("low"))
                c_val = _parse_float(row.get("close price") or row.get("close"))
                ltp_val = _parse_float(row.get("last price") or row.get("ltp"))
                settle_val = _parse_float(row.get("settlement price"))

                # Envelope check when fully traded
                if (
                    o_val is not None
                    and h_val is not None
                    and l_val is not None
                    and c_val is not None
                ):
                    if o_val <= 0 or h_val <= 0 or l_val <= 0 or c_val <= 0:
                        warnings.append(f"Row {row_idx}: Non-positive OHLC price encountered.")
                        continue
                    if h_val < l_val or h_val < max(o_val, c_val) or l_val > min(o_val, c_val):
                        warnings.append(
                            f"Row {row_idx} ({ts.isoformat()}): Invalid OHLC price envelope "
                            f"O={o_val} H={h_val} L={l_val} C={c_val}."
                        )
                        continue
                elif o_val is not None or h_val is not None or l_val is not None:
                    warnings.append(f"Row {row_idx}: Incomplete OHLC prices on traded contract.")
                    continue

                # Volume check
                vol_val = _parse_int(row.get("volume")) or 0
                vol_num = _parse_float(row.get("volume"))
                if vol_num is not None and vol_num < 0:
                    warnings.append(
                        f"Row {row_idx}: Negative volume encountered: {row.get('volume')}."
                    )
                    continue

                # Open interest check
                oi_val = _parse_int(row.get("open interest"))
                oi_num = _parse_float(row.get("open interest"))
                if oi_num is not None and oi_num < 0:
                    warnings.append(
                        f"Row {row_idx}: Negative open interest encountered: {row.get('open interest')}."
                    )
                    continue

                chg_oi_val = _parse_int(row.get("change in oi"))

                # Turnover values
                val_lakhs = _parse_float(row.get("value (₹ lakhs)") or row.get("value"))
                prem_val_lakhs = _parse_float(
                    row.get("premium value (₹ lakhs)") or row.get("premium value")
                )

                # Authentic VWAP calculation
                vwap_val: float | None = None
                if vol_val > 0:
                    if (
                        opt_typ in ("CE", "PE")
                        and prem_val_lakhs is not None
                        and prem_val_lakhs > 0
                    ):
                        candidate = prem_val_lakhs / vol_val
                        if l_val is not None and h_val is not None and l_val <= candidate <= h_val:
                            vwap_val = round(candidate, 4)
                    elif opt_typ == "XX" and (val_lakhs is not None or prem_val_lakhs is not None):
                        turnover = (
                            val_lakhs if val_lakhs is not None and val_lakhs > 0 else prem_val_lakhs
                        )
                        if turnover is not None and turnover > 0:
                            candidate = turnover / vol_val
                            if (
                                l_val is not None
                                and h_val is not None
                                and l_val <= candidate <= h_val
                            ):
                                vwap_val = round(candidate, 4)

                try:
                    record = DerivativeQuoteRecord(
                        timestamp=ts,
                        symbol=underlying,
                        trading_symbol=trading_symbol,
                        expiry_date=exp_date,
                        option_type=opt_typ,
                        strike_price=strike_val,
                        open=round(o_val, 4) if o_val is not None else None,
                        high=round(h_val, 4) if h_val is not None else None,
                        low=round(l_val, 4) if l_val is not None else None,
                        close=round(c_val, 4) if c_val is not None else None,
                        last_price=round(ltp_val, 4) if ltp_val is not None else None,
                        settlement_price=round(settle_val, 4) if settle_val is not None else None,
                        volume=max(0, vol_val),
                        value_lakhs=val_lakhs,
                        premium_value_lakhs=prem_val_lakhs,
                        oi=max(0, oi_val) if oi_val is not None else None,
                        change_in_oi=chg_oi_val,
                        vwap=vwap_val,
                        source="NSE_DERIVATIVE_QUOTE",
                    )
                    records.append(record)
                except Exception as exc:
                    warnings.append(f"Row {row_idx}: Validation error ({exc}).")

            # Sort ascending chronologically, then by contract trading symbol
            records.sort(key=lambda r: (r.timestamp, r.trading_symbol))
            return records, warnings


class NSECSVInspector:
    """Analyzes and validates CSV files before simulation or forward replay."""

    @classmethod
    def inspect_file(
        cls,
        file_path: str | Path,
        target_symbol: str | None = None,
    ) -> CSVInspectionReport:
        """
        Inspect a CSV file and construct a diagnostic report.

        Never alters the dataset. Provides operators with full visibility into
        format, columns, date ranges, and quality anomalies.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Market data file not found: {path}")

        file_size = path.stat().st_size
        if file_size == 0:
            return CSVInspectionReport(
                file_path=str(path),
                file_size_bytes=0,
                detected_format=NSECSVFormat.UNKNOWN,
                total_lines=0,
                parsed_bars=0,
                symbols=[],
                timeframe_detected="unknown",
                columns_found=[],
                quality_warnings=["File is 0 bytes."],
                is_valid_replayable=False,
            )

        # Read header and total lines
        total_lines = 0
        header_cols: list[str] = []
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for line_idx, line in enumerate(f):
                total_lines += 1
                if line_idx == 0:
                    # Parse header
                    row = next(csv.reader(io.StringIO(line)))
                    header_cols = [_clean_header(c) for c in row if c.strip()]

        detected_fmt = NSECSVParser.detect_format(header_cols)

        underlying_symbols: list[str] = []
        expiries_found: list[str] = []
        option_types: list[str] = []
        derivative_fields: list[str] = []
        total_derivative_rows: int | None = None
        replay_ineligibility_reason: str | None = None
        bars: list[Bar] = []
        warnings: list[str] = []

        if detected_fmt == NSECSVFormat.DERIVATIVE_QUOTE:
            quotes, warnings = NSECSVParser.parse_derivative_quotes(path, symbol=target_symbol)

            total_derivative_rows = len(quotes)
            parsed_bars_count = sum(
                1
                for q in quotes
                if q.open is not None
                and q.high is not None
                and q.low is not None
                and q.close is not None
            )
            underlying_symbols = sorted(list({q.symbol for q in quotes}))
            unique_expiries = {q.expiry_date for q in quotes}
            expiries_found = [d.strftime("%d-%b-%Y") for d in sorted(unique_expiries)]
            option_types = sorted(list({q.option_type for q in quotes}))
            derivative_field_candidates = [
                "expiry date",
                "option type",
                "strike price",
                "last price",
                "settlement price",
                "premium value (₹ lakhs)",
                "change in oi",
                "value (₹ lakhs)",
            ]
            derivative_fields = [c for c in header_cols if c in derivative_field_candidates]

            has_volume = any(q.volume > 0 for q in quotes)
            has_oi = any((q.oi or 0) > 0 for q in quotes)
            has_vwap = any(q.vwap is not None for q in quotes)
            has_tc = False

            # Derivative datasets contain multi-contract quotes across expiries and strikes;
            # options trading execution is strictly air-gapped per ADR 011 and ADR 002.
            is_replayable = False
            replay_ineligibility_reason = (
                "Daily derivative quotes contain multi-expiry/strike contracts; "
                "options execution is air-gapped per ADR 011 and ADR 002."
            )
            start_time_iso = quotes[0].timestamp.isoformat() if quotes else None
            end_time_iso = quotes[-1].timestamp.isoformat() if quotes else None
            timeframe_detected = "1d"
            symbols_found = sorted(list({q.trading_symbol for q in quotes}))
            parsed_bars = parsed_bars_count
        else:
            bars, warnings = NSECSVParser.parse_file(
                path,
                symbol=target_symbol,
                timeframe="1m" if detected_fmt == NSECSVFormat.INTRADAY else "1d",
                session_filter=False,
            )
            symbols_found = sorted(list({str(b.symbol) for b in bars if b.symbol is not None}))
            has_volume = any(b.volume > 0 for b in bars)
            has_oi = any((b.oi or 0) > 0 for b in bars)
            has_vwap = any(b.vwap is not None for b in bars)
            has_tc = any(b.tick_count is not None for b in bars)
            parsed_bars = len(bars)
            has_vwap = any(b.vwap is not None for b in bars)
            has_tc = any(b.tick_count is not None for b in bars)

            # Infer timeframe if intraday
            timeframe_detected = "1d"
            if detected_fmt == NSECSVFormat.INTRADAY and len(bars) >= 2:
                # Measure median delta between first few consecutive bars on the same day
                deltas: list[float] = []
                for i in range(min(50, len(bars) - 1)):
                    if bars[i].timestamp.date() == bars[i + 1].timestamp.date():
                        dt_sec = (bars[i + 1].timestamp - bars[i].timestamp).total_seconds()
                        if 0 < dt_sec <= 86400:
                            deltas.append(dt_sec)
                if deltas:
                    deltas.sort()
                    median_sec = deltas[len(deltas) // 2]
                    if 55 <= median_sec <= 65:
                        timeframe_detected = "1m"
                    elif 290 <= median_sec <= 310:
                        timeframe_detected = "5m"
                    elif 890 <= median_sec <= 910:
                        timeframe_detected = "15m"
                    elif 3500 <= median_sec <= 3700:
                        timeframe_detected = "1h"
                    else:
                        timeframe_detected = f"{int(median_sec)}s"

            start_time_iso = bars[0].timestamp.isoformat() if bars else None
            end_time_iso = bars[-1].timestamp.isoformat() if bars else None
            is_replayable = len(bars) > 0 and detected_fmt != NSECSVFormat.UNKNOWN

        return CSVInspectionReport(
            file_path=str(path),
            file_size_bytes=file_size,
            detected_format=detected_fmt,
            total_lines=total_lines,
            parsed_bars=parsed_bars,
            symbols=symbols_found,
            timeframe_detected=timeframe_detected,
            start_time=start_time_iso,
            end_time=end_time_iso,
            columns_found=header_cols,
            has_volume=has_volume,
            has_oi=has_oi,
            has_vwap=has_vwap,
            has_tick_count=has_tc,
            quality_warnings=warnings,
            is_valid_replayable=is_replayable,
            underlying_symbols=underlying_symbols,
            expiries_found=expiries_found,
            option_types=option_types,
            derivative_fields=derivative_fields,
            total_derivative_rows=total_derivative_rows,
            replay_ineligibility_reason=replay_ineligibility_reason,
        )
