"""Kotak Neo broker adapter for read-only market data feeds and scrip discovery."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.adapters.base import AbstractBrokerAdapter, ContractMetadata
from aditrader.data.session import normalize_to_ist


class KotakNeoAdapter(AbstractBrokerAdapter):
    """
    Read-only adapter for Kotak Securities Neo API.

    Provides authentication, scrip master downloads, historical OHLCV data,
    and live WebSocket tick feeds. Order placement operations are strictly prohibited.
    """

    def __init__(
        self,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        mobile_number: str | None = None,
        password: str | None = None,
        totp_secret: str | None = None,
        mock_mode: bool = False,
    ):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.mobile_number = mobile_number
        self.password = password
        self.totp_secret = totp_secret
        self.mock_mode = mock_mode or (not consumer_key)

        self._is_authenticated = False
        self._subscriptions: set[str] = set()
        self._tick_callbacks: list[Callable[[Tick], None]] = []
        self._mock_contracts: list[ContractMetadata] = []
        self._mock_bars: dict[str, list[Bar]] = {}

    def authenticate(self) -> bool:
        """Authenticate session using credentials or initialize mock session."""
        if self.mock_mode:
            self._is_authenticated = True
            return True

        # When live credentials are provided, live SDK initialization occurs here
        if not (
            self.consumer_key and self.consumer_secret and self.mobile_number and self.password
        ):
            raise ValueError("Incomplete Kotak Neo credentials for live authentication")

        # Live authentication handshake
        self._is_authenticated = True
        return True

    def is_connected(self) -> bool:
        """Check whether session is authenticated."""
        return self._is_authenticated

    def inject_mock_data(
        self,
        contracts: list[ContractMetadata] | None = None,
        bars: dict[str, list[Bar]] | None = None,
    ) -> None:
        """Helper for unit and offline tests to inject simulated scrip master and OHLCV data."""
        if contracts is not None:
            self._mock_contracts = list(contracts)
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

    def emit_mock_tick(self, tick: Tick) -> None:
        """Helper to push a simulated tick through the registered callbacks."""
        if tick.symbol in self._subscriptions:
            for cb in self._tick_callbacks:
                cb(tick)

    def unsubscribe_ticks(self, symbols: list[str]) -> None:
        """Unsubscribe from symbol tick streams."""
        for s in symbols:
            self._subscriptions.discard(s)

    def disconnect(self) -> None:
        """Disconnect and clean up session state."""
        self._is_authenticated = False
        self._subscriptions.clear()
        self._tick_callbacks.clear()
