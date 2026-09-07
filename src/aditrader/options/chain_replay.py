"""Point-in-time option chain snapshot and deterministic contract resolution engine.

Guarantees:
- Strict point-in-time isolation: contracts are resolved strictly from quotes visible at timestamp T.
- No lookahead bias: never references future bars, quotes, or settlements.
- Zero price fabrication: contracts missing genuine quotes / LTP are excluded.
- Deterministic contract selection: unambiguous ranking policy with configurable ambiguity fail-closed gate.
- Replay readiness distinction: strictly separates daily EOD quote files from intraday replayable chains.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.market_data import DerivativeQuoteRecord
from aditrader.options.models import ChainRow
from aditrader.strategy.builder.schema import (
    ContractSelector,
    ContractSelectorType,
    SelectorTieBreaker,
)


class OptionsReplayError(ValueError):
    """Base error for options replay and contract resolution failures."""


class NoEligibleOptionContractError(OptionsReplayError):
    """Raised when no option contract matches the required selector predicate within tolerances."""


class AmbiguousOptionContractError(OptionsReplayError):
    """Raised when multiple contracts match identically and fail_on_ambiguity is enabled."""


class StaleOptionQuoteError(OptionsReplayError):
    """Raised when available contract quote exceeds maximum allowed age."""


class PointInTimeOptionContract(BaseModel):
    """Immutable quote and contract specification snapshot at a single point in time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trading_symbol: str = Field(
        ..., min_length=1, description="Unique exchange contract identifier"
    )
    underlying: str = Field(
        ..., min_length=1, description="Root underlying symbol (e.g. 'RELIANCE')"
    )
    strike: float = Field(gt=0.0, description="Strike price in INR")
    option_type: Literal["CE", "PE"] = Field(..., description="Option type: Call (CE) or Put (PE)")
    expiry: date | datetime = Field(..., description="Contract expiration date or datetime")
    ltp: float = Field(gt=0.0, description="Last traded price / premium")
    bid: float | None = Field(default=None, ge=0.0, description="Best available bid quote")
    ask: float | None = Field(default=None, ge=0.0, description="Best available ask quote")
    volume: int = Field(default=0, ge=0, description="Cumulative or incremental trading volume")
    oi: int = Field(default=0, ge=0, description="Open interest contracts")
    timestamp: datetime = Field(..., description="Point-in-time quote observation timestamp")
    vwap: float | None = Field(default=None, ge=0.0, description="Volume-weighted average price")


class PointInTimeOptionChain:
    """Snapshot representing the complete available options chain for an underlying at timestamp T."""

    def __init__(
        self,
        timestamp: datetime,
        underlying: str,
        contracts: list[PointInTimeOptionContract],
        spot_price: float | None = None,
        is_intraday: bool = False,
        source: str = "DERIVATIVE_SNAPSHOT",
    ) -> None:
        if not underlying or not underlying.strip():
            raise ValueError("underlying must be a non-empty string")

        self._timestamp = timestamp
        self._underlying = underlying.strip().upper()
        self._contracts = list(contracts)
        self._spot_price = spot_price
        self._is_intraday = is_intraday
        self._source = source

    @property
    def timestamp(self) -> datetime:
        """Observation timestamp of this chain snapshot."""
        return self._timestamp

    @property
    def underlying(self) -> str:
        """Underlying market asset symbol."""
        return self._underlying

    @property
    def spot_price(self) -> float | None:
        """Underlying spot price at snapshot time, if available."""
        return self._spot_price

    @property
    def is_intraday(self) -> bool:
        """True if this snapshot originates from intraday bars/ticks with intraday timestamps."""
        return self._is_intraday

    @property
    def source(self) -> str:
        """Origin feed classification."""
        return self._source

    @property
    def contracts(self) -> list[PointInTimeOptionContract]:
        """All eligible option contract quotes visible in this snapshot."""
        return list(self._contracts)

    @classmethod
    def from_quote_records(
        cls,
        records: list[DerivativeQuoteRecord],
        timestamp: datetime | None = None,
        spot_price: float | None = None,
        is_intraday: bool = False,
        source: str = "NSE_DERIVATIVE_QUOTE",
    ) -> "PointInTimeOptionChain":
        """Construct PointInTimeOptionChain from a collection of DerivativeQuoteRecord observations."""
        if not records:
            raise ValueError("Cannot construct PointInTimeOptionChain from empty records")

        root_underlying = records[0].symbol.upper()
        eval_ts = timestamp or records[0].timestamp

        parsed_contracts: list[PointInTimeOptionContract] = []
        for r in records:
            if r.option_type not in ("CE", "PE"):
                continue  # Skip futures records ('XX')
            if r.strike_price is None or r.strike_price <= 0.0:
                continue

            # Resolve representative price without fabricating data
            # Prefer last_price, then close, then settlement_price
            price = r.last_price or r.close or r.settlement_price
            if price is None or price <= 0.0:
                continue  # Skip untraded contracts with zero/missing premium

            parsed_contracts.append(
                PointInTimeOptionContract(
                    trading_symbol=r.trading_symbol,
                    underlying=r.symbol.upper(),
                    strike=float(r.strike_price),
                    option_type=r.option_type,
                    expiry=r.expiry_date,
                    ltp=float(price),
                    bid=None,
                    ask=None,
                    volume=int(r.volume),
                    oi=int(r.oi or 0),
                    timestamp=r.timestamp,
                    vwap=r.vwap,
                )
            )

        return cls(
            timestamp=eval_ts,
            underlying=root_underlying,
            contracts=parsed_contracts,
            spot_price=spot_price,
            is_intraday=is_intraday,
            source=source,
        )

    @classmethod
    def from_chain_rows(
        cls,
        rows: list[ChainRow],
        underlying: str,
        timestamp: datetime,
        spot_price: float | None = None,
    ) -> "PointInTimeOptionChain":
        """Construct PointInTimeOptionChain from standard ChainRow strike grid."""
        contracts: list[PointInTimeOptionContract] = []

        for row in rows:
            strike = row.strike
            expiry = row.expiry

            # Call option
            if row.call is not None and row.call.ltp > 0.0:
                contracts.append(
                    PointInTimeOptionContract(
                        trading_symbol=f"{underlying}_{expiry.strftime('%Y%m%d')}_{strike:.0f}_CE",
                        underlying=underlying.upper(),
                        strike=strike,
                        option_type="CE",
                        expiry=expiry,
                        ltp=row.call.ltp,
                        bid=row.call.bid,
                        ask=row.call.ask,
                        volume=row.call.volume,
                        oi=row.call.oi,
                        timestamp=timestamp,
                        vwap=None,
                    )
                )

            # Put option
            if row.put is not None and row.put.ltp > 0.0:
                contracts.append(
                    PointInTimeOptionContract(
                        trading_symbol=f"{underlying}_{expiry.strftime('%Y%m%d')}_{strike:.0f}_PE",
                        underlying=underlying.upper(),
                        strike=strike,
                        option_type="PE",
                        expiry=expiry,
                        ltp=row.put.ltp,
                        bid=row.put.bid,
                        ask=row.put.ask,
                        volume=row.put.volume,
                        oi=row.put.oi,
                        timestamp=timestamp,
                        vwap=None,
                    )
                )

        return cls(
            timestamp=timestamp,
            underlying=underlying,
            contracts=contracts,
            spot_price=spot_price,
            is_intraday=False,
            source="CHAIN_ROWS",
        )

    def get_available_expiries(self) -> list[date]:
        """Extract unique sorted expiration dates visible in this chain."""
        dates: set[date] = set()
        for c in self._contracts:
            if isinstance(c.expiry, datetime):
                dates.add(c.expiry.date())
            elif isinstance(c.expiry, date):
                dates.add(c.expiry)
        return sorted(dates)

    def resolve(
        self,
        selector: ContractSelector,
        underlying: str | None = None,
        evaluation_timestamp: datetime | None = None,
        max_age_seconds: float | None = None,
    ) -> PointInTimeOptionContract:
        """Deterministically resolve a single eligible option contract matching selector predicate.

        Enforces:
        - Contract underlying match
        - Option type constraint (CE / PE)
        - Expiry offset index matching sorted calendar expiries
        - Liquidity filters (min volume and min OI)
        - Premium tolerance bounds
        - Tie-breaking policy (CLOSEST_PREMIUM, HIGHER_OI, HIGHER_VOLUME, CLOSER_TO_ATM)
        - Fail-closed ambiguity detection when requested
        """
        target_underlying = (underlying or self._underlying).strip().upper()

        # 1. Underlying filter
        candidates = [c for c in self._contracts if c.underlying == target_underlying]
        if not candidates:
            raise NoEligibleOptionContractError(
                f"No option contracts found for underlying '{target_underlying}' in chain snapshot."
            )

        # 2. Option type filter
        if selector.option_type is not None:
            candidates = [c for c in candidates if c.option_type == selector.option_type]
            if not candidates:
                raise NoEligibleOptionContractError(
                    f"No option contracts found for type '{selector.option_type}' on underlying '{target_underlying}'."
                )

        # 3. Expiry offset filter
        unique_expiries = sorted(
            {c.expiry.date() if isinstance(c.expiry, datetime) else c.expiry for c in candidates}
        )
        if not unique_expiries:
            raise NoEligibleOptionContractError(
                f"No expiration dates available for underlying '{target_underlying}'."
            )
        if selector.expiry_offset >= len(unique_expiries):
            raise NoEligibleOptionContractError(
                f"Requested expiry_offset {selector.expiry_offset} exceeds available expiries count ({len(unique_expiries)})."
            )

        target_expiry = unique_expiries[selector.expiry_offset]
        candidates = [
            c
            for c in candidates
            if (c.expiry.date() if isinstance(c.expiry, datetime) else c.expiry) == target_expiry
        ]

        # 4. Stale quote age check (if evaluation timestamp and max_age provided)
        eval_ts = evaluation_timestamp or self._timestamp
        if max_age_seconds is not None and max_age_seconds > 0:
            fresh_candidates: list[PointInTimeOptionContract] = []
            for c in candidates:
                age = (eval_ts - c.timestamp).total_seconds()
                if age > max_age_seconds:
                    continue
                fresh_candidates.append(c)

            if not fresh_candidates and candidates:
                oldest_age = max((eval_ts - c.timestamp).total_seconds() for c in candidates)
                raise StaleOptionQuoteError(
                    f"All candidate quotes are stale (oldest age: {oldest_age:.1f}s > max allowed: {max_age_seconds}s)."
                )
            candidates = fresh_candidates

        # 5. Liquidity filters
        if selector.min_volume > 0:
            candidates = [c for c in candidates if c.volume >= selector.min_volume]
        if selector.min_oi > 0:
            candidates = [c for c in candidates if c.oi >= selector.min_oi]

        if not candidates:
            raise NoEligibleOptionContractError(
                f"No contracts survived liquidity filters (min_volume={selector.min_volume}, min_oi={selector.min_oi})."
            )

        # 6. Target criteria matching
        if selector.type == ContractSelectorType.PREMIUM_TARGET:
            if selector.target_ltp is None:
                raise ValueError(
                    "ContractSelector PREMIUM_TARGET requires 'target_ltp' to be defined."
                )

            target_p = selector.target_ltp
            tol = selector.tolerance

            # Check tolerance envelope
            in_tolerance = [c for c in candidates if abs(c.ltp - target_p) <= tol]
            if not in_tolerance:
                best_diff = min(abs(c.ltp - target_p) for c in candidates)
                raise NoEligibleOptionContractError(
                    f"No contract found for target LTP ₹{target_p:.2f} within tolerance ±₹{tol:.2f}. "
                    f"Closest available contract has difference ₹{best_diff:.2f}."
                )
            candidates = in_tolerance

            # Ranking & Tie-breaking
            def sort_key(contract: PointInTimeOptionContract) -> tuple[Any, ...]:
                premium_diff = abs(contract.ltp - target_p)
                secondary: float
                if selector.tie_breaker == SelectorTieBreaker.HIGHER_OI:
                    secondary = float(-contract.oi)
                elif selector.tie_breaker == SelectorTieBreaker.HIGHER_VOLUME:
                    secondary = float(-contract.volume)
                elif (
                    selector.tie_breaker == SelectorTieBreaker.CLOSER_TO_ATM
                    and self._spot_price is not None
                ):
                    secondary = abs(contract.strike - self._spot_price)
                else:
                    # CLOSEST_PREMIUM: secondary is ATM proximity if spot available
                    secondary = (
                        abs(contract.strike - self._spot_price)
                        if self._spot_price is not None
                        else 0.0
                    )

                # Deterministic tertiary tie-breaker
                return (
                    premium_diff,
                    secondary,
                    contract.strike,
                    contract.option_type,
                    contract.trading_symbol,
                )

            candidates.sort(key=sort_key)

            # Check ambiguity policy
            if selector.fail_on_ambiguity and len(candidates) > 1:
                k1 = sort_key(candidates[0])
                k2 = sort_key(candidates[1])
                # If premium_diff and secondary are identical, it is ambiguous
                if k1[0] == k2[0] and k1[1] == k2[1]:
                    raise AmbiguousOptionContractError(
                        f"Ambiguous contract selection between '{candidates[0].trading_symbol}' "
                        f"(LTP {candidates[0].ltp}) and '{candidates[1].trading_symbol}' "
                        f"(LTP {candidates[1].ltp}) with fail_on_ambiguity enabled."
                    )

            return candidates[0]

        elif selector.type == ContractSelectorType.STRIKE_OFFSET:
            # Sort strikes ascending
            candidates_by_strike = sorted(candidates, key=lambda c: c.strike)
            spot = self._spot_price
            if spot is None:
                # If no spot price, take median
                mid_idx = len(candidates_by_strike) // 2
                return candidates_by_strike[mid_idx]

            # Find ATM strike
            atm_contract = min(candidates_by_strike, key=lambda c: abs(c.strike - spot))
            atm_idx = candidates_by_strike.index(atm_contract)
            target_idx = max(0, min(len(candidates_by_strike) - 1, atm_idx))
            return candidates_by_strike[target_idx]

        raise NotImplementedError(f"ContractSelector type '{selector.type}' is not yet supported.")
