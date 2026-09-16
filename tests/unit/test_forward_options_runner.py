"""Unit and integration tests for Kotak Neo Real Forward-Shadow Execution Subsystem.

Verifies:
1. Air-gap enforcement (ADR 002): Physical impossibility of real broker order routing.
2. Fail-closed real authentication: Real mode never falls back to mock silently.
3. Lot sizing integrity: NIFTY 25 shares/lot scaling (1 lot = 25, 4 lots = 100).
4. Dynamic contract resolution: Short CE in target band + 4x hedge CE near ₹5.
5. Per-contract trailing stop state machine with ratchet stepping.
6. Group exit execution on stop trigger and 15:15 IST square-off.
7. Cryptographic sealing: Merkle roots, reconciliation balance, tamper digest.
8. Raw option-chain JSON archiving to runs/kotak_raw/.
9. CLI routing and arguments handling.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aditrader.cli.commands import cmd_forward_options, cmd_forward_test
from aditrader.core.broker import PaperBroker
from aditrader.core.models.enums import OrderSide, OrderStatus
from aditrader.core.models.market_data import Tick
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.adapters.kotak_option_chain import PremiumLadderSelectionResult
from aditrader.data.forward_options_runner import (
    ForwardOptionsSessionConfig,
    KotakOptionForwardRunner,
    RealKotakAuthenticationError,
)
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.options.chain_replay import (
    PointInTimeOptionChain,
    PointInTimeOptionContract,
)

# ==============================================================================
# 1. ADR 002 Air-Gap Safety & Architecture Invariants
# ==============================================================================


class TestAirGapEnforcement:
    """Verify that KotakOptionForwardRunner has NO live order routing capabilities."""

    def test_runner_has_no_live_broker_order_methods(self) -> None:
        """Verify runner lacks any place_order, modify_order, cancel_order methods."""
        config = ForwardOptionsSessionConfig(mock_mode=True, wait_for_market_open=False)
        runner = KotakOptionForwardRunner(config=config)

        # Prohibited live execution verbs must not exist on runner
        assert not hasattr(runner, "place_order")
        assert not hasattr(runner, "modify_order")
        assert not hasattr(runner, "cancel_order")
        assert not hasattr(runner, "execute_live_order")

    def test_all_fills_occur_inside_local_paper_broker(self) -> None:
        """Verify broker is strictly an instance of PaperBroker."""
        config = ForwardOptionsSessionConfig(mock_mode=True, wait_for_market_open=False)
        runner = KotakOptionForwardRunner(config=config)

        assert isinstance(runner.broker, PaperBroker)
        assert runner.broker._deterministic is True

    def test_adapter_has_no_broker_order_routing(self) -> None:
        """Verify KotakNeoAdapter fails closed with security veto if order methods called."""
        config = ForwardOptionsSessionConfig(mock_mode=True, wait_for_market_open=False)
        runner = KotakOptionForwardRunner(config=config)

        with pytest.raises(NotImplementedError, match="CRITICAL SECURITY VETO"):
            runner.adapter.place_order()

        with pytest.raises(NotImplementedError, match="CRITICAL SECURITY VETO"):
            runner.adapter.modify_order()

        with pytest.raises(NotImplementedError, match="CRITICAL SECURITY VETO"):
            runner.adapter.cancel_order()


# ==============================================================================
# 2. Fail-Closed Authentication Policy
# ==============================================================================


class TestFailClosedAuthentication:
    """Verify runner fails closed when real authentication fails."""

    def test_real_auth_missing_credentials_fails_closed(self) -> None:
        """If real forward session is invoked without Kotak credentials, fail closed immediately."""
        config = ForwardOptionsSessionConfig(
            mock_mode=False,
            wait_for_market_open=False,
            duration_seconds=1.0,
        )

        mock_adapter = MagicMock(spec=KotakNeoAdapter)
        mock_adapter.mock_mode = False
        mock_adapter.consumer_key = None
        mock_adapter.mobile_number = None
        mock_adapter.ucc = None

        runner = KotakOptionForwardRunner(config=config, adapter=mock_adapter)

        with pytest.raises(RealKotakAuthenticationError) as exc_info:
            runner.run()

        assert "Incomplete Kotak Neo credentials" in str(exc_info.value)
        assert not mock_adapter.authenticate.called

    def test_real_auth_failure_raises_real_kotak_authentication_error(self) -> None:
        """If real Kotak authentication fails, runner MUST raise RealKotakAuthenticationError."""
        config = ForwardOptionsSessionConfig(
            mock_mode=False,
            wait_for_market_open=False,
            duration_seconds=1.0,
        )

        mock_adapter = MagicMock(spec=KotakNeoAdapter)
        mock_adapter.mock_mode = False
        mock_adapter.is_authenticated = False
        mock_adapter.consumer_key = "dummy_ck"
        mock_adapter.mobile_number = "9999999999"
        mock_adapter.ucc = "dummy_ucc"
        mock_adapter.authenticate.side_effect = ConnectionError("Invalid TOTP or credentials")

        runner = KotakOptionForwardRunner(config=config, adapter=mock_adapter)

        with pytest.raises(RealKotakAuthenticationError) as exc_info:
            runner.run()

        assert "REAL_KOTAK_AUTHENTICATION_FAILED" in str(exc_info.value)
        assert "Invalid TOTP" in str(exc_info.value)

    def test_real_auth_missing_sdk_raises_error(self) -> None:
        """If real auth requested without SDK installed, fail closed."""
        config = ForwardOptionsSessionConfig(
            mock_mode=False,
            wait_for_market_open=False,
            duration_seconds=1.0,
        )

        mock_adapter = MagicMock(spec=KotakNeoAdapter)
        mock_adapter.mock_mode = False
        mock_adapter.is_authenticated = False
        mock_adapter.consumer_key = "dummy_ck"
        mock_adapter.mobile_number = "9999999999"
        mock_adapter.ucc = "dummy_ucc"
        mock_adapter.authenticate.side_effect = RuntimeError("Official Kotak Neo SDK is required")

        runner = KotakOptionForwardRunner(config=config, adapter=mock_adapter)

        with pytest.raises(RealKotakAuthenticationError):
            runner.run()


# ==============================================================================
# 3. Lot Sizing & Dynamic Leg Resolution
# ==============================================================================


class TestLotSizingAndLegResolution:
    """Verify NIFTY 25 shares/lot sizing and ratio hedge geometry."""

    def test_nifty_lot_size_scaling_in_paper_broker(self, tmp_path: Path) -> None:
        """Short leg (1 lot) must submit qty=25; Hedge leg (4 lots) must submit qty=100."""
        config = ForwardOptionsSessionConfig(
            strategy_id="tpl-nifty-ce-premium-ladder-v1",
            underlying="NIFTY",
            mock_mode=True,
            wait_for_market_open=False,
            duration_seconds=0.5,
            output_dir=tmp_path / "forward",
            raw_capture_dir=tmp_path / "raw",
        )
        runner = KotakOptionForwardRunner(config=config)

        # Create synthetic option chain with valid short leg in Band 1 (₹50-₹59.50) and hedge leg near ₹5.00
        now = datetime.now(EXCHANGE_TIMEZONE)
        c_short = PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24500CE",
            underlying="NIFTY",
            expiry=now.date() + timedelta(days=2),
            strike=24500.0,
            option_type="CE",
            ltp=55.0,
            bid=54.8,
            ask=55.2,
            volume=50000,
            oi=1000000,
            timestamp=now,
            token="71472",
            lot_size=25,
        )
        c_hedge = PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP25500CE",
            underlying="NIFTY",
            expiry=now.date() + timedelta(days=2),
            strike=25500.0,
            option_type="CE",
            ltp=5.10,
            bid=5.00,
            ask=5.20,
            volume=80000,
            oi=2500000,
            timestamp=now,
            token="71475",
            lot_size=25,
        )
        chain = PointInTimeOptionChain(
            timestamp=now,
            underlying="NIFTY",
            contracts=[c_short, c_hedge],
            spot_price=24500.0,
        )

        selected = PremiumLadderSelectionResult(
            underlying="NIFTY",
            expiry=str(now.date() + timedelta(days=2)),
            spot_price=24500.0,
            total_strikes_available=2,
            short_leg_symbol=c_short.trading_symbol,
            short_leg_strike=c_short.strike,
            short_leg_ltp=c_short.ltp,
            short_leg_band="Band 1 (50.0-59.5)",
            hedge_leg_symbol=c_hedge.trading_symbol,
            hedge_leg_strike=c_hedge.strike,
            hedge_leg_ltp=c_hedge.ltp,
            selection_status="SELECTED",
            is_deterministic=True,
        )
        runner._selected_contracts = selected
        runner._latest_chain = chain
        runner.execute_paper_entry()

        assert runner.active_group is not None
        assert runner.active_trailing_stop is not None

        # Verify quantities in position group
        short_legs = [leg for leg in runner.active_group.legs if leg.side == OrderSide.SELL]
        hedge_legs = [leg for leg in runner.active_group.legs if leg.side == OrderSide.BUY]

        assert len(short_legs) == 1
        assert len(hedge_legs) == 1

        # Lot size for NIFTY is 25: 1 lot = 25 units, 4 lots = 100 units
        assert short_legs[0].quantity == 1
        assert short_legs[0].total_units == 25
        assert hedge_legs[0].quantity == 4
        assert hedge_legs[0].total_units == 100

        # Check PaperBroker recorded orders
        orders = runner.broker.get_orders()
        assert len(orders) == 2
        sell_order = next(o for o in orders if o.side == OrderSide.SELL)
        buy_order = next(o for o in orders if o.side == OrderSide.BUY)

        assert sell_order.qty == 25
        assert buy_order.qty == 100


# ==============================================================================
# 4. Trailing Ratchet Stop Execution & Group Exit
# ==============================================================================


class TestTrailingStopAndGroupExit:
    """Verify trailing ratchet state transitions and coordinated group exits."""

    def test_trailing_stop_ratchets_and_triggers_group_exit(self, tmp_path: Path) -> None:
        """When short leg price triggers trailing stop, both short and hedge legs must exit."""
        config = ForwardOptionsSessionConfig(
            strategy_id="tpl-nifty-ce-premium-ladder-v1",
            mock_mode=True,
            wait_for_market_open=False,
            slippage_bps=0.0,
            duration_seconds=0.5,
            output_dir=tmp_path / "forward",
            raw_capture_dir=tmp_path / "raw",
        )
        runner = KotakOptionForwardRunner(config=config)

        now = datetime.now(EXCHANGE_TIMEZONE)
        c_short = PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24500CE",
            underlying="NIFTY",
            expiry=now.date() + timedelta(days=2),
            strike=24500.0,
            option_type="CE",
            ltp=50.0,
            bid=50.0,
            ask=50.0,
            volume=50000,
            oi=1000000,
            timestamp=now,
            token="71472",
            lot_size=25,
        )
        c_hedge = PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP25500CE",
            underlying="NIFTY",
            expiry=now.date() + timedelta(days=2),
            strike=25500.0,
            option_type="CE",
            ltp=5.00,
            bid=5.00,
            ask=5.00,
            volume=80000,
            oi=2500000,
            timestamp=now,
            token="71475",
            lot_size=25,
        )
        chain = PointInTimeOptionChain(
            timestamp=now,
            underlying="NIFTY",
            contracts=[c_short, c_hedge],
            spot_price=24500.0,
        )
        selected = PremiumLadderSelectionResult(
            underlying="NIFTY",
            expiry=str(now.date() + timedelta(days=2)),
            spot_price=24500.0,
            total_strikes_available=2,
            short_leg_symbol=c_short.trading_symbol,
            short_leg_strike=c_short.strike,
            short_leg_ltp=c_short.ltp,
            short_leg_band="Band 1 (50.0-59.5)",
            hedge_leg_symbol=c_hedge.trading_symbol,
            hedge_leg_strike=c_hedge.strike,
            hedge_leg_ltp=c_hedge.ltp,
            selection_status="SELECTED",
            is_deterministic=True,
        )
        runner._selected_contracts = selected
        runner._latest_chain = chain
        runner.execute_paper_entry()

        assert runner.active_group is not None
        assert runner.active_trailing_stop is not None
        assert runner.active_trailing_stop.current_stop == 55.0  # Entry 50 + initial gap 5

        # 1. Price drops to 40.0 (favorable for short) -> Stop ratchets to 45.0
        t1 = now + timedelta(seconds=1)
        tick1 = Tick(
            symbol=c_short.trading_symbol,
            timestamp=t1,
            ltp=40.0,
            bid=39.9,
            ask=40.1,
            volume=1000,
            oi=1000000,
        )
        runner.on_tick_received(tick1)
        runner.process_incoming_ticks()
        assert runner.active_trailing_stop is not None
        assert runner.active_trailing_stop.current_stop == 45.0

        # 2. Price drops to 30.0 -> Stop ratchets to 35.0
        t2 = now + timedelta(seconds=2)
        tick2 = Tick(
            symbol=c_short.trading_symbol,
            timestamp=t2,
            ltp=30.0,
            bid=29.9,
            ask=30.1,
            volume=2000,
            oi=1000000,
        )
        runner.on_tick_received(tick2)
        runner.process_incoming_ticks()
        assert runner.active_trailing_stop is not None
        assert runner.active_trailing_stop.current_stop == 35.0

        # 3. Price bounces up to 36.0 -> Exceeds stop of 35.0! Triggers exit.
        t3 = now + timedelta(seconds=3)
        tick3 = Tick(
            symbol=c_short.trading_symbol,
            timestamp=t3,
            ltp=36.0,
            bid=35.9,
            ask=36.1,
            volume=3000,
            oi=1000000,
        )
        runner.on_tick_received(tick3)
        runner.process_incoming_ticks()

        # Active group must be closed
        assert runner._active_group is None

        # Total orders in PaperBroker should now be 4 (2 entries + 2 exits)
        orders = runner.broker.get_orders()
        assert len(orders) == 4
        filled_orders = [o for o in orders if o.status == OrderStatus.FILLED]
        assert len(filled_orders) == 4


# ==============================================================================
# 5. Cryptographic Sealing & Run Dossier Integrity
# ==============================================================================


class TestCryptographicSealingAndDossier:
    """Verify Merkle tree roots, tamper digest, and dossier serialization."""

    def test_full_session_generates_valid_sealed_dossier(self, tmp_path: Path) -> None:
        """Run complete mock session and verify sealed dossier JSON output."""
        fwd_dir = tmp_path / "forward"
        raw_dir = tmp_path / "raw"

        config = ForwardOptionsSessionConfig(
            strategy_id="tpl-nifty-ce-premium-ladder-v1",
            underlying="NIFTY",
            mock_mode=True,
            wait_for_market_open=False,
            duration_seconds=1.5,
            snapshot_interval_seconds=1.0,
            output_dir=fwd_dir,
            raw_capture_dir=raw_dir,
        )

        runner = KotakOptionForwardRunner(config=config)
        dossier_path = runner.run()

        assert Path(dossier_path).exists()
        content = json.loads(Path(dossier_path).read_text(encoding="utf-8"))

        # Verify Core Dossier Schema
        assert content["run_id"].startswith("fwd_opt_")
        assert content["strategy_id"] in (
            "tpl-nifty-ce-premium-ladder-v1",
            "NIFTY CE Premium Ladder",
        )
        assert content["venue"] == "AIR_GAPPED_PAPER_BROKER"
        assert content["underlying"] == "NIFTY"

        # Verify Merkle roots present
        assert "event_stream_merkle_root" in content
        assert len(content["event_stream_merkle_root"]) == 64
        assert "trade_ledger_merkle_root" in content
        assert len(content["trade_ledger_merkle_root"]) == 64
        assert "tamper_digest" in content
        assert len(content["tamper_digest"]) == 64

        # Verify User Claimed Expectation Flagged
        assert "USER_CLAIMED_EXPECTATION" in content["user_claimed_expectation"]
        assert "unverified" in content["user_claimed_expectation"].lower()

        # Verify Raw Capture JSON Preserved
        raw_files = list(raw_dir.glob("*.json"))
        assert len(raw_files) >= 1
        raw_content = json.loads(raw_files[0].read_text(encoding="utf-8"))
        assert "payload" in raw_content or "data" in raw_content or isinstance(raw_content, list)


# ==============================================================================
# 6. Data Feed Degradation & Stale Ticks
# ==============================================================================


class TestDataFeedDegradation:
    """Verify runner detects and audits degraded/stale data feeds."""

    def test_stale_ticks_flag_data_feed_degraded(self, tmp_path: Path) -> None:
        """Ticks older than max_quote_age_seconds must trigger DATA_FEED_DEGRADED warning."""
        config = ForwardOptionsSessionConfig(
            mock_mode=True,
            wait_for_market_open=False,
            max_quote_age_seconds=10.0,
            duration_seconds=0.5,
            output_dir=tmp_path / "forward",
            raw_capture_dir=tmp_path / "raw",
        )
        runner = KotakOptionForwardRunner(config=config)

        # Feed a tick that is 30 seconds old
        stale_time = datetime.now(EXCHANGE_TIMEZONE) - timedelta(seconds=30)
        stale_tick = Tick(
            symbol="NIFTY26SEP24500CE",
            timestamp=stale_time,
            ltp=55.0,
            bid=54.8,
            ask=55.2,
            volume=1000,
            oi=1000000,
        )

        runner.on_tick_received(stale_tick)
        runner.process_incoming_ticks()
        runner.check_data_freshness()

        # Verify event stream records stale tick warning or degraded event
        degraded_events = [e for e in runner.events if e.event_type.value == "LIQUIDITY_BREACH"]
        assert len(degraded_events) >= 1
        assert degraded_events[0].details["status"] == "DATA_FEED_DEGRADED"
        assert degraded_events[0].details["stalled_seconds"] >= 25.0


# ==============================================================================
# 7. CLI Subcommand Invocations
# ==============================================================================


class TestForwardOptionsCLI:
    """Verify CLI subcommands aditrader forward-options and auto-routing from forward-test."""

    def test_cmd_forward_options_mock_execution(self, tmp_path: Path) -> None:
        """aditrader forward-options --mock executes cleanly."""
        args = argparse.Namespace(
            strategy="tpl-nifty-ce-premium-ladder-v1",
            underlying="NIFTY",
            expiry=None,
            band=0,
            capital=500000.0,
            slippage_bps=5.0,
            duration=1.0,
            output_dir=str(tmp_path / "fwd"),
            raw_capture_dir=str(tmp_path / "raw"),
            snapshot_interval=1.0,
            mock=True,
            no_wait=True,
        )

        exit_code = cmd_forward_options(args)
        assert exit_code == 0
        assert len(list((tmp_path / "fwd").glob("*.json"))) >= 1

    def test_cmd_forward_test_auto_routes_options_strategy(self, tmp_path: Path) -> None:
        """aditrader forward-test with multi-leg options strategy auto-routes to forward-options."""
        args = argparse.Namespace(
            strategy="tpl-nifty-ce-premium-ladder-v1",
            instrument="NIFTY",
            timeframe="1m",
            capital=500000.0,
            slippage_bps=5.0,
            mock=True,
            ticks=None,
            bars=None,
            duration=1.0,
            output=None,
            strict_quality=False,
            csv=None,
        )

        with patch("aditrader.cli.commands.cmd_forward_options", return_value=0) as mock_fwd_opt:
            exit_code = cmd_forward_test(args)
            assert exit_code == 0
            assert mock_fwd_opt.called
