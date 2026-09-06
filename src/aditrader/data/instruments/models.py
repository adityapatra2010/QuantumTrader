"""Data contracts and schemas for instrument search and derivatives hierarchy."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.data.adapters.base import ContractMetadata


class MatchQuality(StrEnum):
    """Classification of search match confidence."""

    EXACT_TOKEN = "EXACT_TOKEN"
    EXACT_SYMBOL = "EXACT_SYMBOL"
    EXACT_TRADING_SYMBOL = "EXACT_TRADING_SYMBOL"
    PREFIX_SYMBOL = "PREFIX_SYMBOL"
    PREFIX_TRADING_SYMBOL = "PREFIX_TRADING_SYMBOL"
    STRUCTURED_DERIVATIVE = "STRUCTURED_DERIVATIVE"
    TOKEN_MATCH = "TOKEN_MATCH"
    SUBSTRING = "SUBSTRING"
    FUZZY = "FUZZY"


class InstrumentFilter(BaseModel):
    """Criteria for scoping instrument search queries."""

    model_config = ConfigDict(frozen=True)

    exchange: str | None = Field(
        default=None, description="Filter by exchange, e.g., NSE, NFO, BSE"
    )
    instrument_types: list[str] | None = Field(
        default=None,
        description="Filter by classification, e.g. ['EQ'], ['OPTIDX', 'OPTSTK'], ['FUTIDX']",
    )
    underlying: str | None = Field(
        default=None, description="Filter by root underlying asset symbol"
    )
    expiry_min: datetime | None = Field(
        default=None, description="Minimum contract expiration timestamp"
    )
    expiry_max: datetime | None = Field(
        default=None, description="Maximum contract expiration timestamp"
    )
    strike_min: float | None = Field(default=None, description="Minimum strike price floor")
    strike_max: float | None = Field(default=None, description="Maximum strike price ceiling")
    option_type: Literal["CE", "PE"] | None = Field(
        default=None, description="Call or Put option filter"
    )


class SearchResult(BaseModel):
    """Scored instrument search outcome with match provenance."""

    model_config = ConfigDict(frozen=True)

    contract: ContractMetadata = Field(..., description="Matched contract metadata record")
    score: float = Field(..., ge=0.0, le=100.0, description="Match relevance score from 0 to 100")
    match_quality: MatchQuality = Field(..., description="Quality tier of the search match")
    underlying: str = Field(..., description="Root underlying identifier")
    matched_field: str = Field(..., description="Field triggering the match, e.g. symbol, token")
    highlight_spans: list[tuple[int, int]] = Field(
        default_factory=list, description="Character index spans matching query for UI display"
    )


class DerivativesHierarchy(BaseModel):
    """Hierarchical contract map for an underlying derivative root."""

    model_config = ConfigDict(frozen=True)

    underlying: str = Field(..., description="Root underlying symbol, e.g., NIFTY, RELIANCE")
    has_equity: bool = Field(default=False, description="Whether cash equity contract exists")
    equity_contract: ContractMetadata | None = Field(
        default=None, description="Cash equity instrument metadata if available"
    )
    has_futures: bool = Field(default=False, description="Whether active futures contracts exist")
    futures_expiries: list[datetime] = Field(
        default_factory=list, description="Sorted active futures contract expiries"
    )
    has_options: bool = Field(default=False, description="Whether active options contracts exist")
    options_expiries: list[datetime] = Field(
        default_factory=list, description="Sorted active options contract expiries"
    )
    all_expiries: list[datetime] = Field(
        default_factory=list, description="Combined unique sorted expiries for all derivatives"
    )
    strikes_by_expiry: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Map from ISO date string (YYYY-MM-DD) to sorted strike prices",
    )
    lot_sizes: dict[str, int] = Field(
        default_factory=dict,
        description="Lot size mapping by category (e.g., 'EQ': 1, 'FUT': 25, 'OPT': 25)",
    )
