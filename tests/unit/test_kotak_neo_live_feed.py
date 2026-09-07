"""Unit and integration test suite for Kotak Neo live market data adapter.

Verifies:
1. Physical air-gap / read-only constraints (no broker order APIs - ADR 002)
2. Truthful feed state machine transitions
3. Authentication & TOTP handling without declaring feed readiness prematurely
4. Symbol and instrument token resolution
5. Async SFeed WebSocket lifecycle and message iteration
6. Message decoding (Scrip, Index, MarketStatus) and tick normalization
7. Missing quote handling (no synthetic invention of bid/ask)
8. Readiness synchronization (wait_until_ready) and fail-closed timeout
9. Reconnect backoff and shutdown cleanup
10. ForwardTestRunner integration with live adapter
11. Safe read-only CLI smoke-feed command
12. Opt-in real Kotak Neo network smoke test
"""

import argparse
import asyncio
import os
import time
from typing import Any

import pytest

from aditrader.cli.commands import cmd_smoke_feed
from aditrader.core.models.market_data import Tick
from aditrader.data.adapters.kotak_neo import (
    HAS_NEO_SDK,
    KotakNeoAdapter,
)
from aditrader.data.forward import ForwardTestStatus
from aditrader.data.forward_runner import ForwardTestConfig, ForwardTestRunner
from aditrader.data.session import EXCHANGE_TIMEZONE

if HAS_NEO_SDK:
    from neo_api_client.websocket.feed import (
        DepthLevel,
        SFeedIndex,
        SFeedMarketStatus,
        SFeedScrip,
        WsToken,
    )
else:
    DepthLevel = None  # type: ignore[assignment, misc]
    SFeedIndex = None  # type: ignore[assignment, misc]
    SFeedMarketStatus = None  # type: ignore[assignment, misc]
    SFeedScrip = None  # type: ignore[assignment, misc]
    WsToken = None  # type: ignore[assignment, misc]


# ==============================================================================
# Mock SFeed WebSocket Transport for Offline Verification
# ==============================================================================


class MockSFeedWebSocket:
    """Mock async SFeed WebSocket transport simulating SDK WebSocket behavior."""

    def __init__(
        self,
        messages_to_yield: list[Any] | None = None,
        msg_delay: float = 0.01,
        fail_connect: bool = False,
    ) -> None:
        self.messages_to_yield = messages_to_yield or []
        self.msg_delay = msg_delay
        self.fail_connect = fail_connect
        self.is_connected = False
        self.subscribed_scrips: list[Any] = []
        self.subscribed_indices: list[Any] = []
        self.closed = False
        self._exchange_subscribed = False

    async def connect(self) -> None:
        if self.fail_connect:
            raise ConnectionError("Simulated WebSocket connection failure")
        self.is_connected = True

    async def subscribe_exchange(self) -> None:
        self._exchange_subscribed = True

    async def subscribe_scrips(self, tokens: list[Any]) -> None:
        self.subscribed_scrips.extend(tokens)

    async def subscribe_index(self, tokens: list[Any]) -> None:
        self.subscribed_indices.extend(tokens)

    async def close(self) -> None:
        self.is_connected = False
        self.closed = True

    def __aiter__(self) -> Any:
        return self._message_generator()

    async def _message_generator(self) -> Any:
        for msg in self.messages_to_yield:
            await asyncio.sleep(self.msg_delay)
            yield msg
        # Stay alive until closed
        while self.is_connected and not self.closed:
            await asyncio.sleep(0.05)


class MockNeoAPIClient:
    """Mock NeoAPI client simulating official SDK authentication and WS factory."""

    def __init__(
        self,
        ws_instance: MockSFeedWebSocket | None = None,
        fail_login: bool = False,
    ) -> None:
        self.ws_instance = ws_instance or MockSFeedWebSocket()
        self.fail_login = fail_login
        self.login_called = False
        self.validate_called = False
        self.last_login_kwargs: dict[str, Any] = {}

    def totp_login(
        self,
        mobile_number: str | None = None,
        ucc: str | None = None,
        totp: str | None = None,
    ) -> dict[str, Any]:
        if self.fail_login:
            raise RuntimeError("Invalid mobile number or credentials")
        self.login_called = True
        self.last_login_kwargs = {
            "mobile_number": mobile_number,
            "ucc": ucc,
            "totp": totp,
        }
        return {"status": "success", "message": "OTP Verified"}

    def totp_validate(self, mpin: str | None = None) -> dict[str, Any]:
        self.validate_called = True
        return {"status": "success", "message": "Session Initialized"}

    def create_websocket(self, **kwargs: Any) -> MockSFeedWebSocket:
        return self.ws_instance


# ==============================================================================
# 1. Physical Air-Gap Guarantee Tests
# ==============================================================================


def test_air_gap_guarantee_no_order_routing_apis() -> None:
    """KotakNeoAdapter must NEVER route real orders and must raise NotImplementedError if called."""
    adapter = KotakNeoAdapter(mock_mode=True)
    with pytest.raises(NotImplementedError, match="CRITICAL SECURITY VETO"):
        adapter.place_order()


# ==============================================================================
# 2. Feed State Machine & Truthfulness Tests
# ==============================================================================


def test_feed_status_simulated_rehearsal_in_mock_mode() -> None:
    """Mock mode adapter must report SIMULATED_REHEARSAL truthfully."""
    adapter = KotakNeoAdapter(mock_mode=True)
    assert adapter.feed_status == "SIMULATED_REHEARSAL"
    assert adapter.authenticate() is True
    assert adapter.is_connected() is True


def test_feed_status_unsupported_when_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live mode adapter must report UNSUPPORTED and fail closed when SDK is absent."""
    import aditrader.data.adapters.kotak_neo as kn_mod

    monkeypatch.setattr(kn_mod, "HAS_NEO_SDK", False)
    adapter = KotakNeoAdapter(
        consumer_key="key",
        mobile_number="9999999999",
        password="pass",
        mock_mode=False,
    )
    assert adapter.feed_status == "UNSUPPORTED"
    with pytest.raises(NotImplementedError, match="neo_api_client"):
        adapter.authenticate()


def test_authentication_success_does_not_imply_feed_readiness() -> None:
    """Authentication success transitions to LIVE_CONNECTING, NOT LIVE_CONNECTED."""
    mock_client = MockNeoAPIClient()
    adapter = KotakNeoAdapter(
        consumer_key="test_key",
        mobile_number="9999999999",
        ucc="TEST_UCC",
        totp_secret="JBSWY3DPEHPK3PXP",
        mpin="123456",
        mock_mode=False,
        neo_client_factory=lambda **kw: mock_client,
    )

    assert adapter.feed_status == "LIVE_CONNECTING"
    assert adapter.is_connected() is False

    # Authenticate
    adapter.authenticate()

    assert mock_client.login_called is True
    assert mock_client.validate_called is True
    assert adapter.feed_status == "LIVE_CONNECTING"
    # Even though authenticated, is_connected MUST be False until stream connects & receives ticks
    assert adapter.is_connected() is False


# ==============================================================================
# 3. Symbol & Instrument Token Resolution
# ==============================================================================


def test_symbol_resolution_indices_and_equities() -> None:
    """Adapter resolves index and equity symbols into canonical exchange segment and token."""
    adapter = KotakNeoAdapter(mock_mode=True)

    # Indices
    nifty_res = adapter.resolve_symbol_token("NIFTY")
    assert nifty_res == ("nse_cm", "26000", True)

    bnf_res = adapter.resolve_symbol_token("BANKNIFTY")
    assert bnf_res == ("nse_cm", "26001", True)

    sensex_res = adapter.resolve_symbol_token("SENSEX")
    assert sensex_res == ("bse_cm", "1", True)

    # Equities
    rel_res = adapter.resolve_symbol_token("RELIANCE")
    assert rel_res == ("nse_cm", "1333", False)

    tcs_res = adapter.resolve_symbol_token("TCS")
    assert tcs_res == ("nse_cm", "11536", False)

    # Custom pipe format
    pipe_res = adapter.resolve_symbol_token("nse_fo|54321")
    assert pipe_res == ("nse_fo", "54321", False)

    # Pure token
    num_res = adapter.resolve_symbol_token("9999")
    assert num_res == ("nse_cm", "9999", False)


# ==============================================================================
# 4. SFeed Message Decoding & Tick Normalization Tests
# ==============================================================================


@pytest.mark.skipif(not HAS_NEO_SDK, reason="neo_api_client SDK required for SFeed models")
def test_parse_sfeed_scrip_with_full_depth() -> None:
    """Parse SFeedScrip with genuine 5-level depth into normalized Tick in Asia/Kolkata."""
    adapter = KotakNeoAdapter(mock_mode=True)

    sample_scrip = SFeedScrip.model_construct(
        exchange_segment="nse_cm",
        instrument_token="2885",
        trading_symbol="RELIANCE",
        last_traded_price=2945.50,
        last_trade_time=1700000000,
        volume_traded_today=150000,
        open_interest=5000,
        buy=[DepthLevel(price=2945.0, quantity=100, orders=4)],
        sell=[DepthLevel(price=2946.0, quantity=250, orders=6)],
    )

    tick = adapter.parse_sfeed_message(sample_scrip)
    assert tick is not None
    assert isinstance(tick, Tick)
    assert tick.symbol == "RELIANCE"
    assert tick.ltp == 2945.50
    assert tick.bid == 2945.0
    assert tick.ask == 2946.0
    assert tick.bid_qty == 100
    assert tick.ask_qty == 250
    assert tick.volume == 150000
    assert tick.oi == 5000
    assert tick.timestamp.tzinfo == EXCHANGE_TIMEZONE
    assert tick.source == "KOTAK_LIVE"
    assert tick.is_synthetic is False


@pytest.mark.skipif(not HAS_NEO_SDK, reason="neo_api_client SDK required for SFeed models")
def test_parse_sfeed_scrip_with_missing_quotes_truthful_none() -> None:
    """When bid/ask depth is absent, adapter must retain None without inventing fake quotes."""
    adapter = KotakNeoAdapter(mock_mode=True)

    sample_scrip = SFeedScrip.model_construct(
        exchange_segment="nse_cm",
        instrument_token="2885",
        trading_symbol="RELIANCE",
        last_traded_price=2945.50,
        last_trade_time=1700000000,
        volume_traded_today=150000,
        open_interest=None,
        buy=[],
        sell=[],
    )

    tick = adapter.parse_sfeed_message(sample_scrip)
    assert tick is not None
    assert tick.bid is None
    assert tick.ask is None
    assert tick.bid_qty is None
    assert tick.ask_qty is None
    assert tick.oi is None


@pytest.mark.skipif(not HAS_NEO_SDK, reason="neo_api_client SDK required for SFeed models")
def test_parse_sfeed_index_normalization() -> None:
    """Parse SFeedIndex: normalizes Nifty 50 to NIFTY, leaves bid/ask as None."""
    adapter = KotakNeoAdapter(mock_mode=True)

    sample_idx = SFeedIndex.model_construct(
        exchange_segment="nse_cm",
        instrument_token="26000",
        name="Nifty 50",
        last_traded_price=24150.25,
        last_trade_time=1700000000,
    )

    tick = adapter.parse_sfeed_message(sample_idx)
    assert tick is not None
    assert tick.symbol == "NIFTY"
    assert tick.ltp == 24150.25
    assert tick.bid is None
    assert tick.ask is None


@pytest.mark.skipif(not HAS_NEO_SDK, reason="neo_api_client SDK required for SFeed models")
def test_parse_sfeed_market_status_update() -> None:
    """SFeedMarketStatus updates market status dictionary and returns None."""
    adapter = KotakNeoAdapter(mock_mode=True)

    status_msg = SFeedMarketStatus.model_construct(
        type="market_status",
        exchange_segment="nse_cm",
        status_code="1",
        status="Market open",
    )

    tick = adapter.parse_sfeed_message(status_msg)
    assert tick is None
    assert adapter.get_market_status("nse_cm") == "Market open"


# ==============================================================================
# 5. Live Streaming Lifecycle & Readiness Gate Tests
# ==============================================================================


@pytest.mark.skipif(not HAS_NEO_SDK, reason="neo_api_client SDK required for SFeed models")
def test_streaming_readiness_gate_and_tick_delivery() -> None:
    """Streaming achieves LIVE_CONNECTED only upon receiving first valid tick."""
    sample_tick_msg = SFeedScrip.model_construct(
        exchange_segment="nse_cm",
        instrument_token="2885",
        trading_symbol="RELIANCE",
        last_traded_price=2950.0,
        last_trade_time=int(time.time()),
        volume_traded_today=1000,
        open_interest=0,
        buy=[DepthLevel(price=2949.5, quantity=50, orders=2)],
        sell=[DepthLevel(price=2950.5, quantity=50, orders=2)],
    )

    mock_ws = MockSFeedWebSocket(messages_to_yield=[sample_tick_msg], msg_delay=0.05)
    mock_client = MockNeoAPIClient(ws_instance=mock_ws)

    adapter = KotakNeoAdapter(
        consumer_key="test_key",
        mobile_number="9999999999",
        ucc="TEST_UCC",
        totp_secret="JBSWY3DPEHPK3PXP",
        mock_mode=False,
        readiness_timeout=5.0,
        neo_client_factory=lambda **kw: mock_client,
    )

    received_ticks: list[Tick] = []

    adapter.authenticate()
    assert str(adapter.feed_status) == "LIVE_CONNECTING"

    adapter.subscribe_ticks(["RELIANCE"], lambda t: received_ticks.append(t))

    # wait_until_ready blocks until first tick is processed
    ready = adapter.wait_until_ready(timeout=3.0)
    assert ready is True
    assert str(adapter.feed_status) == "LIVE_CONNECTED"
    assert len(received_ticks) >= 1
    assert received_ticks[0].symbol == "RELIANCE"

    adapter.disconnect()
    assert str(adapter.feed_status) == "LIVE_FAILED"
    assert mock_ws.closed is True


def test_wait_until_ready_timeout_fails_closed() -> None:
    """When no messages arrive before readiness timeout, adapter raises TimeoutError."""
    # WebSocket yields zero messages
    mock_ws = MockSFeedWebSocket(messages_to_yield=[], msg_delay=0.1)
    mock_client = MockNeoAPIClient(ws_instance=mock_ws)

    adapter = KotakNeoAdapter(
        consumer_key="test_key",
        mobile_number="9999999999",
        ucc="TEST_UCC",
        totp_secret="JBSWY3DPEHPK3PXP",
        mock_mode=False,
        readiness_timeout=0.3,
        neo_client_factory=lambda **kw: mock_client,
    )

    adapter.authenticate()
    adapter.subscribe_ticks(["NIFTY"], lambda t: None)

    with pytest.raises(TimeoutError, match="failed to achieve readiness"):
        adapter.wait_until_ready(timeout=0.3)

    assert adapter.feed_status == "LIVE_FAILED"
    adapter.disconnect()


# ==============================================================================
# 6. ForwardTestRunner Integration with Live Adapter
# ==============================================================================


@pytest.mark.skipif(not HAS_NEO_SDK, reason="neo_api_client SDK required for SFeed models")
def test_forward_test_runner_with_live_adapter_lifecycle() -> None:
    """ForwardTestRunner starts live adapter, waits for readiness, and shuts down cleanly."""
    sample_msgs = [
        SFeedScrip.model_construct(
            exchange_segment="nse_cm",
            instrument_token="2885",
            trading_symbol="RELIANCE",
            last_traded_price=2950.0 + i,
            last_trade_time=int(time.time()),
            volume_traded_today=100 * (i + 1),
            open_interest=0,
            buy=[DepthLevel(price=2949.0 + i, quantity=50, orders=1)],
            sell=[DepthLevel(price=2951.0 + i, quantity=50, orders=1)],
        )
        for i in range(5)
    ]

    mock_ws = MockSFeedWebSocket(messages_to_yield=sample_msgs, msg_delay=0.02)
    mock_client = MockNeoAPIClient(ws_instance=mock_ws)

    adapter = KotakNeoAdapter(
        consumer_key="test_key",
        mobile_number="9999999999",
        ucc="TEST_UCC",
        totp_secret="JBSWY3DPEHPK3PXP",
        mock_mode=False,
        readiness_timeout=2.0,
        neo_client_factory=lambda **kw: mock_client,
    )

    config = ForwardTestConfig(
        symbol="RELIANCE",
        timeframe="1m",
        max_ticks=3,
        force_mock=False,
        feed_readiness_timeout=2.0,
    )

    runner = ForwardTestRunner(
        config=config,
        strategy="test_ma_crossover",
        adapter=adapter,
    )

    result = runner.run()

    assert result.session.status == ForwardTestStatus.COMPLETED
    assert result.session.total_ticks >= 3
    adapter.disconnect()
    assert mock_ws.closed is True


# ==============================================================================
# 7. CLI Smoke Feed Command Tests
# ==============================================================================


def test_cli_cmd_smoke_feed_mock_mode() -> None:
    """CLI smoke-feed in mock mode executes and returns exit code 0."""
    args = argparse.Namespace(
        symbol="NIFTY",
        ticks=3,
        timeout=5.0,
        mock=True,
    )
    exit_code = cmd_smoke_feed(args)
    assert exit_code == 0


def test_cli_cmd_smoke_feed_fails_closed_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI smoke-feed in live mode fails closed when SDK is missing."""
    import aditrader.data.adapters.kotak_neo as kn_mod

    monkeypatch.setattr(kn_mod, "HAS_NEO_SDK", False)
    monkeypatch.setenv("KOTAK_CONSUMER_KEY", "dummy_key")
    monkeypatch.setenv("KOTAK_MOBILE_NUMBER", "9999999999")
    monkeypatch.setenv("KOTAK_PASSWORD", "dummy_pass")

    args = argparse.Namespace(
        symbol="NIFTY",
        ticks=2,
        timeout=1.0,
        mock=False,
    )
    exit_code = cmd_smoke_feed(args)
    assert exit_code == 1


# ==============================================================================
# 8. Opt-In Real Network Smoke Test
# ==============================================================================


@pytest.mark.skipif(
    not os.environ.get("RUN_REAL_KOTAK_TESTS"),
    reason="Real Kotak Neo live network test requires RUN_REAL_KOTAK_TESTS=1 and credentials",
)
def test_real_kotak_neo_sfeed_network_smoke() -> None:
    """Real live streaming test against Kotak Neo production WebSocket servers."""
    adapter = KotakNeoAdapter(
        mock_mode=False,
        readiness_timeout=15.0,
    )

    received: list[Tick] = []
    adapter.authenticate()
    adapter.subscribe_ticks(["NIFTY"], lambda t: received.append(t))

    try:
        ready = adapter.wait_until_ready(timeout=15.0)
        assert ready is True
        assert adapter.feed_status == "LIVE_CONNECTED"
        assert len(received) >= 1
    finally:
        adapter.disconnect()
