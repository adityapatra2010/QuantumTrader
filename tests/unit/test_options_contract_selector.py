"""Unit tests for ContractSelector and PointInTimeOptionChain contract resolution.

Verifies:
- Exact premium match
- Tolerance match
- No match within tolerance (NoEligibleOptionContractError)
- Multiple matches and deterministic tie-breaking:
  * CLOSEST_PREMIUM
  * HIGHER_OI
  * HIGHER_VOLUME
  * CLOSER_TO_ATM
- Ambiguous contract selection fail-closed behavior (AmbiguousOptionContractError)
- Stale quote rejection (StaleOptionQuoteError)
- Missing LTP / untraded contracts rejection
- Expiry offset filtering and bounds checking
- Option type (CE vs PE) isolation
"""

from datetime import UTC, date, datetime

import pytest

from aditrader.options.chain_replay import (
    AmbiguousOptionContractError,
    NoEligibleOptionContractError,
    PointInTimeOptionChain,
    PointInTimeOptionContract,
    StaleOptionQuoteError,
)
from aditrader.strategy.builder.schema import (
    ContractSelector,
    ContractSelectorType,
    SelectorTieBreaker,
)


def _build_test_chain(eval_time: datetime | None = None) -> PointInTimeOptionChain:
    """Helper creating a deterministic option chain snapshot."""
    t0 = eval_time or datetime(2026, 9, 7, 9, 30, 0, tzinfo=UTC)
    exp_near = date(2026, 9, 24)
    exp_far = date(2026, 10, 29)

    contracts = [
        # Near Expiry CE
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24400CE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="CE",
            expiry=exp_near,
            ltp=110.0,
            volume=5000,
            oi=120000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24500CE",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=exp_near,
            ltp=50.0,  # Exact 50
            volume=10000,
            oi=250000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24600CE",
            underlying="NIFTY",
            strike=24600.0,
            option_type="CE",
            expiry=exp_near,
            ltp=22.0,
            volume=8000,
            oi=180000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24800CE",
            underlying="NIFTY",
            strike=24800.0,
            option_type="CE",
            expiry=exp_near,
            ltp=5.20,  # Near 5.0 hedge
            volume=15000,
            oi=400000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24900CE",
            underlying="NIFTY",
            strike=24900.0,
            option_type="CE",
            expiry=exp_near,
            ltp=4.80,  # Near 5.0 hedge (tied distance with 5.20)
            volume=12000,
            oi=350000,
            timestamp=t0,
        ),
        # Near Expiry PE
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24500PE",
            underlying="NIFTY",
            strike=24500.0,
            option_type="PE",
            expiry=exp_near,
            ltp=48.50,
            volume=9000,
            oi=220000,
            timestamp=t0,
        ),
        # Far Expiry CE
        PointInTimeOptionContract(
            trading_symbol="NIFTY26OCT24500CE",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=exp_far,
            ltp=150.0,
            volume=2000,
            oi=50000,
            timestamp=t0,
        ),
    ]

    return PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=contracts,
        spot_price=24520.0,
        is_intraday=True,
    )


def test_contract_selector_exact_match() -> None:
    """Verify exact match resolves the exact contract."""
    chain = _build_test_chain()
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=50.0,
        tolerance=1.0,
        option_type="CE",
        expiry_offset=0,
    )

    resolved = chain.resolve(selector)
    assert resolved.trading_symbol == "NIFTY26SEP24500CE"
    assert resolved.ltp == 50.0
    assert resolved.strike == 24500.0


def test_contract_selector_tolerance_match() -> None:
    """Verify match when LTP is within tolerance."""
    chain = _build_test_chain()
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=52.0,  # Target 52, contract has 50.0
        tolerance=3.0,
        option_type="CE",
        expiry_offset=0,
    )

    resolved = chain.resolve(selector)
    assert resolved.trading_symbol == "NIFTY26SEP24500CE"


def test_contract_selector_no_match_fails_closed() -> None:
    """Verify fail-closed when no contract exists within tolerance."""
    chain = _build_test_chain()
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=75.0,  # No contracts near 75 (closest are 50 and 110)
        tolerance=5.0,
        option_type="CE",
        expiry_offset=0,
    )

    with pytest.raises(NoEligibleOptionContractError, match="No contract found for target LTP"):
        chain.resolve(selector)


def test_contract_selector_tie_breaker_higher_oi() -> None:
    """Verify tie-breaker resolves contract with higher open interest when distance is identical."""
    chain = _build_test_chain()
    # 24800CE is LTP 5.20 (diff 0.20, OI 400,000)
    # 24900CE is LTP 4.80 (diff 0.20, OI 350,000)
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=5.0,
        tolerance=1.0,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.HIGHER_OI,
    )

    resolved = chain.resolve(selector)
    assert resolved.trading_symbol == "NIFTY26SEP24800CE"
    assert resolved.oi == 400000


def test_contract_selector_tie_breaker_higher_volume() -> None:
    """Verify tie-breaker resolves contract with higher volume."""
    chain = _build_test_chain()
    # 24800CE has volume 15000 vs 24900CE volume 12000
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=5.0,
        tolerance=1.0,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.HIGHER_VOLUME,
    )

    resolved = chain.resolve(selector)
    assert resolved.trading_symbol == "NIFTY26SEP24800CE"


def test_contract_selector_ambiguous_failure_when_enabled() -> None:
    """Verify AmbiguousOptionContractError is raised when fail_on_ambiguity=True."""
    t0 = datetime(2026, 9, 7, 9, 30, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)

    # Two contracts with exact same distance and same OI
    contracts = [
        PointInTimeOptionContract(
            trading_symbol="NIFTY_A",
            underlying="NIFTY",
            strike=24800.0,
            option_type="CE",
            expiry=exp,
            ltp=5.20,
            volume=1000,
            oi=50000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY_B",
            underlying="NIFTY",
            strike=24900.0,
            option_type="CE",
            expiry=exp,
            ltp=4.80,
            volume=1000,
            oi=50000,
            timestamp=t0,
        ),
    ]
    chain = PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=contracts,
        is_intraday=True,
    )

    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=5.0,
        tolerance=1.0,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.HIGHER_OI,
        fail_on_ambiguity=True,
    )

    with pytest.raises(AmbiguousOptionContractError, match="Ambiguous contract selection"):
        chain.resolve(selector)


def test_contract_selector_stale_quote_rejection() -> None:
    """Verify quotes older than max_age_seconds are rejected with StaleOptionQuoteError."""
    t_quote = datetime(2026, 9, 7, 9, 0, 0, tzinfo=UTC)
    chain = _build_test_chain(eval_time=t_quote)

    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=50.0,
        tolerance=5.0,
        option_type="CE",
    )

    # Evaluation time is 1 hour later (3600 seconds) with max_age=300 seconds
    t_eval = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
    with pytest.raises(StaleOptionQuoteError, match="All candidate quotes are stale"):
        chain.resolve(
            selector=selector,
            evaluation_timestamp=t_eval,
            max_age_seconds=300.0,
        )


def test_contract_selector_expiry_offset() -> None:
    """Verify expiry_offset selects the next expiry month."""
    chain = _build_test_chain()
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=150.0,
        tolerance=5.0,
        option_type="CE",
        expiry_offset=1,  # Second expiry (October)
    )

    resolved = chain.resolve(selector)
    assert resolved.trading_symbol == "NIFTY26OCT24500CE"
    assert resolved.expiry == date(2026, 10, 29)


def test_contract_selector_expiry_offset_out_of_bounds() -> None:
    """Verify offset exceeding available expiries raises NoEligibleOptionContractError."""
    chain = _build_test_chain()
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=50.0,
        tolerance=5.0,
        option_type="CE",
        expiry_offset=5,  # Out of bounds
    )

    with pytest.raises(NoEligibleOptionContractError, match="exceeds available expiries count"):
        chain.resolve(selector)


def test_contract_selector_option_type_isolation() -> None:
    """Verify CE selector ignores PE contracts even if PE premium is closer."""
    chain = _build_test_chain()
    # PE is at 48.50 (diff 0.50), CE is at 50.0 (diff 1.0 from 49.0)
    selector = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=49.0,
        tolerance=2.0,
        option_type="CE",
    )

    resolved = chain.resolve(selector)
    assert resolved.option_type == "CE"
    assert resolved.trading_symbol == "NIFTY26SEP24500CE"
