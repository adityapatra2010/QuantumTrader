"""Authoritative contract specifications and market rules resolver for Indian markets.

Provides dynamic and cataloged strike intervals, lot sizes, and asset classification
in compliance with NSE and SEBI derivative contract guidelines.
"""

from __future__ import annotations

import re
from typing import Any

# Authoritative NSE / BSE index derivative specifications
INDEX_DERIVATIVE_SPECS: dict[str, tuple[float, int]] = {
    # Symbol: (strike_step, lot_size)
    "NIFTY": (50.0, 25),
    "NIFTY 50": (50.0, 25),
    "BANKNIFTY": (100.0, 15),
    "NIFTY BANK": (100.0, 15),
    "FINNIFTY": (50.0, 25),
    "NIFTY FIN SERVICE": (50.0, 25),
    "MIDCPNIFTY": (25.0, 50),
    "NIFTY MID SELECT": (25.0, 50),
    "NIFTYNXT50": (100.0, 10),
    "SENSEX": (100.0, 10),
    "BANKEX": (100.0, 15),
}

# Key high-volume NSE stock derivative contract specifications
EQUITY_DERIVATIVE_SPECS: dict[str, tuple[float, int]] = {
    # Symbol: (strike_step, lot_size)
    "RELIANCE": (20.0, 250),
    "TCS": (20.0, 175),
    "INFY": (20.0, 400),
    "HDFCBANK": (25.0, 550),
    "ICICIBANK": (10.0, 700),
    "SBIN": (10.0, 750),
    "BHARTIARTL": (10.0, 475),
    "ITC": (5.0, 1600),
    "KOTAKBANK": (20.0, 400),
    "LT": (50.0, 150),
    "AXISBANK": (10.0, 625),
    "TATAMOTORS": (10.0, 575),
    "MARUTI": (100.0, 50),
    "BAJFINANCE": (100.0, 125),
    "SUNPHARMA": (20.0, 350),
    "TITAN": (50.0, 175),
    "WIPRO": (5.0, 1500),
    "TATASTEEL": (2.5, 5500),
}


def estimate_strike_step_from_spot(spot: float) -> float:
    """Estimate standard NSE option strike interval based on prevailing underlying price tier."""
    if spot < 50.0:
        return 1.0
    if spot < 125.0:
        return 2.5
    if spot < 250.0:
        return 5.0
    if spot < 500.0:
        return 10.0
    if spot < 1000.0:
        return 20.0
    if spot < 2500.0:
        return 50.0
    if spot < 5000.0:
        return 100.0
    return 200.0


def is_futures_symbol(symbol_or_underlying: str) -> bool:
    """Return True if the underlying identifier explicitly represents a futures contract.

    Prevents false-positive matches for legitimate equity tickers that contain 'FUT'
    as a substring (e.g. FUTURECONSUMER, FUTURA, FUTEX).
    """
    s = symbol_or_underlying.strip().upper()

    # Explicit suffixes
    if s.endswith("-FUT") or s.endswith(".FUT") or s.endswith(" FUT") or s.endswith("_FUT"):
        return True

    # NSE contract trading symbol patterns (e.g., NIFTY24DECFUT, RELIANCE24NOVFUT)
    if re.search(r"\d{2}[A-Z]{3}FUT$", s):
        return True

    # Segment and token demarcations
    return bool(re.search(r"(?:^|[-_\.\s])FUT(?:IDX|STK)?(?:$|[-_\.\s])", s))


def resolve_contract_specs(
    underlying: str,
    spot_price: float | None = None,
    hierarchy: Any | None = None,
) -> tuple[float, int]:
    """Resolve strike step interval and exchange lot size for an underlying asset.

    Prioritizes:
    1. Contract metadata in `hierarchy` if provided.
    2. Exact Index derivative specification.
    3. Explicit NSE stock derivative specification.
    4. Heuristic derived from spot price tier and regulatory lot value.

    Returns:
        tuple[float, int]: (strike_step, lot_size)
    """
    clean_und = underlying.strip().upper()
    # Strip futures suffix if present to find underlying base asset
    clean_und = re.sub(r"[-_\.\s]?FUT(?:IDX|STK)?$", "", clean_und).strip()

    step: float | None = None
    lot_size: int | None = None

    # 1. Inspect hierarchy if available
    if hierarchy is not None:
        # Check lot sizes
        if hasattr(hierarchy, "lot_sizes") and isinstance(hierarchy.lot_sizes, dict):
            lot_size = hierarchy.lot_sizes.get("OPT") or hierarchy.lot_sizes.get("FUT")

        # Check strikes by expiry to deduce exact strike interval
        if (
            hasattr(hierarchy, "strikes_by_expiry")
            and isinstance(hierarchy.strikes_by_expiry, dict)
            and hierarchy.strikes_by_expiry
        ):
            for strikes in hierarchy.strikes_by_expiry.values():
                if len(strikes) >= 2:
                    sorted_s = sorted(strikes)
                    diffs = [
                        round(s2 - s1, 2)
                        for s1, s2 in zip(sorted_s[:-1], sorted_s[1:], strict=False)
                        if (s2 - s1) > 1e-4
                    ]
                    if diffs:
                        step = min(diffs)
                        break

    # 2. Check Index specs
    if clean_und in INDEX_DERIVATIVE_SPECS:
        idx_step, idx_lot = INDEX_DERIVATIVE_SPECS[clean_und]
        step = step or idx_step
        lot_size = lot_size or idx_lot

    # 3. Check Equity specs
    if clean_und in EQUITY_DERIVATIVE_SPECS:
        eq_step, eq_lot = EQUITY_DERIVATIVE_SPECS[clean_und]
        step = step or eq_step
        lot_size = lot_size or eq_lot

    # 4. Fallback defaults based on spot price tier
    effective_spot = spot_price or 24000.0
    if step is None:
        step = estimate_strike_step_from_spot(effective_spot)

    if lot_size is None:
        # SEBI derivative contract value guideline (~₹5-10 Lakhs notionally)
        target_contract_value = 750000.0
        lot_size = max(1, round(target_contract_value / max(1.0, effective_spot)))

    return step, lot_size
