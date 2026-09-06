"""High-speed in-memory indexing and hierarchical resolution engine for instruments."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from aditrader.data.adapters.base import ContractMetadata
from aditrader.data.instruments.matcher import (
    extract_underlying,
    parse_query,
    score_contract,
)
from aditrader.data.instruments.models import (
    DerivativesHierarchy,
    InstrumentFilter,
    MatchQuality,
    SearchResult,
)
from aditrader.data.session import normalize_to_ist


class InstrumentIndex:
    """In-memory deterministic index for financial instrument discovery and hierarchical resolution."""

    def __init__(self, contracts: Sequence[ContractMetadata] | None = None) -> None:
        self._contracts: list[ContractMetadata] = []
        self._by_symbol: dict[str, ContractMetadata] = {}
        self._by_token: dict[tuple[str, str], ContractMetadata] = {}
        self._token_to_contracts: dict[str, list[ContractMetadata]] = defaultdict(list)
        self._by_underlying: dict[str, list[ContractMetadata]] = defaultdict(list)
        self._underlying_of: dict[str, str] = {}
        self._hierarchies: dict[str, DerivativesHierarchy] = {}
        self._underlyings_sorted: list[str] = []

        if contracts:
            self.add_contracts(contracts)

    def count(self) -> int:
        """Return total indexed contracts."""
        return len(self._contracts)

    def clear(self) -> None:
        """Clear all indexed contracts and cache structures."""
        self._contracts.clear()
        self._by_symbol.clear()
        self._by_token.clear()
        self._token_to_contracts.clear()
        self._by_underlying.clear()
        self._underlying_of.clear()
        self._hierarchies.clear()
        self._underlyings_sorted.clear()

    def add_contracts(self, contracts: Sequence[ContractMetadata]) -> None:
        """Index a sequence of ContractMetadata records into structured lookups."""
        for c in contracts:
            sym_upper = c.symbol.upper()
            self._contracts.append(c)
            self._by_symbol[sym_upper] = c

            exch_upper = c.exchange.upper()
            token_str = str(c.token).strip()
            self._by_token[(exch_upper, token_str)] = c
            self._token_to_contracts[token_str].append(c)

            underlying = extract_underlying(c)
            self._underlying_of[sym_upper] = underlying
            self._by_underlying[underlying].append(c)

        self._underlyings_sorted = sorted(self._by_underlying.keys())
        self._rebuild_hierarchies()

    def _rebuild_hierarchies(self) -> None:
        """Construct structured DerivativesHierarchy for each known underlying."""
        self._hierarchies.clear()

        for und, contracts in self._by_underlying.items():
            equity_contract: ContractMetadata | None = None
            has_equity = False
            fut_expiries: set[datetime] = set()
            opt_expiries: set[datetime] = set()
            all_expiries_set: set[datetime] = set()
            strikes_by_date: dict[str, set[float]] = defaultdict(set)
            lot_sizes: dict[str, int] = {}

            for c in contracts:
                itype = c.instrument_type.upper()
                if itype == "EQ":
                    has_equity = True
                    equity_contract = c
                    lot_sizes["EQ"] = c.lot_size
                elif itype in ("FUTIDX", "FUTSTK"):
                    lot_sizes["FUT"] = c.lot_size
                    if c.expiry_date:
                        exp_ist = normalize_to_ist(c.expiry_date)
                        fut_expiries.add(exp_ist)
                        all_expiries_set.add(exp_ist)
                elif itype in ("OPTIDX", "OPTSTK"):
                    lot_sizes["OPT"] = c.lot_size
                    if c.expiry_date:
                        exp_ist = normalize_to_ist(c.expiry_date)
                        opt_expiries.add(exp_ist)
                        all_expiries_set.add(exp_ist)
                        date_key = exp_ist.strftime("%Y-%m-%d")
                        if c.strike_price is not None:
                            strikes_by_date[date_key].add(c.strike_price)

            sorted_fut = sorted(fut_expiries)
            sorted_opt = sorted(opt_expiries)
            sorted_all = sorted(all_expiries_set)
            sorted_strikes = {d: sorted(s) for d, s in strikes_by_date.items()}

            self._hierarchies[und] = DerivativesHierarchy(
                underlying=und,
                has_equity=has_equity,
                equity_contract=equity_contract,
                has_futures=bool(fut_expiries),
                futures_expiries=sorted_fut,
                has_options=bool(opt_expiries),
                options_expiries=sorted_opt,
                all_expiries=sorted_all,
                strikes_by_expiry=sorted_strikes,
                lot_sizes=lot_sizes,
            )

    def get_by_symbol(self, symbol: str) -> ContractMetadata | None:
        """Retrieve contract by unique symbol identifier."""
        return self._by_symbol.get(symbol.strip().upper())

    def get_by_token(self, token: str, exchange: str | None = None) -> ContractMetadata | None:
        """Retrieve contract by exchange token ID."""
        t_str = str(token).strip()
        if exchange:
            return self._by_token.get((exchange.strip().upper(), t_str))
        candidates = self._token_to_contracts.get(t_str, [])
        return candidates[0] if candidates else None

    def get_underlyings(self) -> list[str]:
        """Return sorted list of all indexed underlying asset symbols."""
        return list(self._underlyings_sorted)

    def get_contracts_for_underlying(self, underlying: str) -> list[ContractMetadata]:
        """Return all contracts associated with an underlying."""
        return list(self._by_underlying.get(underlying.strip().upper(), []))

    def get_derivatives_hierarchy(self, underlying: str) -> DerivativesHierarchy | None:
        """Retrieve structured derivatives mapping for an underlying asset."""
        return self._hierarchies.get(underlying.strip().upper())

    def get_expiries(
        self, underlying: str, contract_type: Literal["FUT", "OPT"] | None = None
    ) -> list[datetime]:
        """Get sorted expiration datetimes for an underlying, optionally filtered by derivative type."""
        h = self.get_derivatives_hierarchy(underlying)
        if not h:
            return []
        if contract_type == "FUT":
            return list(h.futures_expiries)
        if contract_type == "OPT":
            return list(h.options_expiries)
        return list(h.all_expiries)

    def get_strikes(self, underlying: str, expiry: datetime) -> list[float]:
        """Get sorted strike prices for an underlying on a given expiry date."""
        h = self.get_derivatives_hierarchy(underlying)
        if not h:
            return []
        date_key = normalize_to_ist(expiry).strftime("%Y-%m-%d")
        return list(h.strikes_by_expiry.get(date_key, []))

    def resolve_derivative(
        self,
        underlying: str,
        contract_type: Literal["FUT", "CE", "PE"],
        expiry: datetime,
        strike: float | None = None,
    ) -> ContractMetadata | None:
        """Hierarchically resolve a specific derivative contract."""
        contracts = self.get_contracts_for_underlying(underlying)
        target_date_str = normalize_to_ist(expiry).strftime("%Y-%m-%d")

        for c in contracts:
            if not c.expiry_date:
                continue
            c_date_str = normalize_to_ist(c.expiry_date).strftime("%Y-%m-%d")
            if c_date_str != target_date_str:
                continue

            if (contract_type == "FUT" and c.instrument_type in ("FUTIDX", "FUTSTK")) or (
                contract_type in ("CE", "PE")
                and c.instrument_type in ("OPTIDX", "OPTSTK")
                and c.option_type == contract_type
                and strike is not None
                and c.strike_price is not None
                and abs(c.strike_price - strike) < 1e-4
            ):
                return c

        return None

    def get_option_pair(
        self, underlying: str, expiry: datetime, strike: float
    ) -> tuple[ContractMetadata | None, ContractMetadata | None]:
        """Retrieve CE and PE contract pair for a specific strike and expiry."""
        ce = self.resolve_derivative(underlying, "CE", expiry, strike)
        pe = self.resolve_derivative(underlying, "PE", expiry, strike)
        return ce, pe

    def _matches_filters(self, contract: ContractMetadata, filters: InstrumentFilter) -> bool:
        """Check if contract satisfies user-supplied InstrumentFilter constraints."""
        if filters.exchange and contract.exchange.upper() != filters.exchange.upper():
            return False

        if filters.instrument_types and contract.instrument_type.upper() not in [
            t.upper() for t in filters.instrument_types
        ]:
            return False

        if filters.underlying:
            contract_und = self._underlying_of.get(contract.symbol.upper())
            if contract_und != filters.underlying.upper():
                return False

        if filters.option_type and contract.option_type != filters.option_type:
            return False

        if filters.strike_min is not None and (
            contract.strike_price is None or contract.strike_price < filters.strike_min
        ):
            return False

        if filters.strike_max is not None and (
            contract.strike_price is None or contract.strike_price > filters.strike_max
        ):
            return False

        if filters.expiry_min is not None and (
            contract.expiry_date is None
            or normalize_to_ist(contract.expiry_date) < normalize_to_ist(filters.expiry_min)
        ):
            return False

        return not (
            filters.expiry_max is not None
            and (
                contract.expiry_date is None
                or normalize_to_ist(contract.expiry_date) > normalize_to_ist(filters.expiry_max)
            )
        )

    def search(
        self,
        query: str,
        filters: InstrumentFilter | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Execute deterministic scored search across indexed instruments."""
        parsed = parse_query(query)
        has_query = bool(parsed.raw_query)

        # Candidate pool selection
        candidates: list[ContractMetadata]
        if parsed.underlying and parsed.underlying in self._by_underlying:
            candidates = self._by_underlying[parsed.underlying]
            # Include token matches if query is numeric
            if parsed.raw_query.isdigit() and parsed.raw_query in self._token_to_contracts:
                candidates = list(set(candidates + self._token_to_contracts[parsed.raw_query]))
        else:
            candidates = self._contracts

        results: list[SearchResult] = []

        for c in candidates:
            if filters and not self._matches_filters(c, filters):
                continue

            und = self._underlying_of.get(c.symbol.upper(), extract_underlying(c))

            if has_query:
                scored = score_contract(c, query, parsed, und)
                if not scored:
                    continue
                score, match_q, matched_field = scored
            else:
                # No query text, filter only: assign default score
                score = 100.0 if c.instrument_type == "EQ" else 80.0
                match_q = MatchQuality.TOKEN_MATCH
                matched_field = "symbol"

            results.append(
                SearchResult(
                    contract=c,
                    score=score,
                    match_quality=match_q,
                    underlying=und,
                    matched_field=matched_field,
                )
            )

        # Deterministic institutional tie-breaking
        def rank_key(item: SearchResult) -> tuple[float, int, float, str]:
            # 1. Higher score first (-score)
            s_key = -item.score

            # 2. Instrument category priority
            c_type = item.contract.instrument_type.upper()
            if parsed.is_future:
                p_order = 0 if "FUT" in c_type else 1
            elif parsed.option_type is not None or parsed.strike is not None:
                p_order = 0 if "OPT" in c_type else 1
            else:
                p_order = 0 if c_type == "EQ" else (1 if "FUT" in c_type else 2)

            # 3. Expiry timestamp ascending
            exp_ts = (
                normalize_to_ist(item.contract.expiry_date).timestamp()
                if item.contract.expiry_date
                else 0.0
            )

            # 4. Symbol alphabetical
            return (s_key, p_order, exp_ts, item.contract.symbol)

        results.sort(key=rank_key)
        return results[:limit]
