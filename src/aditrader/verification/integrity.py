"""Dataset and market-data stream integrity auditing engine.

Enforces:
- Physical OHLC price envelope invariants (low <= open, close <= high)
- Strictly positive prices and non-negative volume/OI
- Chronological monotonicity and duplicate timestamp detection
- Continuous NSE session gap detection (09:15 to 15:30 IST, continuous, no lunch break)
- Differentiated validation for liquid linear series vs illiquid option contract strikes
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.market_data import Bar
from aditrader.data.feeds.nse_csv import NSECSVFormat, NSECSVInspector, NSECSVParser
from aditrader.data.session import EXCHANGE_TIMEZONE


class TimestampGap(BaseModel):
    """Information on an unexpected intraday market data gap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_timestamp: str
    end_timestamp: str
    gap_duration_seconds: float
    expected_interval_seconds: float
    missing_bars_count: int
    note: str


class DataIntegrityReport(BaseModel):
    """Comprehensive diagnostic data integrity report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_identifier: str
    total_records: int = Field(ge=0)
    valid_records: int = Field(ge=0)
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    gaps: list[TimestampGap] = Field(default_factory=list)
    duplicates_count: int = Field(default=0, ge=0)
    envelope_violations_count: int = Field(default=0, ge=0)
    negative_price_count: int = Field(default=0, ge=0)
    crossed_quotes_count: int = Field(default=0, ge=0)
    timezone_violations_count: int = Field(default=0, ge=0)
    details: str = Field(default="")


class DataIntegrityChecker:
    """Audits CSV files and bar collections against institutional integrity standards."""

    @classmethod
    def audit_csv_file(
        cls,
        csv_path: str | Path,
        *,
        expected_timeframe_minutes: int | None = None,
        is_options_dataset: bool = False,
    ) -> DataIntegrityReport:
        """Audit a historical CSV dataset file on disk."""
        p = Path(csv_path)
        if not p.is_file():
            return DataIntegrityReport(
                source_identifier=str(p),
                total_records=0,
                valid_records=0,
                is_valid=False,
                errors=[f"Dataset file not found: {p}"],
                details="File does not exist on disk",
            )

        try:
            inspector_rep = NSECSVInspector.inspect_file(p)
            detected_format = inspector_rep.detected_format
            is_opt = is_options_dataset or (detected_format == NSECSVFormat.DERIVATIVE_QUOTE)

            bars, errs = NSECSVParser.parse_file(p)
            if not bars:
                return DataIntegrityReport(
                    source_identifier=p.name,
                    total_records=0,
                    valid_records=0,
                    is_valid=False,
                    errors=errs or ["Failed to parse any valid OHLCV bars from CSV."],
                    details="Zero valid bars parsed",
                )

            # Resolve expected interval
            interval_min = expected_timeframe_minutes
            if interval_min is None:
                tf_str = inspector_rep.timeframe_detected or "1m"
                if tf_str.endswith("m"):
                    try:
                        interval_min = int(tf_str[:-1])
                    except ValueError:
                        interval_min = 1
                else:
                    interval_min = None

            return cls.audit_bars(
                bars=bars,
                source_identifier=p.name,
                expected_interval_minutes=interval_min,
                is_options_dataset=is_opt,
                initial_errors=errs,
            )
        except Exception as exc:
            return DataIntegrityReport(
                source_identifier=p.name,
                total_records=0,
                valid_records=0,
                is_valid=False,
                errors=[f"Integrity audit crashed with exception: {exc}"],
                details=f"Unexpected failure during inspection: {exc}",
            )

    @classmethod
    def audit_bars(
        cls,
        bars: list[Bar],
        *,
        source_identifier: str = "in_memory_bars",
        expected_interval_minutes: int | None = None,
        is_options_dataset: bool = False,
        initial_errors: list[str] | None = None,
    ) -> DataIntegrityReport:
        """Audit an in-memory list of Bar objects for envelope, timestamp, and gap consistency."""
        errors: list[str] = list(initial_errors or [])
        warnings: list[str] = []
        gaps: list[TimestampGap] = []

        duplicates = 0
        envelope_violations = 0
        negative_prices = 0
        crossed_quotes = 0
        tz_violations = 0

        if not bars:
            return DataIntegrityReport(
                source_identifier=source_identifier,
                total_records=0,
                valid_records=0,
                is_valid=False,
                errors=["Bar sequence is empty"],
                details="No bars provided",
            )

        seen_keys: set[tuple[str, datetime]] = set()
        prev_bar_by_symbol: dict[str, Bar] = {}

        expected_delta = (
            timedelta(minutes=expected_interval_minutes)
            if expected_interval_minutes and expected_interval_minutes > 0
            else None
        )

        for idx, bar in enumerate(bars):
            sym = bar.symbol or "PRIMARY"

            # 1. Price envelope checks
            if bar.open <= 0.0 or bar.high <= 0.0 or bar.low <= 0.0 or bar.close <= 0.0:
                negative_prices += 1
                errors.append(
                    f"Bar #{idx} ({bar.timestamp}) contains non-positive price: O={bar.open}, H={bar.high}, L={bar.low}, C={bar.close}"
                )

            if bar.high < bar.low:
                envelope_violations += 1
                errors.append(f"Bar #{idx} ({bar.timestamp}) High ({bar.high}) < Low ({bar.low})")

            if bar.high < max(bar.open, bar.close):
                envelope_violations += 1
                errors.append(f"Bar #{idx} ({bar.timestamp}) High ({bar.high}) < max(Open, Close)")

            if bar.low > min(bar.open, bar.close):
                envelope_violations += 1
                errors.append(f"Bar #{idx} ({bar.timestamp}) Low ({bar.low}) > min(Open, Close)")

            # 2. Timezone and Session verification
            if bar.timestamp.tzinfo is None:
                tz_violations += 1
                errors.append(
                    f"Bar #{idx} timestamp {bar.timestamp} is timezone-naive (must be Asia/Kolkata)"
                )
            else:
                bar_ist = bar.timestamp.astimezone(EXCHANGE_TIMEZONE)
                bar_time = bar_ist.time()
                # Continuous NSE regular session: 09:15 to 15:30 IST
                if not (time(9, 15) <= bar_time <= time(15, 30)):
                    warnings.append(
                        f"Bar #{idx} ({sym}) timestamp {bar_ist.strftime('%H:%M:%S')} is outside regular NSE session (09:15-15:30 IST)"
                    )
                if bar_ist.weekday() >= 5:
                    warnings.append(
                        f"Bar #{idx} ({sym}) falls on weekend: {bar_ist.strftime('%A %Y-%m-%d')}"
                    )

            # 3. Volume / OI
            if bar.volume < 0:
                errors.append(f"Bar #{idx} ({bar.timestamp}) volume negative: {bar.volume}")
            if bar.oi < 0:
                errors.append(f"Bar #{idx} ({bar.timestamp}) OI negative: {bar.oi}")

            # 4. Monotonicity & Duplicates (strictly scoped by contract symbol)
            sym_key = (sym, bar.timestamp)
            if sym_key in seen_keys:
                duplicates += 1
                errors.append(
                    f"Bar #{idx} duplicate timestamp detected for {sym_key[0]}: {bar.timestamp}"
                )
            else:
                seen_keys.add(sym_key)

            prev_bar = prev_bar_by_symbol.get(sym)
            if prev_bar is not None:
                if bar.timestamp < prev_bar.timestamp:
                    errors.append(
                        f"Bar #{idx} ({sym}) chronological monotonicity violation: {bar.timestamp} preceded {prev_bar.timestamp}"
                    )
                elif expected_delta and not is_options_dataset:
                    # Check intraday gap within the SAME regular trading session (09:15 to 15:30 IST)
                    t1 = prev_bar.timestamp.astimezone(EXCHANGE_TIMEZONE)
                    t2 = bar.timestamp.astimezone(EXCHANGE_TIMEZONE)

                    if t1.date() == t2.date():
                        # Both bars on same date
                        delta_t = t2 - t1
                        # If delta is more than 1.5x the expected interval, a bar was dropped
                        if delta_t > expected_delta * 1.5:
                            missing_count = (
                                round(delta_t.total_seconds() / expected_delta.total_seconds()) - 1
                            )
                            gaps.append(
                                TimestampGap(
                                    start_timestamp=t1.isoformat(),
                                    end_timestamp=t2.isoformat(),
                                    gap_duration_seconds=delta_t.total_seconds(),
                                    expected_interval_seconds=expected_delta.total_seconds(),
                                    missing_bars_count=missing_count,
                                    note=f"Intraday continuous session gap on {t1.date()}",
                                )
                            )
                            warnings.append(
                                f"Intraday data gap on {t1.date()} between {t1.strftime('%H:%M:%S')} and {t2.strftime('%H:%M:%S')} ({missing_count} missing bars)"
                            )

            prev_bar_by_symbol[sym] = bar

        is_valid = (
            len(errors) == 0
            and duplicates == 0
            and envelope_violations == 0
            and negative_prices == 0
            and tz_violations == 0
        )

        valid_count = len(bars) - envelope_violations - negative_prices - duplicates

        details = (
            f"Audited {len(bars)} bars: all envelope, timestamp, and pricing checks passed."
            if is_valid
            else f"Integrity check failed: {len(errors)} critical violations, {envelope_violations} envelope errors, {duplicates} duplicates."
        )

        return DataIntegrityReport(
            source_identifier=source_identifier,
            total_records=len(bars),
            valid_records=max(0, valid_count),
            is_valid=is_valid,
            errors=errors[:50],  # cap diagnostic output to avoid unbounded lists
            warnings=warnings[:50],
            gaps=gaps[:50],
            duplicates_count=duplicates,
            envelope_violations_count=envelope_violations,
            negative_price_count=negative_prices,
            crossed_quotes_count=crossed_quotes,
            timezone_violations_count=tz_violations,
            details=details,
        )
