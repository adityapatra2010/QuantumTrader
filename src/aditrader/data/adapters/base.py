"""Abstract broker adapter interface and normalized contract metadata schemas."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.market_data import Bar, Tick


class ContractMetadata(BaseModel):
    """Normalized contract definition discovered from broker scrip master."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(description="Unique internal contract identifier, e.g., NIFTY24DEC24000CE")
    trading_symbol: str = Field(
        description="Exchange trading symbol, e.g., NIFTY 26-DEC-2024 CE 24000"
    )
    exchange: str = Field(default="NSE", description="Exchange segment, e.g. NSE, NFO, CDS")
    instrument_type: str = Field(
        description="Instrument classification, e.g., EQ, OPTIDX, FUTIDX, OPTSTK, FUTSTK"
    )
    lot_size: int = Field(gt=0, description="Exchange designated minimum trading lot size")
    tick_size: float = Field(default=0.05, gt=0, description="Minimum price movement increment")
    token: str = Field(description="Broker / exchange internal security token id")
    strike_price: float | None = Field(
        default=None, description="Strike price for options derivatives"
    )
    expiry_date: datetime | None = Field(
        default=None, description="Expiration date-time for derivatives"
    )
    option_type: Literal["CE", "PE"] | None = Field(
        default=None, description="Call or Put option type"
    )


class AbstractBrokerAdapter(ABC):
    """
    Read-only broker adapter interface for market data and contract metadata discovery.

    Architectural Guardrail:
    Real-order routing methods are strictly barred from this interface (ADR 002).
    """

    @abstractmethod
    def authenticate(self) -> bool:
        """Perform vendor authentication (TOTP/MPIN) and establish session."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if adapter is currently authenticated with active session."""
        pass

    @abstractmethod
    def fetch_scrip_master(self) -> list[ContractMetadata]:
        """Download and parse broker scrip master into normalized ContractMetadata."""
        pass

    @abstractmethod
    def fetch_historical_bars(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "1m",
    ) -> list[Bar]:
        """Fetch historical OHLCV bars for a specified symbol and window."""
        pass

    @abstractmethod
    def subscribe_ticks(
        self,
        symbols: list[str],
        callback: Callable[[Tick], None],
    ) -> None:
        """Register live tick streaming subscription with callback handler."""
        pass

    @abstractmethod
    def unsubscribe_ticks(self, symbols: list[str]) -> None:
        """Unsubscribe from live tick streaming for symbols."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Terminate WebSocket connections and invalidate sessions."""
        pass

    # --------------------------------------------------------------------------
    # Architectural Guardrail: Order Placement Prohibited
    # --------------------------------------------------------------------------

    def place_order(self, *args: Any, **kwargs: Any) -> Any:
        """Absolute architectural guardrail: Broker adapters must NEVER route real orders."""
        raise NotImplementedError(
            "CRITICAL SECURITY VETO: Real order execution is strictly barred on broker adapters (ADR 002). "
            "All trading must execute through core.PaperBroker."
        )
