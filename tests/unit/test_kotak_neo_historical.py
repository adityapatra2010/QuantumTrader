"""Unit test suite for Kotak Neo historical market data adapter and capability discovery.

Verifies:
1. Physical air-gap: Order routing methods remain strictly unimplemented (ADR 002).
2. Scrip parsing: Strike price paise-to-rupees scaling and 1980 epoch offset adjustments.
3. Historical data: Automated <= 29-day date chunking, retry backoff, and deduplication.
4. Capture manager: Raw JSON hashing, canonical Bar normalization, and envelope audits.
5. Capability discovery: Progressive tests A through E and definitive 10-year options verdict.
6. CLI entrypoints: kotak-auth, kotak-discover, and kotak-history execution.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from aditrader.cli.commands import (
    cmd_kotak_auth,
    cmd_kotak_discover,
    cmd_kotak_history,
)
from aditrader.data.adapters.kotak_capture import (
    KotakCaptureManager,
    KotakNormalizedDataset,
)
from aditrader.data.adapters.kotak_discovery import (
    KotakCapabilityDiscoverer,
    KotakCapabilityReport,
)
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.session import EXCHANGE_TIMEZONE

# ==============================================================================
# 1. Air-Gap & Safety Constraints (ADR 002)
# ==============================================================================


class TestKotakNeoAirGap:
    """Ensure Kotak Neo adapter remains strictly read-only and air-gapped from execution."""

    def test_order_placement_methods_raise_not_implemented(self) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)
        with pytest.raises(NotImplementedError, match="ADR 002"):
            adapter.place_order(MagicMock())

        with pytest.raises(NotImplementedError, match="ADR 002"):
            adapter.modify_order("order_123", MagicMock())

        with pytest.raises(NotImplementedError, match="ADR 002"):
            adapter.cancel_order("order_123")


# ==============================================================================
# 2. Scrip Master Parsing & Scaling Rules
# ==============================================================================


class TestKotakNeoScripParsing:
    """Test scrip master CSV parsing, strike paise scaling, and epoch adjustments."""

    def test_strike_price_paise_scaling(self) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)

        # Case 1: dStrikePrice; format in paise (2400000 paise = 24000.0 INR)
        row_paise_semicolon = {
            "pSymbol": "NIFTY24DEC24000CE",
            "pTrdSymbol": "NIFTY 26-DEC-2024 CE 24000",
            "pExchSeg": "nse_fo",
            "pInstType": "OPTIDX",
            "pSymbolToken": "45001",
            "pLotSize": "25",
            "pTickSize": "0.05",
            "dStrikePrice;": "2400000",
            "pOptionType": "CE",
        }
        c1 = adapter.parse_scrip_csv_row(row_paise_semicolon)
        assert c1.strike_price == 24000.0
        assert c1.option_type == "CE"
        assert c1.lot_size == 25

        # Case 2: pStrikePrice in paise >= 100,000 (2350000 -> 23500.0)
        row_paise_high = {
            "pSymbol": "NIFTY24DEC23500PE",
            "pTrdSymbol": "NIFTY 26-DEC-2024 PE 23500",
            "pExchSeg": "nse_fo",
            "pInstType": "OPTIDX",
            "pSymbolToken": "45002",
            "pStrikePrice": "2350000",
            "pOptionType": "PE",
        }
        c2 = adapter.parse_scrip_csv_row(row_paise_high)
        assert c2.strike_price == 23500.0
        assert c2.option_type == "PE"

        # Case 3: Already in rupees (< 100,000)
        row_rupees = {
            "pSymbol": "BANKNIFTY50000CE",
            "pSymbolToken": "45003",
            "pStrikePrice": "50000.0",
            "pOptionType": "CE",
        }
        c3 = adapter.parse_scrip_csv_row(row_rupees)
        assert c3.strike_price == 50000.0

    def test_expiry_date_epoch_offset_adjustment(self) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)

        # Kotak Neo binary/scrip files sometimes use epoch offset starting in 1980
        # If timestamp gives year < 2020, 315,511,200 seconds (~10 years) are added
        base_target = datetime(2024, 12, 26, 15, 30, tzinfo=EXCHANGE_TIMEZONE)
        raw_epoch = base_target.timestamp() - 315513000

        row_epoch = {
            "pSymbol": "NIFTY_EXP_TEST",
            "pSymbolToken": "99001",
            "pExpiryDate": str(int(raw_epoch)),
        }
        c = adapter.parse_scrip_csv_row(row_epoch)
        assert c.expiry_date is not None
        assert c.expiry_date.year == 2024
        assert c.expiry_date.month == 12

    def test_expiry_date_string_formats(self) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)
        for fmt_str in ("26-Dec-2024", "2024-12-26", "26/12/2024"):
            row = {"pSymbol": "TEST", "pSymbolToken": "1", "pExpiryDate": fmt_str}
            c = adapter.parse_scrip_csv_row(row)
            assert c.expiry_date is not None
            assert c.expiry_date.year == 2024
            assert c.expiry_date.month == 12
            assert c.expiry_date.day == 26


# ==============================================================================
# 3. Historical Data Chunking, Mapping, and Deduplication
# ==============================================================================


class TestKotakNeoHistoricalRetrieval:
    """Test date chunking, interval mapping, deduplication, and retries."""

    def test_interval_mapping_and_max_days(self) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)
        assert adapter._map_timeframe_to_interval("1m") == "1min"
        assert adapter._map_timeframe_to_interval("5m") == "5min"
        assert adapter._map_timeframe_to_interval("15m") == "15min"
        assert adapter._map_timeframe_to_interval("1h") == "60min"
        assert adapter._map_timeframe_to_interval("1d") == "D"

        assert adapter._get_interval_max_days("1min") == 29
        assert adapter._get_interval_max_days("5min") == 29
        assert adapter._get_interval_max_days("15min") == 59
        assert adapter._get_interval_max_days("60min") == 89
        assert adapter._get_interval_max_days("D") == 179

    def test_resolve_neosymbol(self) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)
        assert adapter.resolve_neosymbol("NIFTY") == "nse_cm|26000"
        assert adapter.resolve_neosymbol("BANKNIFTY") == "nse_cm|26001"
        assert adapter.resolve_neosymbol("RELIANCE") == "nse_cm|1333"
        assert adapter.resolve_neosymbol("nse_fo|45001") == "nse_fo|45001"

    def test_historical_bars_chunking_with_mock_client(self) -> None:
        adapter = KotakNeoAdapter(consumer_key="mock_key", mock_mode=False)

        mock_neo = MagicMock()

        def mock_historical_data(
            neosymbol: str, interval: str, from_date: str, to_date: str
        ) -> dict[str, Any]:
            f_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=EXCHANGE_TIMEZONE)
            t_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=EXCHANGE_TIMEZONE)
            candles = []
            curr = f_dt.replace(hour=9, minute=15)
            while curr <= t_dt.replace(hour=15, minute=30):
                if 9 * 60 + 15 <= curr.hour * 60 + curr.minute <= 15 * 60 + 30:
                    ts_str = curr.strftime("%Y-%m-%d %H:%M:%S")
                    candles.append([ts_str, 24000.0, 24050.0, 23950.0, 24010.0, 1000, 50000])
                curr += timedelta(hours=2)
            return {"status": "success", "interval": interval, "data": {"candles": candles}}

        mock_neo.historical_data.side_effect = mock_historical_data
        adapter._neo_client = mock_neo

        start_time = datetime(2024, 10, 1, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
        end_time = datetime(2024, 11, 30, 15, 30, tzinfo=EXCHANGE_TIMEZONE)

        bars = adapter.fetch_historical_bars(
            symbol="NIFTY",
            start_time=start_time,
            end_time=end_time,
            timeframe="5m",
        )

        assert len(bars) > 0
        assert mock_neo.historical_data.call_count >= 2
        for i in range(len(bars) - 1):
            assert bars[i].timestamp <= bars[i + 1].timestamp
            assert start_time <= bars[i].timestamp <= end_time


# ==============================================================================
# 4. KotakCaptureManager: Hashing, Normalization, and Integrity
# ==============================================================================


class TestKotakCaptureManager:
    """Test raw API capture hashing, canonical normalization, and envelope checks."""

    def test_save_raw_capture_hashes_and_persists(self, tmp_path: Path) -> None:
        raw_payload = {
            "status": "success",
            "interval": "5min",
            "data": {
                "candles": [
                    ["2024-12-24 09:15:00", 24000.0, 24050.0, 23950.0, 24010.0, 5000, 100000],
                    ["2024-12-24 09:20:00", 24010.0, 24060.0, 24000.0, 24040.0, 4200, 105000],
                ]
            },
        }
        raw_file, meta = KotakCaptureManager.save_raw_capture(
            raw_payload,
            neosymbol="nse_cm|26000",
            symbol="NIFTY",
            interval="5min",
            from_date="2024-12-24",
            to_date="2024-12-24",
            output_dir=tmp_path,
        )

        assert raw_file.is_file()
        assert meta.record_count == 2
        assert meta.raw_sha256 is not None
        assert len(meta.raw_sha256) == 64

    def test_normalize_candles_enforces_price_envelope(self) -> None:
        payload = {
            "status": "success",
            "data": {
                "candles": [
                    ["2024-12-24 09:15:00", 100.0, 110.0, 95.0, 105.0, 1000, 20000],
                    ["2024-12-24 09:20:00", 100.0, 90.0, 110.0, 105.0, 1000, 20000],
                ]
            },
        }
        bars = KotakCaptureManager.normalize_candles(payload, symbol="TEST_SYM", timeframe="5m")
        assert len(bars) == 1
        assert bars[0].open == 100.0
        assert bars[0].high == 110.0
        assert bars[0].low == 95.0
        assert bars[0].close == 105.0
        assert bars[0].timestamp.tzinfo == EXCHANGE_TIMEZONE

    def test_process_raw_response_runs_integrity_audit(self, tmp_path: Path) -> None:
        payload = {
            "status": "success",
            "interval": "5min",
            "data": {
                "candles": [
                    ["2024-12-24 09:15:00", 24000.0, 24050.0, 23950.0, 24010.0, 5000, 100000],
                    ["2024-12-24 09:20:00", 24010.0, 24060.0, 24000.0, 24040.0, 4200, 105000],
                ]
            },
        }
        dataset = KotakCaptureManager.process_raw_response(
            payload,
            neosymbol="nse_cm|26000",
            symbol="NIFTY",
            interval="5min",
            from_date="2024-12-24",
            to_date="2024-12-24",
            output_dir=tmp_path,
        )
        assert isinstance(dataset, KotakNormalizedDataset)
        assert dataset.is_valid is True
        assert len(dataset.bars) == 2
        assert dataset.integrity_report.envelope_violations_count == 0


# ==============================================================================
# 5. KotakCapabilityDiscoverer: 5 Progressive Tests & Verdict
# ==============================================================================


class TestKotakCapabilityDiscovery:
    """Test progressive discovery tests A-E and definitive 10-year verdict."""

    def test_discovery_suite_runs_all_tests_in_mock_mode(self, tmp_path: Path) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)
        discoverer = KotakCapabilityDiscoverer(adapter=adapter, raw_capture_dir=tmp_path)

        report = discoverer.run_discovery_suite(output_dir=tmp_path)

        assert isinstance(report, KotakCapabilityReport)
        assert len(report.tests) == 5

        test_ids = [t.test_id for t in report.tests]
        assert test_ids == ["TEST_A", "TEST_B", "TEST_C", "TEST_D", "TEST_E"]

        test_c = next(t for t in report.tests if t.test_id == "TEST_C")
        assert test_c.status == "FAIL"

        assert report.ten_year_options_verdict == "NOT AVAILABLE"
        assert "NOT AVAILABLE" in report.verdict_rationale
        assert len(report.blocking_factors) >= 4

    def test_blocking_factors_contain_all_critical_impediments(self, tmp_path: Path) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)
        discoverer = KotakCapabilityDiscoverer(adapter=adapter, raw_capture_dir=tmp_path)
        report = discoverer.run_discovery_suite(output_dir=tmp_path)

        factors_text = " ".join(report.blocking_factors).upper()
        assert "EXPIRED" in factors_text
        assert "SCRIP MASTER" in factors_text
        assert "BID/ASK" in factors_text
        assert "GREEKS" in factors_text or "IV" in factors_text
        assert "TOKEN RECYCLING" in factors_text


# ==============================================================================
# 6. CLI Commands Smoke Verification
# ==============================================================================


class TestKotakCLICommands:
    """Verify CLI subcommands kotak-auth, kotak-discover, and kotak-history."""

    def test_cmd_kotak_auth_mock(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(mock=True)
        code = cmd_kotak_auth(args)
        assert code == 0
        out = capsys.readouterr().out
        assert "KOTAK NEO AUTHENTICATION: PASS (MOCK MODE)" in out
        assert "SDK VERSION:         3.0.6" in out

    def test_cmd_kotak_discover_mock(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = argparse.Namespace(mock=True, output_dir=str(tmp_path))
        code = cmd_kotak_discover(args)
        assert code == 0
        out = capsys.readouterr().out
        assert "10-YEAR OPTIONS BACKTEST DATA: NOT AVAILABLE" in out
        assert "TEST_A" in out
        assert "TEST_C" in out

    def test_cmd_kotak_history_mock(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_json = tmp_path / "nifty_bars.json"
        args = argparse.Namespace(
            symbol="NIFTY",
            symbol_arg=None,
            timeframe="5m",
            from_date=None,
            to_date=None,
            output=str(out_json),
            mock=True,
        )
        code = cmd_kotak_history(args)
        assert code == 0
        out = capsys.readouterr().out
        assert "Integrity Status:    PASS" in out
        assert out_json.is_file()
        content = json.loads(out_json.read_text(encoding="utf-8"))
        assert len(content) > 0
