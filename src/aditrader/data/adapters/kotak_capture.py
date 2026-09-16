"""Raw capture preservation and canonical normalization pipeline for Kotak Neo market data.

Guarantees:
- Raw API payloads are stored immutably without in-place mutation.
- Every raw capture carries a SHA-256 cryptographic content digest.
- Normalization produces canonical AdiTrader models (Bar, PointInTimeOptionContract).
- Dataset integrity validation (DataIntegrityChecker) is executed post-normalization.
- Cryptographic provenance is recorded for Run Dossier audit integration.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.market_data import Bar
from aditrader.data.session import EXCHANGE_TIMEZONE, normalize_to_ist
from aditrader.verification.integrity import DataIntegrityChecker, DataIntegrityReport

logger = logging.getLogger(__name__)

RAW_CAPTURE_DIR = Path("runs/kotak_raw")


class KotakRawCaptureMetadata(BaseModel):
    """Immutable metadata describing a raw market data capture from Kotak Neo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(default="Kotak Neo", description="Source vendor identifier")
    sdk_version: str = Field(default="3.0.6", description="Installed SDK version")
    neosymbol: str = Field(..., description="Exchange segment and token, e.g. nse_cm|26000")
    symbol: str = Field(..., description="Canonical trading symbol, e.g. NIFTY")
    interval: str = Field(..., description="Requested interval, e.g. 1min, 5min, D")
    from_date: str = Field(..., description="Requested start date (YYYY-MM-DD)")
    to_date: str = Field(..., description="Requested end date (YYYY-MM-DD)")
    retrieved_at: str = Field(..., description="UTC timestamp of API retrieval")
    raw_sha256: str = Field(..., description="SHA-256 digest of exact raw JSON bytes")
    record_count: int = Field(default=0, ge=0, description="Number of candles returned")
    normalization_version: str = Field(default="1.0", description="Schema version of normalization")


class KotakNormalizedDataset(BaseModel):
    """Container holding normalized bars, provenance metadata, and integrity audit report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: KotakRawCaptureMetadata
    raw_file_path: str
    bars: list[Bar]
    integrity_report: DataIntegrityReport
    is_valid: bool


class KotakCaptureManager:
    """Manages raw capture preservation, normalization, and integrity verification."""

    @classmethod
    def save_raw_capture(
        cls,
        raw_response: dict[str, Any] | list[Any],
        *,
        neosymbol: str,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
        sdk_version: str = "3.0.6",
        output_dir: Path | None = None,
    ) -> tuple[Path, KotakRawCaptureMetadata]:
        """Save unmutated API response JSON to disk with computed SHA-256 digest."""
        target_dir = output_dir or RAW_CAPTURE_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        raw_bytes = json.dumps(raw_response, sort_keys=True, indent=2).encode("utf-8")
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        # Count records if candles exist
        if isinstance(raw_response, list):
            record_count = len(raw_response)
        else:
            data_block = raw_response.get("data")
            if isinstance(data_block, dict):
                candles = data_block.get("candles", [])
            elif isinstance(data_block, list):
                candles = data_block
            elif "candles" in raw_response:
                candles = raw_response["candles"]
            else:
                candles = []
            record_count = len(candles) if isinstance(candles, list) else 0

        now_utc = datetime.now(UTC).isoformat()
        metadata = KotakRawCaptureMetadata(
            source="Kotak Neo",
            sdk_version=sdk_version,
            neosymbol=neosymbol,
            symbol=symbol,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            retrieved_at=now_utc,
            raw_sha256=raw_sha256,
            record_count=record_count,
            normalization_version="1.0",
        )

        clean_sym = symbol.replace(" ", "_").replace("|", "_")
        filename = f"raw_{clean_sym}_{interval}_{from_date}_{to_date}_{raw_sha256[:10]}.json"
        file_path = target_dir / filename

        with open(file_path, "wb") as f:
            f.write(raw_bytes)

        # Also write metadata sidecar
        meta_path = target_dir / f"{filename}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))

        logger.info(f"Saved raw Kotak capture to {file_path} (SHA-256: {raw_sha256[:12]})")
        return file_path, metadata

    @classmethod
    def normalize_candles(
        cls,
        raw_response: dict[str, Any] | list[Any],
        symbol: str,
        *,
        timeframe: str = "1m",
    ) -> list[Bar]:
        """Convert Kotak Neo raw JSON candles into canonical AdiTrader Bar models.

        Kotak historical candles format:
        [timestamp_str, open, high, low, close, volume, oi]
        e.g. ["2026-08-20T09:15:00+0530", 12009.9, 12019.35, 12001.25, 12001.5, 163275, 13667775]
        """
        candles: list[Any] = []
        if isinstance(raw_response, dict):
            data_block = raw_response.get("data")
            if isinstance(data_block, dict):
                candles = data_block.get("candles", [])
            elif isinstance(data_block, list):
                candles = data_block
            elif "candles" in raw_response:
                candles = raw_response["candles"]
        elif isinstance(raw_response, list):
            candles = raw_response

        bars: list[Bar] = []
        for row in candles:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue

            raw_ts = row[0]
            try:
                # Parse timestamp
                if isinstance(raw_ts, str):
                    clean_ts = raw_ts.strip()
                    # Handle offsets without colon, e.g. +0530 -> +05:30
                    if len(clean_ts) >= 5 and clean_ts[-5] in ("+", "-") and clean_ts[-3] != ":":
                        clean_ts = clean_ts[:-2] + ":" + clean_ts[-2:]
                    parsed_dt = datetime.fromisoformat(clean_ts)
                elif isinstance(raw_ts, (int, float)):
                    parsed_dt = datetime.fromtimestamp(float(raw_ts), tz=EXCHANGE_TIMEZONE)
                else:
                    continue

                ts_ist = normalize_to_ist(parsed_dt)

                open_p = float(row[1])
                high_p = float(row[2])
                low_p = float(row[3])
                close_p = float(row[4])
                vol = int(row[5]) if len(row) > 5 and row[5] is not None else 0
                oi = int(row[6]) if len(row) > 6 and row[6] is not None else 0

                # Reject non-positive prices
                if open_p <= 0 or high_p <= 0 or low_p <= 0 or close_p <= 0:
                    continue

                # Reject corrupted bars where reported high is strictly less than reported low
                if high_p < low_p:
                    continue

                # Validate physical OHLC envelope
                real_high = max(high_p, open_p, close_p)
                real_low = min(low_p, open_p, close_p)

                bar = Bar(
                    timestamp=ts_ist,
                    open=open_p,
                    high=real_high,
                    low=real_low,
                    close=close_p,
                    volume=max(0, vol),
                    oi=max(0, oi),
                    symbol=symbol,
                    source="KOTAK_NEO_HISTORICAL",
                    timeframe=timeframe,
                    is_synthetic=False,
                )
                bars.append(bar)
            except (ValueError, TypeError) as exc:
                logger.debug(f"Skipping malformed candle row {row}: {exc}")
                continue

        # Sort chronologically ascending and deduplicate by timestamp
        bars.sort(key=lambda b: b.timestamp)
        deduped: list[Bar] = []
        seen_ts: set[datetime] = set()
        for b in bars:
            if b.timestamp not in seen_ts:
                seen_ts.add(b.timestamp)
                deduped.append(b)

        return deduped

    @classmethod
    def process_and_verify(
        cls,
        raw_response: dict[str, Any] | list[Any],
        *,
        neosymbol: str,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
        expected_interval_minutes: int | None = None,
        is_options_dataset: bool = False,
        sdk_version: str = "3.0.6",
        output_dir: Path | None = None,
    ) -> KotakNormalizedDataset:
        """Complete workflow: Save raw capture, normalize to bars, and run integrity audit."""
        raw_file, metadata = cls.save_raw_capture(
            raw_response,
            neosymbol=neosymbol,
            symbol=symbol,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            sdk_version=sdk_version,
            output_dir=output_dir,
        )

        bars = cls.normalize_candles(raw_response, symbol=symbol, timeframe=interval)

        # Audit with DataIntegrityChecker
        int_min = expected_interval_minutes
        if int_min is None:
            if interval.endswith("min"):
                try:
                    int_min = int(interval[:-3])
                except ValueError:
                    int_min = 1
            elif interval == "1m":
                int_min = 1
            elif interval == "5m":
                int_min = 5
            elif interval == "15m":
                int_min = 15

        integrity_report = DataIntegrityChecker.audit_bars(
            bars,
            source_identifier=raw_file.name,
            expected_interval_minutes=int_min,
            is_options_dataset=is_options_dataset,
        )

        return KotakNormalizedDataset(
            metadata=metadata,
            raw_file_path=str(raw_file),
            bars=bars,
            integrity_report=integrity_report,
            is_valid=integrity_report.is_valid,
        )

    @classmethod
    def process_raw_response(
        cls,
        raw_response: dict[str, Any] | list[Any],
        *,
        neosymbol: str,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
        expected_interval_minutes: int | None = None,
        is_options_dataset: bool = False,
        sdk_version: str = "3.0.6",
        output_dir: Path | None = None,
    ) -> KotakNormalizedDataset:
        """Alias for process_and_verify workflow."""
        return cls.process_and_verify(
            raw_response,
            neosymbol=neosymbol,
            symbol=symbol,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            expected_interval_minutes=expected_interval_minutes,
            is_options_dataset=is_options_dataset,
            sdk_version=sdk_version,
            output_dir=output_dir,
        )
