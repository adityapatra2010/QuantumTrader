"""Instrument Search Service orchestrating indexing, discovery, and persistent caching."""

from datetime import datetime
from pathlib import Path
from typing import Literal

import pyarrow as pa
import pyarrow.parquet as pq

from aditrader.data.adapters.base import AbstractBrokerAdapter, ContractMetadata
from aditrader.data.instruments.index import InstrumentIndex
from aditrader.data.instruments.models import (
    DerivativesHierarchy,
    InstrumentFilter,
    SearchResult,
)
from aditrader.data.session import normalize_to_ist


class InstrumentSearchService:
    """Unified service managing contract master discovery, persistent caching, and search queries."""

    def __init__(
        self,
        adapter: AbstractBrokerAdapter | None = None,
        contracts: list[ContractMetadata] | None = None,
    ) -> None:
        self._adapter = adapter
        self._index = InstrumentIndex(contracts=contracts)

    @property
    def index(self) -> InstrumentIndex:
        """Access the underlying in-memory index."""
        return self._index

    def load_from_adapter(self, adapter: AbstractBrokerAdapter | None = None) -> int:
        """Fetch scrip master from broker adapter and index all discovered contracts."""
        target_adapter = adapter or self._adapter
        if not target_adapter:
            raise ValueError("No broker adapter provided to fetch scrip master.")

        contracts = target_adapter.fetch_scrip_master()
        self._index.clear()
        self._index.add_contracts(contracts)
        return len(contracts)

    def load_from_contracts(self, contracts: list[ContractMetadata]) -> int:
        """Load and index contracts directly from memory."""
        self._index.clear()
        self._index.add_contracts(contracts)
        return len(contracts)

    def save_to_parquet(self, file_path: str | Path) -> Path:
        """Serialize indexed contract master records into a persistent Parquet file."""
        target_path = Path(file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        contracts = self._index._contracts
        symbols = [c.symbol for c in contracts]
        trading_symbols = [c.trading_symbol for c in contracts]
        exchanges = [c.exchange for c in contracts]
        inst_types = [c.instrument_type for c in contracts]
        lot_sizes = [c.lot_size for c in contracts]
        tick_sizes = [c.tick_size for c in contracts]
        tokens = [c.token for c in contracts]
        strikes = [c.strike_price for c in contracts]
        expiries = [c.expiry_date.isoformat() if c.expiry_date else None for c in contracts]
        option_types = [c.option_type for c in contracts]

        table = pa.Table.from_arrays(
            [
                pa.array(symbols, pa.string()),
                pa.array(trading_symbols, pa.string()),
                pa.array(exchanges, pa.string()),
                pa.array(inst_types, pa.string()),
                pa.array(lot_sizes, pa.int64()),
                pa.array(tick_sizes, pa.float64()),
                pa.array(tokens, pa.string()),
                pa.array(strikes, pa.float64()),
                pa.array(expiries, pa.string()),
                pa.array(option_types, pa.string()),
            ],
            names=[
                "symbol",
                "trading_symbol",
                "exchange",
                "instrument_type",
                "lot_size",
                "tick_size",
                "token",
                "strike_price",
                "expiry_date",
                "option_type",
            ],
        )

        pq.write_table(table, target_path, compression="zstd")
        return target_path

    def load_from_parquet(self, file_path: str | Path) -> int:
        """Load and index contract master from a cached Parquet file."""
        target_path = Path(file_path)
        if not target_path.is_file():
            raise FileNotFoundError(f"Parquet scrip cache not found at: {target_path}")

        table = pq.read_table(target_path)
        data = table.to_pydict()

        contracts: list[ContractMetadata] = []
        n_rows = len(data["symbol"])

        for i in range(n_rows):
            exp_str = data["expiry_date"][i]
            expiry_dt = normalize_to_ist(datetime.fromisoformat(exp_str)) if exp_str else None

            opt_raw = data["option_type"][i]
            opt_type = opt_raw if opt_raw in ("CE", "PE") else None

            contracts.append(
                ContractMetadata(
                    symbol=data["symbol"][i],
                    trading_symbol=data["trading_symbol"][i],
                    exchange=data["exchange"][i],
                    instrument_type=data["instrument_type"][i],
                    lot_size=int(data["lot_size"][i]),
                    tick_size=float(data["tick_size"][i]),
                    token=str(data["token"][i]),
                    strike_price=float(data["strike_price"][i])
                    if data["strike_price"][i] is not None
                    else None,
                    expiry_date=expiry_dt,
                    option_type=opt_type,
                )
            )

        self._index.clear()
        self._index.add_contracts(contracts)
        return len(contracts)

    def search(
        self,
        query: str,
        filters: InstrumentFilter | None = None,
        limit: int = 20,
        evaluation_time: datetime | None = None,
    ) -> list[SearchResult]:
        """Execute deterministic scored search across indexed instruments."""
        return self._index.search(
            query=query, filters=filters, limit=limit, evaluation_time=evaluation_time
        )

    def resolve_derivative(
        self,
        underlying: str,
        contract_type: Literal["FUT", "CE", "PE"],
        expiry: datetime,
        strike: float | None = None,
    ) -> ContractMetadata | None:
        """Hierarchically resolve a specific derivative contract."""
        return self._index.resolve_derivative(
            underlying=underlying,
            contract_type=contract_type,
            expiry=expiry,
            strike=strike,
        )

    def get_derivatives_hierarchy(self, underlying: str) -> DerivativesHierarchy | None:
        """Retrieve structured derivatives map for an underlying asset."""
        return self._index.get_derivatives_hierarchy(underlying=underlying)

    def get_expiries(
        self, underlying: str, contract_type: Literal["FUT", "OPT"] | None = None
    ) -> list[datetime]:
        """Get sorted expiration datetimes for an underlying."""
        return self._index.get_expiries(underlying=underlying, contract_type=contract_type)

    def get_strikes(self, underlying: str, expiry: datetime) -> list[float]:
        """Get sorted strike prices for an underlying on a given expiry date."""
        return self._index.get_strikes(underlying=underlying, expiry=expiry)

    def get_option_pair(
        self, underlying: str, expiry: datetime, strike: float
    ) -> tuple[ContractMetadata | None, ContractMetadata | None]:
        """Retrieve CE and PE contract pair for a specific strike and expiry."""
        return self._index.get_option_pair(underlying=underlying, expiry=expiry, strike=strike)

    def get_underlyings(self) -> list[str]:
        """Return sorted list of all indexed underlying asset symbols."""
        return self._index.get_underlyings()

    def get_by_symbol(self, symbol: str) -> ContractMetadata | None:
        """Retrieve contract by unique symbol identifier."""
        return self._index.get_by_symbol(symbol=symbol)

    def get_by_token(self, token: str, exchange: str | None = None) -> ContractMetadata | None:
        """Retrieve contract by exchange token ID."""
        return self._index.get_by_token(token=token, exchange=exchange)
