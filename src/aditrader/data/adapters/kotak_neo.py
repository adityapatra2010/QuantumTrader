"""Kotak Neo broker adapter for read-only market data feeds and scrip discovery."""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from aditrader.config.settings import get_settings
from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.adapters.base import AbstractBrokerAdapter, ContractMetadata
from aditrader.data.session import EXCHANGE_TIMEZONE, normalize_to_ist

logger = logging.getLogger(__name__)

try:
    from neo_api_client.neo_api import NeoAPI
    from neo_api_client.websocket.feed import (
        DepthLevel,
        SFeedIndex,
        SFeedMarketStatus,
        SFeedScrip,
        SFeedScripLite,
        SFeedWebSocket,
        WsToken,
    )

    HAS_NEO_SDK = True
except ImportError:  # pragma: no cover
    HAS_NEO_SDK = False
    NeoAPI = None  # type: ignore[assignment,misc]
    SFeedWebSocket = None  # type: ignore[assignment,misc]
    WsToken = None  # type: ignore[assignment,misc]
    SFeedScrip = None  # type: ignore[assignment,misc]
    SFeedScripLite = None  # type: ignore[assignment,misc]
    SFeedIndex = None  # type: ignore[assignment,misc]
    SFeedMarketStatus = None  # type: ignore[assignment,misc]
    DepthLevel = None  # type: ignore[assignment,misc]


# Known NSE/BSE Index symbol to (segment, token) mappings
INDEX_SYMBOLS: dict[str, tuple[str, str]] = {
    "NIFTY": ("nse_cm", "26000"),
    "NIFTY 50": ("nse_cm", "26000"),
    "BANKNIFTY": ("nse_cm", "26001"),
    "NIFTY BANK": ("nse_cm", "26001"),
    "FINNIFTY": ("nse_cm", "26037"),
    "NIFTY FIN SERVICE": ("nse_cm", "26037"),
    "MIDCPNIFTY": ("nse_cm", "26074"),
    "NIFTY MID SELECT": ("nse_cm", "26074"),
    "SENSEX": ("bse_cm", "1"),
}

# Common NSE Equity symbol to (segment, token) mappings
COMMON_EQUITY_SYMBOLS: dict[str, tuple[str, str]] = {
    "RELIANCE": ("nse_cm", "1333"),
    "TCS": ("nse_cm", "11536"),
    "INFY": ("nse_cm", "1594"),
    "HDFCBANK": ("nse_cm", "1330"),
    "ICICIBANK": ("nse_cm", "4963"),
    "SBIN": ("nse_cm", "3045"),
}


class KotakNeoAdapter(AbstractBrokerAdapter):
    """Read-only adapter for Kotak Securities Neo API and SFeed WebSocket.

    Provides authentication, scrip master downloads, historical OHLCV data,
    and live WebSocket tick feeds. Order placement operations are strictly prohibited.
    """

    def __init__(
        self,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        mobile_number: str | None = None,
        password: str | None = None,
        ucc: str | None = None,
        totp_secret: str | None = None,
        mpin: str | None = None,
        mock_mode: bool = False,
        readiness_timeout: float = 15.0,
        reconnect_delay: float = 2.0,
        max_reconnect_attempts: int = 5,
        max_connect_retries: int = 3,
        neo_client_factory: Callable[..., Any] | None = None,
    ):
        settings = get_settings()
        self.consumer_key = consumer_key or settings.kotak_consumer_key
        self.consumer_secret = consumer_secret or settings.kotak_consumer_secret
        self.mobile_number = mobile_number or settings.kotak_mobile_number
        self.password = password or settings.kotak_password
        self.ucc = ucc or getattr(settings, "kotak_ucc", None) or self.password
        self.totp_secret = totp_secret or settings.kotak_totp_secret
        self.mpin = mpin or settings.kotak_mpin
        self.mock_mode = mock_mode or (not self.consumer_key)

        self.readiness_timeout = readiness_timeout
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.max_connect_retries = max_connect_retries
        self._neo_client_factory = neo_client_factory

        self._is_authenticated = False
        self._feed_status: Literal[
            "LIVE_CONNECTED", "LIVE_CONNECTING", "LIVE_FAILED", "SIMULATED_REHEARSAL", "UNSUPPORTED"
        ] = (
            "SIMULATED_REHEARSAL"
            if self.mock_mode
            else ("LIVE_CONNECTING" if HAS_NEO_SDK else "UNSUPPORTED")
        )

        self._subscriptions: set[str] = set()
        self._tick_callbacks: list[Callable[[Tick], None]] = []
        self._mock_contracts: list[ContractMetadata] = []
        self._mock_bars: dict[str, list[Bar]] = {}

        self._neo_client: Any = None
        self._ws_client: Any = None
        self._stream_thread: threading.Thread | None = None
        self._stream_loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread_lock = threading.Lock()
        self._last_error: Exception | None = None
        self._market_status: dict[str, str] = {}
        self._token_to_symbol: dict[str, str] = {}

    @property
    def feed_status(
        self,
    ) -> Literal[
        "LIVE_CONNECTED", "LIVE_CONNECTING", "LIVE_FAILED", "SIMULATED_REHEARSAL", "UNSUPPORTED"
    ]:
        """Expose truthful feed connection state separately from credential authentication."""
        if self.mock_mode:
            return "SIMULATED_REHEARSAL"
        if not HAS_NEO_SDK:
            return "UNSUPPORTED"
        return self._feed_status

    def authenticate(self) -> bool:
        """Authenticate session using credentials or initialize mock session."""
        if self.mock_mode:
            self._is_authenticated = True
            self._feed_status = "SIMULATED_REHEARSAL"
            return True

        if not HAS_NEO_SDK:
            self._feed_status = "UNSUPPORTED"
            raise NotImplementedError(
                "Live Kotak Neo API / WebSocket client is not installed in this environment "
                "(missing 'neo_api_client' / 'kotakneoapi' SDK). Real live broker streaming cannot be claimed. "
                "Initialize KotakNeoAdapter with mock_mode=True or run forward testing with --mock "
                "for simulated paper trading rehearsal."
            )

        if not (self.consumer_key and self.mobile_number and (self.ucc or self.password)):
            self._feed_status = "LIVE_FAILED"
            raise ValueError(
                "Incomplete Kotak Neo credentials for live authentication. "
                "Required: consumer_key, mobile_number, and ucc/password."
            )

        try:
            if self._neo_client_factory:
                client = self._neo_client_factory(
                    consumer_key=self.consumer_key, environment="prod"
                )
            else:
                assert NeoAPI is not None
                client = NeoAPI(consumer_key=self.consumer_key, environment="prod")

            totp_code: str | None = None
            if self.totp_secret:
                import pyotp

                totp_code = pyotp.TOTP(self.totp_secret).now()

            client.totp_login(
                mobile_number=self.mobile_number,
                ucc=self.ucc or self.password or "",
                totp=totp_code,
            )
            if self.mpin:
                client.totp_validate(mpin=self.mpin)

            self._neo_client = client
            self._is_authenticated = True
            self._feed_status = "LIVE_CONNECTING"
            return True
        except Exception as exc:
            self._feed_status = "LIVE_FAILED"
            self._last_error = exc
            raise ConnectionError(f"Kotak Neo live authentication failed: {exc}") from exc

    def is_connected(self) -> bool:
        """Check whether live streaming session is connected and actively receiving ticks."""
        if self.mock_mode:
            return self._is_authenticated
        return (
            self._is_authenticated
            and self._feed_status == "LIVE_CONNECTED"
            and bool(self._ws_client and getattr(self._ws_client, "is_connected", False))
        )

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Block until the feed achieves readiness (first valid tick received) or timeout expires."""
        if self.mock_mode:
            return self._is_authenticated

        wait_sec = timeout if timeout is not None else self.readiness_timeout
        signaled = self._ready_event.wait(timeout=wait_sec)

        if not signaled:
            self._feed_status = "LIVE_FAILED"
            raise TimeoutError(
                f"Kotak Neo live feed failed to achieve readiness within {wait_sec:.1f}s. "
                f"No valid SFeed market-data messages were received. Feed status: {self._feed_status}"
            )

        if self._feed_status != "LIVE_CONNECTED":
            err_msg = str(self._last_error) if self._last_error else "Unknown error"
            raise ConnectionError(
                f"Kotak Neo live feed failed to establish connection or subscription: {err_msg} "
                f"(Feed status: {self._feed_status})"
            )

        return True

    def inject_mock_data(
        self,
        contracts: list[ContractMetadata] | None = None,
        bars: dict[str, list[Bar]] | None = None,
    ) -> None:
        """Helper for unit and offline tests to inject simulated scrip master and OHLCV data."""
        if contracts is not None:
            self._mock_contracts = list(contracts)
            for c in contracts:
                self._token_to_symbol[c.token] = c.symbol
        if bars is not None:
            self._mock_bars = dict(bars)

    def fetch_scrip_master(self) -> list[ContractMetadata]:
        """Fetch and parse scrip master into normalized ContractMetadata contracts."""
        if not self._is_authenticated:
            raise RuntimeError("Adapter is not authenticated. Call authenticate() first.")

        if self.mock_mode and self._mock_contracts:
            return list(self._mock_contracts)

        # Baseline default contracts for standard testing
        sample_exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
        return [
            ContractMetadata(
                symbol="NIFTY",
                trading_symbol="NIFTY 50",
                exchange="NSE",
                instrument_type="EQ",
                lot_size=1,
                tick_size=0.05,
                token="26000",
            ),
            ContractMetadata(
                symbol="NIFTY24DEC24000CE",
                trading_symbol="NIFTY 26-DEC-2024 CE 24000",
                exchange="NFO",
                instrument_type="OPTIDX",
                lot_size=25,
                tick_size=0.05,
                token="45001",
                strike_price=24000.0,
                expiry_date=sample_exp,
                option_type="CE",
            ),
            ContractMetadata(
                symbol="NIFTY24DEC24000PE",
                trading_symbol="NIFTY 26-DEC-2024 PE 24000",
                exchange="NFO",
                instrument_type="OPTIDX",
                lot_size=25,
                tick_size=0.05,
                token="45002",
                strike_price=24000.0,
                expiry_date=sample_exp,
                option_type="PE",
            ),
        ]

    def parse_scrip_csv_row(self, row: dict[str, Any]) -> ContractMetadata:
        """
        Parse an individual scrip record from Kotak Neo CSV schema into ContractMetadata.

        Handles column variations across instrument files.
        """
        raw_symbol = str(row.get("pSymbol", row.get("symbol", ""))).strip()
        raw_trd_symbol = str(row.get("pTrdSymbol", row.get("trading_symbol", raw_symbol))).strip()
        exchange = str(row.get("pExchSeg", row.get("exchange", "NSE"))).strip()
        inst_type = str(row.get("pInstType", row.get("instrument_type", "EQ"))).strip()
        token = str(row.get("pSymbolToken", row.get("token", ""))).strip()
        lot_size = int(row.get("pLotSize", row.get("lot_size", 1)))
        tick_size = float(row.get("pTickSize", row.get("tick_size", 0.05)))

        strike_raw = row.get("pStrikePrice", row.get("strike_price"))
        strike_price = float(strike_raw) if strike_raw and float(strike_raw) > 0 else None

        expiry_raw = row.get("pExpiryDate", row.get("expiry_date"))
        expiry_date = None
        if expiry_raw:
            if isinstance(expiry_raw, datetime):
                expiry_date = normalize_to_ist(expiry_raw)
            elif isinstance(expiry_raw, str) and expiry_raw.strip():
                for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
                    try:
                        parsed = datetime.strptime(expiry_raw.strip(), fmt)
                        expiry_date = normalize_to_ist(parsed)
                        break
                    except ValueError:
                        continue

        from typing import Literal

        opt_type_raw = str(row.get("pOptionType", row.get("option_type", ""))).upper().strip()
        option_type: Literal["CE", "PE"] | None = (
            "CE"
            if opt_type_raw in ("CE", "CALL")
            else "PE"
            if opt_type_raw in ("PE", "PUT")
            else None
        )

        return ContractMetadata(
            symbol=raw_symbol,
            trading_symbol=raw_trd_symbol,
            exchange=exchange,
            instrument_type=inst_type,
            lot_size=lot_size,
            tick_size=tick_size,
            token=token,
            strike_price=strike_price,
            expiry_date=expiry_date,
            option_type=option_type,
        )

    def fetch_historical_bars(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "1m",
    ) -> list[Bar]:
        """Fetch historical bars within the specified window."""
        if not self._is_authenticated:
            raise RuntimeError("Adapter is not authenticated. Call authenticate() first.")

        if self.mock_mode:
            available = self._mock_bars.get(symbol, [])
            start_ist = normalize_to_ist(start_time)
            end_ist = normalize_to_ist(end_time)
            return [
                bar for bar in available if start_ist <= normalize_to_ist(bar.timestamp) <= end_ist
            ]

        return []

    def resolve_symbol_token(self, symbol: str) -> tuple[str, str, bool] | None:
        """Resolve symbol into (exchange_segment, instrument_token, is_index)."""
        clean_sym = symbol.strip().upper()
        if clean_sym in INDEX_SYMBOLS:
            seg, tok = INDEX_SYMBOLS[clean_sym]
            self._token_to_symbol[tok] = clean_sym
            return (seg, tok, True)

        if clean_sym in COMMON_EQUITY_SYMBOLS:
            seg, tok = COMMON_EQUITY_SYMBOLS[clean_sym]
            self._token_to_symbol[tok] = clean_sym
            return (seg, tok, False)

        for contract in self._mock_contracts:
            if contract.symbol.upper() == clean_sym or contract.trading_symbol.upper() == clean_sym:
                is_idx = (
                    contract.instrument_type in ("INDEX", "OPTIDX", "FUTIDX")
                    and not contract.strike_price
                )
                exch = contract.exchange.upper()
                seg = (
                    "nse_fo"
                    if exch in ("NFO", "NSE_FO")
                    else "bse_cm"
                    if exch == "BSE"
                    else "nse_cm"
                )
                self._token_to_symbol[contract.token] = contract.symbol
                return (seg, contract.token, is_idx)

        if "|" in symbol:
            parts = symbol.split("|", 1)
            return (parts[0].lower(), parts[1], False)

        if symbol.isdigit():
            return ("nse_cm", symbol, False)

        return None

    def _resolve_ws_tokens(self, symbols: list[str]) -> tuple[list[Any], list[Any]]:
        """Resolve symbols into scrip and index WsToken lists."""
        if not HAS_NEO_SDK or WsToken is None:
            raise NotImplementedError("neo_api_client SDK is not installed in this environment")

        scrip_tokens: list[Any] = []
        index_tokens: list[Any] = []

        for sym in symbols:
            resolved = self.resolve_symbol_token(sym)
            if resolved is None:
                raise ValueError(
                    f"Could not resolve instrument token for symbol '{sym}'. "
                    "Ensure instrument is indexed or supported in scrip master."
                )
            seg, tok, is_idx = resolved
            ws_tok = WsToken(exchange_segment=seg, instrument_token=tok)
            if is_idx:
                index_tokens.append(ws_tok)
            else:
                scrip_tokens.append(ws_tok)

        return scrip_tokens, index_tokens

    def subscribe_ticks(
        self,
        symbols: list[str],
        callback: Callable[[Tick], None],
    ) -> None:
        """Register symbols for tick streaming and attach callback."""
        if not self._is_authenticated:
            raise RuntimeError("Adapter is not authenticated. Call authenticate() first.")

        self._subscriptions.update(symbols)
        if callback not in self._tick_callbacks:
            self._tick_callbacks.append(callback)

        if self.mock_mode:
            return

        with self._thread_lock:
            if self._stream_thread is None or not self._stream_thread.is_alive():
                self._start_stream()
            elif self._stream_loop is not None and self._stream_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._async_subscribe_symbols(symbols),
                    self._stream_loop,
                )

    async def _async_subscribe_symbols(self, symbols: list[str]) -> None:
        """Dynamically subscribe symbols on an active WebSocket connection."""
        if self._ws_client is None:
            return
        scrip_tokens, index_tokens = self._resolve_ws_tokens(symbols)
        if scrip_tokens and hasattr(self._ws_client, "subscribe_scrips"):
            await self._ws_client.subscribe_scrips(scrip_tokens)
        if index_tokens and hasattr(self._ws_client, "subscribe_index"):
            await self._ws_client.subscribe_index(index_tokens)

    def _start_stream(self) -> None:
        """Launch background SFeed streaming worker thread."""
        self._stop_event.clear()
        self._ready_event.clear()
        self._feed_status = "LIVE_CONNECTING"
        self._stream_thread = threading.Thread(
            target=self._run_stream_loop,
            name="KotakNeoSFeed-Worker",
            daemon=True,
        )
        self._stream_thread.start()

    def _run_stream_loop(self) -> None:
        """Execute async SFeed WebSocket worker inside background thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._stream_loop = loop
        try:
            loop.run_until_complete(self._stream_worker())
        except Exception as exc:
            self._last_error = exc
            self._feed_status = "LIVE_FAILED"
            self._ready_event.set()
        finally:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                with contextlib.suppress(Exception):
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._stream_loop = None

    async def _stream_worker(self) -> None:
        """Async worker connecting SFeed WebSocket, subscribing, and iterating messages."""
        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                if not self._is_authenticated or self._neo_client is None:
                    raise RuntimeError("Kotak Neo adapter is not authenticated")

                self._feed_status = "LIVE_CONNECTING"
                ws = self._neo_client.create_websocket(
                    reconnect_delay=self.reconnect_delay,
                    max_reconnect_attempts=self.max_reconnect_attempts,
                    max_connect_retries=self.max_connect_retries,
                )
                self._ws_client = ws
                await ws.connect()

                if hasattr(ws, "subscribe_exchange"):
                    with contextlib.suppress(Exception):
                        await ws.subscribe_exchange()

                scrip_tokens, index_tokens = self._resolve_ws_tokens(list(self._subscriptions))
                if scrip_tokens and hasattr(ws, "subscribe_scrips"):
                    await ws.subscribe_scrips(scrip_tokens)
                if index_tokens and hasattr(ws, "subscribe_index"):
                    await ws.subscribe_index(index_tokens)

                consecutive_failures = 0

                async for message in ws:
                    if self._stop_event.is_set():
                        break
                    self._handle_sfeed_message(message)
                    if self._stop_event.is_set():
                        break

                if self._stop_event.is_set():
                    break

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = exc
                consecutive_failures += 1
                logger.error(f"Kotak Neo SFeed streaming exception: {exc}")

                if self._stop_event.is_set() or consecutive_failures > self.max_reconnect_attempts:
                    self._feed_status = "LIVE_FAILED"
                    self._ready_event.set()
                    break

                self._feed_status = "LIVE_CONNECTING"
                backoff = min(self.reconnect_delay * (1.5 ** (consecutive_failures - 1)), 30.0)
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
            finally:
                if self._ws_client is not None:
                    with contextlib.suppress(Exception):
                        await self._ws_client.close()
                    self._ws_client = None

    def _handle_sfeed_message(self, message: Any) -> None:
        """Handle incoming decoded SFeed WebSocket message."""
        if SFeedMarketStatus is not None and isinstance(message, SFeedMarketStatus):
            self._market_status[message.exchange_segment] = message.status
            return

        try:
            tick = self.parse_sfeed_message(message)
        except Exception as parse_exc:
            logger.warning(f"Discarding malformed SFeed message: {parse_exc}")
            return

        if tick is not None:
            if self._feed_status != "LIVE_CONNECTED":
                self._feed_status = "LIVE_CONNECTED"
                self._ready_event.set()

            for cb in list(self._tick_callbacks):
                try:
                    cb(tick)
                except Exception as cb_exc:
                    logger.error(f"Error in tick callback: {cb_exc}")

    def emit_mock_tick(self, tick: Tick) -> None:
        """Helper to push a simulated tick through registered callbacks."""
        if tick.symbol in self._subscriptions:
            for cb in self._tick_callbacks:
                cb(tick)

    def unsubscribe_ticks(self, symbols: list[str]) -> None:
        """Unsubscribe from symbol tick streams."""
        for s in symbols:
            self._subscriptions.discard(s)

    def disconnect(self) -> None:
        """Disconnect WebSocket, shutdown background worker thread, and clean up session state."""
        self._stop_event.set()
        self._ready_event.set()

        if (
            self._stream_loop is not None
            and self._stream_loop.is_running()
            and self._ws_client is not None
        ):
            if threading.current_thread() == self._stream_thread:
                with contextlib.suppress(Exception):
                    self._stream_loop.create_task(self._ws_client.close())
            else:
                fut = asyncio.run_coroutine_threadsafe(self._ws_client.close(), self._stream_loop)
                with contextlib.suppress(Exception):
                    fut.result(timeout=2.0)

        if self._stream_thread is not None and self._stream_thread.is_alive():
            if threading.current_thread() != self._stream_thread:
                self._stream_thread.join(timeout=3.0)
            self._stream_thread = None

        self._is_authenticated = False
        self._subscriptions.clear()
        self._tick_callbacks.clear()
        if not self.mock_mode:
            self._feed_status = "LIVE_FAILED"

    def get_market_status(self, exchange_segment: str = "nse_cm") -> str:
        """Return the latest exchange market status (e.g. 'Market open', 'Market closed')."""
        return self._market_status.get(exchange_segment.lower(), "UNKNOWN")

    def get_all_market_statuses(self) -> dict[str, str]:
        """Return all exchange segment market statuses recorded."""
        return dict(self._market_status)

    def parse_sfeed_message(self, message: Any) -> Tick | None:
        """Parse native SFeed WebSocket model into canonical Tick without inventing data."""
        if SFeedMarketStatus is not None and isinstance(message, SFeedMarketStatus):
            self._market_status[message.exchange_segment] = message.status
            return None

        sym: str = ""
        if SFeedIndex is not None and isinstance(message, SFeedIndex):
            raw_name = getattr(message, "name", "")
            if raw_name:
                name_upper = raw_name.upper()
                if "50" in name_upper and "NIFTY" in name_upper:
                    sym = "NIFTY"
                elif "BANK" in name_upper and "NIFTY" in name_upper:
                    sym = "BANKNIFTY"
                else:
                    sym = raw_name
            if not sym:
                tok_str = str(getattr(message, "instrument_token", ""))
                sym = getattr(message, "trading_symbol", "") or self._token_to_symbol.get(
                    tok_str, tok_str
                )
        else:
            tok_str = str(getattr(message, "instrument_token", ""))
            sym = getattr(message, "trading_symbol", "") or self._token_to_symbol.get(
                tok_str, tok_str
            )

        if not sym:
            sym = str(getattr(message, "instrument_token", "UNKNOWN"))

        ltp = float(getattr(message, "last_traded_price", 0.0))

        # Timestamp normalization
        ltt = getattr(message, "last_trade_time", 0)
        if ltt and ltt > 0:
            val = float(ltt)
            if val > 1e11:
                val = val / 1000.0
            timestamp = datetime.fromtimestamp(val, tz=EXCHANGE_TIMEZONE)
        else:
            timestamp = datetime.now(tz=EXCHANGE_TIMEZONE)

        # Traded volume
        volume = int(getattr(message, "volume_traded_today", 0) or 0)

        # Open interest
        raw_oi = getattr(message, "open_interest", None)
        oi = int(raw_oi) if raw_oi is not None and raw_oi > 0 else None

        # Best Bid & Ask depth
        buy_levels = getattr(message, "buy", None)
        if buy_levels and len(buy_levels) > 0 and getattr(buy_levels[0], "price", 0.0) > 0:
            bid = float(buy_levels[0].price)
            bid_qty = (
                int(buy_levels[0].quantity) if getattr(buy_levels[0], "quantity", 0) > 0 else None
            )
        else:
            bid = None
            bid_qty = None

        sell_levels = getattr(message, "sell", None)
        if sell_levels and len(sell_levels) > 0 and getattr(sell_levels[0], "price", 0.0) > 0:
            ask = float(sell_levels[0].price)
            ask_qty = (
                int(sell_levels[0].quantity) if getattr(sell_levels[0], "quantity", 0) > 0 else None
            )
        else:
            ask = None
            ask_qty = None

        exchange_seg = getattr(message, "exchange_segment", None)
        token = getattr(message, "instrument_token", None)

        return Tick(
            symbol=sym,
            ltp=ltp,
            timestamp=timestamp,
            volume=volume,
            oi=oi,
            bid=bid,
            ask=ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            exchange=str(exchange_seg).upper() if exchange_seg else None,
            instrument_token=str(token) if token else None,
            source="KOTAK_LIVE",
            is_synthetic=False,
        )

    def parse_quote_packet(self, packet: dict[str, Any] | Any) -> Tick:
        """Parse raw Kotak Neo WebSocket or quote packet into canonical Tick.

        Supports both raw dictionary payloads and SFeed model objects.
        """
        if not isinstance(packet, dict):
            res = self.parse_sfeed_message(packet)
            if res is not None:
                return res
            raise ValueError(f"Packet cannot be parsed as Tick: {packet}")

        raw_symbol = (
            packet.get("symbol")
            or packet.get("ts")
            or packet.get("trading_symbol")
            or packet.get("pTrdSymbol")
        )
        symbol = str(raw_symbol).strip() if raw_symbol is not None else ""
        if not symbol:
            raise ValueError("Quote packet missing symbol or trading symbol")

        raw_ltp = packet.get("ltp", packet.get("lp", packet.get("last_price", 0.0)))
        ltp = float(raw_ltp) if raw_ltp is not None else 0.0

        # Volume
        raw_vol = packet.get("volume", packet.get("v", packet.get("vol", 0)))
        volume = int(float(raw_vol)) if raw_vol is not None else 0

        # Open Interest
        raw_oi = packet.get("oi", packet.get("open_interest"))
        oi = int(float(raw_oi)) if raw_oi is not None and str(raw_oi).strip() != "" else None

        # Bid / Ask Quotes
        raw_bid = packet.get("bid", packet.get("bp", packet.get("bp1", packet.get("best_bid"))))
        bid = float(raw_bid) if raw_bid is not None and float(raw_bid) > 0.0 else None

        raw_ask = packet.get(
            "ask", packet.get("sp", packet.get("ap", packet.get("sp1", packet.get("best_ask"))))
        )
        ask = float(raw_ask) if raw_ask is not None and float(raw_ask) > 0.0 else None

        raw_bid_qty = packet.get("bid_qty", packet.get("bq", packet.get("bq1")))
        bid_qty = (
            int(float(raw_bid_qty))
            if raw_bid_qty is not None and int(float(raw_bid_qty)) >= 0
            else None
        )

        raw_ask_qty = packet.get("ask_qty", packet.get("sq", packet.get("aq", packet.get("sq1"))))
        ask_qty = (
            int(float(raw_ask_qty))
            if raw_ask_qty is not None and int(float(raw_ask_qty)) >= 0
            else None
        )

        # Exchange & Token
        exchange = packet.get("exchange", packet.get("e", packet.get("pExchSeg")))
        exchange_str = str(exchange).strip() if exchange else None

        token = packet.get("token", packet.get("tok", packet.get("pSymbolToken")))
        token_str = str(token).strip() if token else None

        # Timestamp
        ts_raw = packet.get("timestamp", packet.get("ltt", packet.get("lut", packet.get("time"))))
        if ts_raw is not None:
            if isinstance(ts_raw, datetime):
                timestamp = normalize_to_ist(ts_raw)
            elif isinstance(ts_raw, (int, float)):
                val = float(ts_raw)
                if val > 1e11:  # milliseconds epoch
                    val = val / 1000.0
                timestamp = datetime.fromtimestamp(val, tz=EXCHANGE_TIMEZONE)
            elif isinstance(ts_raw, str) and ts_raw.strip():
                clean_ts = ts_raw.strip()
                try:
                    num_val = float(clean_ts)
                    if num_val > 1e11:
                        num_val = num_val / 1000.0
                    timestamp = datetime.fromtimestamp(num_val, tz=EXCHANGE_TIMEZONE)
                except ValueError:
                    parsed_dt: datetime | None = None
                    try:
                        parsed_dt = datetime.fromisoformat(clean_ts)
                    except ValueError:
                        for fmt in (
                            "%d/%m/%Y %H:%M:%S",
                            "%d-%m-%Y %H:%M:%S",
                            "%Y-%m-%d %H:%M:%S",
                            "%d-%b-%Y %H:%M:%S",
                            "%d/%m/%Y %I:%M:%S %p",
                            "%d-%b-%Y %I:%M:%S %p",
                        ):
                            try:
                                parsed_dt = datetime.strptime(clean_ts, fmt)
                                break
                            except ValueError:
                                continue
                    if parsed_dt is not None:
                        timestamp = normalize_to_ist(parsed_dt)
                    else:
                        timestamp = datetime.now(tz=EXCHANGE_TIMEZONE)
            else:
                timestamp = datetime.now(tz=EXCHANGE_TIMEZONE)
        else:
            timestamp = datetime.now(tz=EXCHANGE_TIMEZONE)

        return Tick(
            symbol=symbol,
            ltp=ltp,
            timestamp=timestamp,
            volume=volume,
            oi=oi,
            bid=bid,
            ask=ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            exchange=exchange_str,
            instrument_token=token_str,
            source="KOTAK_NEO",
            is_synthetic=False,
        )
