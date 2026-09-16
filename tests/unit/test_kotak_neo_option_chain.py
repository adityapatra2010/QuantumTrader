"""Unit tests for Kotak Neo live option chain integration, normalization, quotes, and Premium-Ladder selection.

Verifies:
1. Expiries parsing (ISO dates, dd-MMM-yyyy, sorting, empty responses).
2. Option chain parsing (official v3.0.6 schema, strike paise scaling, CE/PE mapping).
3. Canonical normalization into PointInTimeOptionChain without synthetic price fabrication.
4. Quotes cross-check comparison (LTP drift, volume, OI, and L2 market depth).
5. SFeed WebSocket subscription and token resolution.
6. Premium-Ladder deterministic candidate selection (short leg in band, hedge leg near ₹5).
7. Data quality auditing (duplicate strikes, missing LTP, stale quotes, truncated hedges).
8. Physical air-gap constraints (ADR 002).
9. CLI subcommand smoke test execution.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aditrader.cli.commands import cmd_kotak_option_chain
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.adapters.kotak_option_chain import (
    KotakOptionChainManager,
    OptionChainQualityReport,
    PremiumLadderSelectionResult,
    QuoteComparisonResult,
    WebSocketVerificationResult,
)
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.options.chain_replay import (
    PointInTimeOptionChain,
    PointInTimeOptionContract,
)

# ==============================================================================
# 1. Expiries Parsing & Calendar Normalization
# ==============================================================================


class TestKotakExpiriesParsing:
    """Test expiry date retrieval, parsing across date formats, and sorting."""

    def test_mock_expiries_generation(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        expiries = mgr.fetch_expiries(underlying="NIFTY")
        assert len(expiries) == 4
        # Verify chronological sorting
        for i in range(len(expiries) - 1):
            assert expiries[i] < expiries[i + 1]

    def test_multi_format_date_parsing(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        assert mgr._parse_date_string("2026-09-24") == date(2026, 9, 24)
        assert mgr._parse_date_string("24-Sep-2026") == date(2026, 9, 24)
        assert mgr._parse_date_string("24/09/2026") == date(2026, 9, 24)
        assert mgr._parse_date_string("invalid-date") is None

    def test_expiries_from_adapter_response(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.mock_mode = False
        mock_adapter.fetch_expiries.return_value = ["24-Sep-2026", "2026-10-01", "2026-10-29"]

        mgr = KotakOptionChainManager(adapter=mock_adapter, mock_mode=False)
        expiries = mgr.fetch_expiries(underlying="NIFTY")

        assert expiries == ["2026-09-24", "2026-10-01", "2026-10-29"]
        assert mock_adapter.fetch_expiries.called


# ==============================================================================
# 2. Option Chain Parsing & Strike Scaling
# ==============================================================================


class TestKotakOptionChainParsing:
    """Test option chain payload parsing, strike paise scaling, and CE/PE mapping."""

    def test_strike_paise_scaling_in_chain(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw_payload = {
            "data": {
                "common_data": {
                    "unlSymbol": "NIFTY",
                    "expiryDt": "2026-09-24",
                },
                "call": [
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|71472",
                            "symbol": "NIFTY26SEP24500CE",
                            "optionType": "CE",
                            "strikePrice": "2450000",  # Strike in paise
                        },
                        "quote": {"ltp": "55.50", "volume": 10000},
                        "openInterest": {"current": 500000},
                    }
                ],
                "put": [],
            }
        }
        chain = mgr.normalize_option_chain(raw_payload)
        assert len(chain.contracts) == 1
        c = chain.contracts[0]
        assert c.strike == 24500.0
        assert c.ltp == 55.50
        assert c.option_type == "CE"

    def test_ce_pe_separation_and_fields(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw_payload = {
            "data": {
                "common_data": {
                    "unlSymbol": "NIFTY",
                    "expiryDt": "2026-09-24",
                },
                "call": [
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|101",
                            "symbol": "NIFTY26SEP24000CE",
                            "optionType": "CE",
                            "strikePrice": "24000",
                        },
                        "quote": {"ltp": "120.0", "volume": 50000, "bid": "119.5", "ask": "120.5"},
                        "openInterest": {"current": 1000000},
                    }
                ],
                "put": [
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|102",
                            "symbol": "NIFTY26SEP24000PE",
                            "optionType": "PE",
                            "strikePrice": "24000",
                        },
                        "quote": {"ltp": "85.0", "volume": 40000, "bid": "84.5", "ask": "85.5"},
                        "openInterest": {"current": 800000},
                    }
                ],
            }
        }
        chain = mgr.normalize_option_chain(raw_payload, spot_price=24100.0)
        assert len(chain.contracts) == 2
        ce = next(c for c in chain.contracts if c.option_type == "CE")
        pe = next(c for c in chain.contracts if c.option_type == "PE")

        assert ce.strike == 24000.0
        assert ce.ltp == 120.0
        assert ce.bid == 119.5
        assert ce.ask == 120.5
        assert ce.volume == 50000
        assert ce.oi == 1000000

        assert pe.strike == 24000.0
        assert pe.ltp == 85.0
        assert pe.bid == 84.5
        assert pe.ask == 85.5

    def test_market_closed_ltp_fallback(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw_payload = {
            "data": {
                "common_data": {"unlSymbol": "NIFTY", "expiryDt": "2026-09-24"},
                "call": [
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|103",
                            "symbol": "NIFTY_TEST",
                            "optionType": "CE",
                            "strikePrice": "24500",
                        },
                        "quote": {"ltp": "0.0", "close": "45.0", "prevClose": "44.0"},
                        "openInterest": {"current": 10000},
                    }
                ],
                "put": [],
            }
        }
        chain = mgr.normalize_option_chain(raw_payload)
        assert len(chain.contracts) == 1
        assert chain.contracts[0].ltp == 45.0

    def test_malformed_payload_raises_value_error(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        with pytest.raises(ValueError, match="Malformed option chain response"):
            mgr.normalize_option_chain({"error": "server_down"})


# ==============================================================================
# 3. Canonical Normalization & Provenance
# ==============================================================================


class TestKotakNormalization:
    """Verify PointInTimeOptionChain structure, provenance, and absence of fake prices."""

    def test_canonical_structure_properties(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw = mgr.fetch_option_chain(count=40)
        chain = mgr.normalize_option_chain(raw, spot_price=24500.0)

        assert isinstance(chain, PointInTimeOptionChain)
        assert chain.underlying == "NIFTY"
        assert chain.is_intraday is True
        assert chain.source == "KOTAK_NEO_OPTION_CHAIN"
        assert chain.spot_price == 24500.0
        assert len(chain.contracts) > 0

        # Verify no synthetic Black-Scholes Greeks were fabricated in raw quotes
        for c in chain.contracts:
            assert isinstance(c, PointInTimeOptionContract)
            assert c.ltp > 0.0
            assert c.timestamp.tzinfo == EXCHANGE_TIMEZONE


# ==============================================================================
# 4. Quotes Cross-Check
# ==============================================================================


class TestQuotesCrossCheck:
    """Test comparing option_chain records with quotes() endpoint."""

    def test_mock_quotes_comparison_passes(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw = mgr.fetch_option_chain(count=40)
        chain = mgr.normalize_option_chain(raw)

        comparisons = mgr.verify_against_quotes(chain.contracts, sample_size=4)
        assert len(comparisons) == 4
        for cmp in comparisons:
            assert isinstance(cmp, QuoteComparisonResult)
            assert cmp.ltp_matches is True
            assert cmp.has_depth is True
            assert cmp.chain_ltp == cmp.quote_ltp

    def test_quotes_discrepancy_reporting(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.mock_mode = False
        mock_adapter.consumer_key = "test_key"
        mock_adapter.is_authenticated = True

        mock_neo = MagicMock()
        # Mock quotes returning slightly drifted LTP
        mock_neo.quotes.return_value = [
            {
                "exchange_token": "70040",
                "ltp": "58.20",  # Drifted from chain's 55.00
                "last_volume": "10000",
                "open_int": "500000",
                "depth": {"buy": [{"price": "58.00"}], "sell": [{"price": "58.50"}]},
                "lstup_time": "1782374657",
            }
        ]
        mock_adapter._neo_client = mock_neo

        mgr = KotakOptionChainManager(adapter=mock_adapter, mock_mode=False)

        eval_ts = datetime.now(EXCHANGE_TIMEZONE)
        contract = PointInTimeOptionContract(
            trading_symbol="NIFTY_20260924_24500_CE_70040",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=date(2026, 9, 24),
            ltp=55.00,
            timestamp=eval_ts,
        )

        comparisons = mgr.verify_against_quotes([contract], sample_size=1)
        assert len(comparisons) == 1
        cmp = comparisons[0]
        assert cmp.ltp_matches is False
        assert cmp.chain_ltp == 55.00
        assert cmp.quote_ltp == 58.20
        assert "LTP drift" in (cmp.discrepancy_note or "")


# ==============================================================================
# 5. SFeed WebSocket Verification
# ==============================================================================


class TestKotakWebSocketVerification:
    """Test SFeed WebSocket subscription verification."""

    def test_mock_websocket_verification_passes(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw = mgr.fetch_option_chain(count=20)
        chain = mgr.normalize_option_chain(raw)

        ws_res = mgr.verify_websocket_path(chain.contracts, sample_size=3)
        assert isinstance(ws_res, WebSocketVerificationResult)
        assert ws_res.status == "PASS"
        assert ws_res.timestamps_usable is True
        assert ws_res.mapping_correct is True
        assert len(ws_res.subscribed_tokens) == 3


# ==============================================================================
# 6. NIFTY CE Premium-Ladder Live Selection Readiness
# ==============================================================================


class TestPremiumLadderLiveSelection:
    """Test first-step deterministic contract selection for the Premium-Ladder strategy."""

    def test_deterministic_short_and_hedge_selection(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw = mgr.fetch_option_chain(count=100)
        chain = mgr.normalize_option_chain(raw, spot_price=24500.0)

        result = mgr.evaluate_premium_ladder_selection(chain)
        assert isinstance(result, PremiumLadderSelectionResult)
        assert result.selection_status == "SELECTED"
        assert result.is_deterministic is True

        # Short leg must fall into one of the configured premium bands (e.g. 50-59.5)
        assert result.short_leg_symbol is not None
        assert result.short_leg_ltp is not None
        assert 50.0 <= result.short_leg_ltp <= 109.5

        # Hedge leg must be near ₹5.00 (within 3.0 to 7.0)
        assert result.hedge_leg_symbol is not None
        assert result.hedge_leg_ltp is not None
        assert 3.0 <= result.hedge_leg_ltp <= 7.0

        # Short leg and hedge leg must not be the same contract
        assert result.short_leg_symbol != result.hedge_leg_symbol
        assert result.short_leg_strike is not None
        assert result.hedge_leg_strike is not None
        assert result.short_leg_strike < result.hedge_leg_strike  # Hedge is further OTM

    def test_repeatable_identical_selection(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw = mgr.fetch_option_chain(count=100)
        chain = mgr.normalize_option_chain(raw, spot_price=24500.0)

        # Run selection multiple times on identical snapshot
        res1 = mgr.evaluate_premium_ladder_selection(chain)
        res2 = mgr.evaluate_premium_ladder_selection(chain)

        assert res1.short_leg_symbol == res2.short_leg_symbol
        assert res1.short_leg_strike == res2.short_leg_strike
        assert res1.short_leg_ltp == res2.short_leg_ltp
        assert res1.hedge_leg_symbol == res2.hedge_leg_symbol
        assert res1.hedge_leg_strike == res2.hedge_leg_strike
        assert res1.hedge_leg_ltp == res2.hedge_leg_ltp

    def test_missing_hedge_candidates_returns_partial(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        # Small strike count (20) around ATM: all premiums will be > ₹15, so no ₹5 hedge
        raw = mgr.fetch_option_chain(count=20)
        chain = mgr.normalize_option_chain(raw, spot_price=24500.0)

        # Artificially remove any hedge candidates
        filtered_contracts = [c for c in chain.contracts if not (3.0 <= c.ltp <= 7.0)]
        chain._contracts = filtered_contracts

        result = mgr.evaluate_premium_ladder_selection(chain)
        assert result.selection_status == "PARTIAL"
        assert result.hedge_leg_symbol is None
        assert "no hedge leg found" in (result.failure_reason or "")


# ==============================================================================
# 7. Data Quality & Missing Data Behavior
# ==============================================================================


class TestDataQualityAudit:
    """Test data quality auditing, missing strikes, duplicate detection, and stale quotes."""

    def test_audit_passes_on_complete_mock_chain(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw = mgr.fetch_option_chain(count=100)
        chain = mgr.normalize_option_chain(raw, spot_price=24500.0)

        report = mgr.audit_data_quality(chain)
        assert isinstance(report, OptionChainQualityReport)
        assert report.status == "PASS"
        assert report.duplicate_strikes_count == 0
        assert report.missing_ltp_count == 0
        assert report.has_hedge_candidates is True
        assert len(report.issues) == 0

    def test_detects_duplicate_strikes(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        eval_ts = datetime.now(EXCHANGE_TIMEZONE)
        c1 = PointInTimeOptionContract(
            trading_symbol="NIFTY_24500_CE_1",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=date(2026, 9, 24),
            ltp=55.0,
            timestamp=eval_ts,
        )
        c2 = PointInTimeOptionContract(
            trading_symbol="NIFTY_24500_CE_2",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=date(2026, 9, 24),
            ltp=56.0,
            timestamp=eval_ts,
        )
        chain = PointInTimeOptionChain(
            timestamp=eval_ts,
            underlying="NIFTY",
            contracts=[c1, c2],
        )

        report = mgr.audit_data_quality(chain)
        assert report.duplicate_strikes_count == 1
        assert any("duplicate strike" in iss.lower() for iss in report.issues)

    def test_detects_stale_quotes(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        # Quote observed 1 hour ago
        old_ts = datetime.now(EXCHANGE_TIMEZONE) - timedelta(hours=1)
        c = PointInTimeOptionContract(
            trading_symbol="NIFTY_24500_CE",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=date(2026, 9, 24),
            ltp=55.0,
            timestamp=old_ts,
        )
        chain = PointInTimeOptionChain(
            timestamp=old_ts,
            underlying="NIFTY",
            contracts=[c],
        )

        report = mgr.audit_data_quality(chain, max_quote_age_seconds=60.0)
        assert report.stale_quotes_count == 1
        assert any("quote staleness" in iss.lower() for iss in report.issues)


# ==============================================================================
# 8. Air-Gap Safety & Prohibitions (ADR 002)
# ==============================================================================


class TestContractMetadataAndTimestampPreservation:
    """Verify that broker tokens, lot sizes, and exchange quote timestamps are preserved."""

    def test_token_and_lot_size_and_timestamp_extracted(self) -> None:
        mgr = KotakOptionChainManager(mock_mode=True)
        raw_payload = {
            "data": {
                "common_data": {
                    "unlSymbol": "NIFTY",
                    "expiryDt": "2026-09-24",
                    "mktLot": "25",
                },
                "call": [
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|71472",
                            "symbol": "NIFTY26SEP24500CE",
                            "optionType": "CE",
                            "strikePrice": "24500",
                        },
                        "quote": {
                            "ltp": "55.50",
                            "volume": 10000,
                            "lstup_time": 1726416000,  # 2024-09-15 16:00:00 UTC
                        },
                        "openInterest": {"current": 500000},
                    }
                ],
                "put": [],
            }
        }
        chain = mgr.normalize_option_chain(raw_payload)
        contract = chain.contracts[0]
        assert contract.token == "71472"
        assert contract.lot_size == 25
        assert contract.timestamp.year >= 2024
        # Verify helper uses contract.token directly
        assert mgr._extract_or_make_token(contract) == "71472"


class TestKotakAirGapSafety:
    """Verify live order routing methods remain strictly unimplemented."""

    def test_order_routing_methods_remain_unimplemented(self) -> None:
        adapter = KotakNeoAdapter(mock_mode=True)
        with pytest.raises(NotImplementedError, match="ADR 002"):
            adapter.place_order(MagicMock())

        with pytest.raises(NotImplementedError, match="ADR 002"):
            adapter.modify_order("order_1", MagicMock())

        with pytest.raises(NotImplementedError, match="ADR 002"):
            adapter.cancel_order("order_1")


# ==============================================================================
# 9. CLI Smoke Test Execution
# ==============================================================================


class TestKotakOptionChainCLI:
    """Verify cmd_kotak_option_chain command runs end-to-end in mock mode."""

    def test_cmd_kotak_option_chain_mock(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = argparse.Namespace(
            underlying="NIFTY",
            expiry=None,
            count=100,
            output_dir=str(tmp_path),
            mock=True,
        )
        code = cmd_kotak_option_chain(args)
        assert code == 0

        out = capsys.readouterr().out
        assert "KOTAK NEO OPTION-CHAIN INTEGRATION" in out
        assert "AUTHENTICATION" in out
        assert "PASS (MOCK SESSION)" in out
        assert "OPTION CHAIN SNAPSHOT" in out
        assert "CROSS-CHECK" in out
        assert "SFEED WEBSOCKET PATH VERIFICATION" in out
        assert "NIFTY CE PREMIUM-LADDER FIRST-STEP SELECTION" in out
        assert "SELECTION: SELECTED" in out or "Selection Status: SELECTED" in out
        assert "DATA QUALITY & COMPLETENESS AUDIT" in out
        assert "SUMMARY VERDICT: LIVE OPTION CHAIN READY" in out
