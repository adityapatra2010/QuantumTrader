"""Deterministic scoring, token parsing, and ranking for financial instruments."""

import re
from dataclasses import dataclass
from typing import Literal

from aditrader.data.adapters.base import ContractMetadata
from aditrader.data.instruments.models import MatchQuality


@dataclass(frozen=True)
class ParsedQuery:
    """Deconstructed search query elements."""

    raw_query: str
    normalized_query: str
    tokens: list[str]
    underlying: str | None = None
    strike: float | None = None
    option_type: Literal["CE", "PE"] | None = None
    is_future: bool = False
    expiry_hint: str | None = None


def extract_underlying(contract: ContractMetadata) -> str:
    """Extract root underlying symbol from normalized ContractMetadata."""
    if contract.instrument_type == "EQ":
        return contract.symbol.replace("-EQ", "").strip().upper()

    # Attempt 1: Split trading_symbol by spaces (e.g., "NIFTY 26-DEC-2024 CE 24000")
    parts = contract.trading_symbol.strip().split()
    if parts:
        candidate = parts[0].upper()
        # Clean index names like "NIFTY 50" -> "NIFTY"
        if candidate in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
            return candidate
        if re.match(r"^[A-Z0-9_-]+$", candidate):
            return candidate

    # Attempt 2: Regex on symbol (e.g. "NIFTY24DEC24000CE" -> "NIFTY")
    m = re.match(r"^([A-Z]+?)(\d{2}[A-Z]{3}|\d{5})", contract.symbol.upper())
    if m:
        return m.group(1)

    # Attempt 3: Symbol without standard derivative suffixes
    clean = re.sub(r"(\d+.*|FUT.*|CE.*|PE.*)$", "", contract.symbol.upper())
    if clean:
        return clean

    return contract.symbol.upper()


def parse_query(query: str) -> ParsedQuery:
    """Parse and decompose search input into structured derivative elements."""
    raw = query.strip()
    norm = re.sub(r"\s+", " ", raw.upper())
    raw_tokens = norm.split(" ")

    underlying: str | None = None
    strike: float | None = None
    option_type: Literal["CE", "PE"] | None = None
    is_future = False
    expiry_hint: str | None = None
    remaining_tokens: list[str] = []

    for token in raw_tokens:
        t_upper = token.upper()

        if t_upper in ("CE", "CALL", "C"):
            option_type = "CE"
            continue
        if t_upper in ("PE", "PUT", "P"):
            option_type = "PE"
            continue
        if t_upper in ("FUT", "FUTURE", "FUTURES"):
            is_future = True
            continue

        # Check for numeric strike (e.g. 24000, 24000.0, 2500)
        try:
            val = float(t_upper)
            # Differentiate token ID from strike: strikes are usually in a typical range
            strike = val
            continue
        except ValueError:
            pass

        # Check for month or year expiry hints (e.g. DEC, 24DEC, 26-DEC)
        if (
            re.match(r"^(\d{1,2}[A-Z]{3}|\d{2}[A-Z]{3}\d{2,4}|[A-Z]{3})$", t_upper)
            and t_upper
            in (
                "JAN",
                "FEB",
                "MAR",
                "APR",
                "MAY",
                "JUN",
                "JUL",
                "AUG",
                "SEP",
                "OCT",
                "NOV",
                "DEC",
            )
            or any(
                m in t_upper
                for m in (
                    "JAN",
                    "FEB",
                    "MAR",
                    "APR",
                    "MAY",
                    "JUN",
                    "JUL",
                    "AUG",
                    "SEP",
                    "OCT",
                    "NOV",
                    "DEC",
                )
            )
        ):
            expiry_hint = t_upper
            continue

        remaining_tokens.append(t_upper)

    if remaining_tokens:
        underlying = " ".join(remaining_tokens)

    return ParsedQuery(
        raw_query=raw,
        normalized_query=norm,
        tokens=raw_tokens,
        underlying=underlying,
        strike=strike,
        option_type=option_type,
        is_future=is_future,
        expiry_hint=expiry_hint,
    )


def is_subsequence(needle: str, haystack: str) -> bool:
    """Check if needle characters appear in haystack in preserved order."""
    if not needle:
        return True
    it = iter(haystack)
    return all(char in it for char in needle)


def score_contract(
    contract: ContractMetadata,
    query_str: str,
    parsed: ParsedQuery,
    underlying: str,
) -> tuple[float, MatchQuality, str] | None:
    """Compute deterministic match score (0-100) and provenance for a contract."""
    norm_q = parsed.normalized_query
    sym_upper = contract.symbol.upper()
    trd_upper = contract.trading_symbol.upper()
    token_str = str(contract.token).strip()

    # 1. Exact Token ID match
    if query_str.strip() == token_str:
        return 100.0, MatchQuality.EXACT_TOKEN, "token"

    # 2. Exact Symbol match
    if norm_q == sym_upper:
        return 99.0, MatchQuality.EXACT_SYMBOL, "symbol"

    # 3. Exact Trading Symbol match
    if norm_q == trd_upper:
        return 97.0, MatchQuality.EXACT_TRADING_SYMBOL, "trading_symbol"

    # 4. Exact Underlying match for Cash Equity
    if norm_q == underlying and contract.instrument_type == "EQ":
        return 96.0, MatchQuality.EXACT_SYMBOL, "symbol"

    # 5. Symbol Prefix match
    if sym_upper.startswith(norm_q):
        prefix_ratio = min(1.0, len(norm_q) / max(1, len(sym_upper)))
        score = 88.0 + prefix_ratio * 7.0
        return round(score, 1), MatchQuality.PREFIX_SYMBOL, "symbol"

    # 6. Trading Symbol Prefix match
    if trd_upper.startswith(norm_q):
        prefix_ratio = min(1.0, len(norm_q) / max(1, len(trd_upper)))
        score = 83.0 + prefix_ratio * 6.0
        return round(score, 1), MatchQuality.PREFIX_TRADING_SYMBOL, "trading_symbol"

    # 7. Structured Derivative Query Match
    if parsed.underlying and (
        parsed.underlying == underlying or sym_upper.startswith(parsed.underlying)
    ):
        if parsed.is_future and contract.instrument_type in ("FUTIDX", "FUTSTK"):
            score = 92.0
            if parsed.expiry_hint and parsed.expiry_hint in trd_upper:
                score += 3.0
            return round(min(95.0, score), 1), MatchQuality.STRUCTURED_DERIVATIVE, "trading_symbol"

        if (
            parsed.strike is not None
            and parsed.option_type is not None
            and contract.strike_price == parsed.strike
            and contract.option_type == parsed.option_type
        ):
            score = 93.0
            if parsed.expiry_hint and parsed.expiry_hint in trd_upper:
                score += 3.0
            return round(min(96.0, score), 1), MatchQuality.STRUCTURED_DERIVATIVE, "trading_symbol"

        if parsed.strike is not None and contract.strike_price == parsed.strike:
            return 82.0, MatchQuality.STRUCTURED_DERIVATIVE, "trading_symbol"

        if parsed.option_type is not None and contract.option_type == parsed.option_type:
            return 76.0, MatchQuality.STRUCTURED_DERIVATIVE, "trading_symbol"

    # 8. All Query Tokens present in trading symbol or symbol
    if len(parsed.tokens) > 1:
        combined = f"{sym_upper} {trd_upper} {token_str}"
        if all(t in combined for t in parsed.tokens):
            return 74.0, MatchQuality.TOKEN_MATCH, "trading_symbol"

    # 9. Substring match
    if norm_q in trd_upper:
        return 65.0, MatchQuality.SUBSTRING, "trading_symbol"
    if norm_q in sym_upper:
        return 63.0, MatchQuality.SUBSTRING, "symbol"

    # 10. Fuzzy subsequence match (e.g. "bnf" in "BANKNIFTY", "rel" in "RELIANCE")
    if len(norm_q) >= 2 and (
        is_subsequence(norm_q, sym_upper) or is_subsequence(norm_q, underlying)
    ):
        score = 45.0 + min(10.0, (len(norm_q) / max(1, len(underlying))) * 10.0)
        return round(score, 1), MatchQuality.FUZZY, "symbol"

    return None
