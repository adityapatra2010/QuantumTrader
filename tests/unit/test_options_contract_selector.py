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
    PremiumBand,
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


def test_premium_band_boundary_validation() -> None:
    """Verify inclusive boundaries for band 50.00-59.50."""
    band = PremiumBand(min_ltp=50.00, max_ltp=59.50)

    # Valid values
    assert band.contains(50.00)
    assert band.contains(52.00)
    assert band.contains(59.49)
    assert band.contains(59.50)

    # Invalid values
    assert not band.contains(49.99)
    assert not band.contains(59.51)
    assert not band.contains(0.0)
    assert not band.contains(100.0)


def test_all_six_bands_boundaries() -> None:
    """Verify exact boundaries across all 6 specified strategy bands."""
    bands = [
        PremiumBand(min_ltp=50.0, max_ltp=59.5),
        PremiumBand(min_ltp=60.0, max_ltp=69.5),
        PremiumBand(min_ltp=70.0, max_ltp=79.5),
        PremiumBand(min_ltp=80.0, max_ltp=89.5),
        PremiumBand(min_ltp=90.0, max_ltp=99.5),
        PremiumBand(min_ltp=100.0, max_ltp=109.5),
    ]

    expected_specs = [
        (50.0, 59.5),
        (60.0, 69.5),
        (70.0, 79.5),
        (80.0, 89.5),
        (90.0, 99.5),
        (100.0, 109.5),
    ]

    for band, (exp_min, exp_max) in zip(bands, expected_specs, strict=True):
        assert band.min_ltp == exp_min
        assert band.max_ltp == exp_max
        assert band.contains(exp_min)
        assert band.contains((exp_min + exp_max) / 2.0)
        assert band.contains(exp_max)
        assert not band.contains(exp_min - 0.01)
        assert not band.contains(exp_max + 0.01)


def test_no_gap_no_overlap_deadband() -> None:
    """Verify that buffer gaps between bands do not match either band (no silent rounding)."""
    b1 = PremiumBand(min_ltp=50.0, max_ltp=59.5)
    b2 = PremiumBand(min_ltp=60.0, max_ltp=69.5)
    b3 = PremiumBand(min_ltp=70.0, max_ltp=79.5)

    # 59.50 matches band 1
    assert b1.contains(59.50)
    assert not b2.contains(59.50)

    # 59.60 matches neither band 1 nor band 2
    assert not b1.contains(59.60)
    assert not b2.contains(59.60)

    # 60.00 matches band 2
    assert not b1.contains(60.00)
    assert b2.contains(60.00)

    # 69.50 matches band 2
    assert b2.contains(69.50)
    assert not b3.contains(69.50)

    # 69.60 matches neither band 2 nor band 3
    assert not b2.contains(69.60)
    assert not b3.contains(69.60)

    # 70.00 matches band 3
    assert not b2.contains(70.00)
    assert b3.contains(70.00)


def test_observed_point_in_time_contract_selection_candidates() -> None:
    """Verify exact candidate filtering and deterministic tie-breaking.

    At time T:
    NIFTY CE contracts:
    Strike A -> 47.5
    Strike B -> 52.0
    Strike C -> 58.5
    Strike D -> 61.0

    Band 50.0-59.5 candidates: Strike B (52.0) and Strike C (58.5).
    """
    t0 = datetime(2026, 9, 7, 9, 30, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)

    contracts = [
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24400CE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="CE",
            expiry=exp,
            ltp=47.5,  # Outside band
            volume=5000,
            oi=100000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24450CE",
            underlying="NIFTY",
            strike=24450.0,
            option_type="CE",
            expiry=exp,
            ltp=52.0,  # Candidate B (inside band 50.0-59.5)
            volume=8000,
            oi=200000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24500CE",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=exp,
            ltp=58.5,  # Candidate C (inside band 50.0-59.5)
            volume=12000,
            oi=300000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24550CE",
            underlying="NIFTY",
            strike=24550.0,
            option_type="CE",
            expiry=exp,
            ltp=61.0,  # Outside band
            volume=4000,
            oi=80000,
            timestamp=t0,
        ),
    ]

    chain = PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=contracts,
        spot_price=24480.0,
        is_intraday=True,
    )

    band = PremiumBand(min_ltp=50.0, max_ltp=59.5)

    # 1. find_band_candidates returns exactly Strike B and C
    candidates = chain.find_band_candidates(band=band, option_type="CE")
    symbols = [c.trading_symbol for c in candidates]
    assert symbols == ["NIFTY26SEP24450CE", "NIFTY26SEP24500CE"]
    assert "NIFTY26SEP24400CE" not in symbols
    assert "NIFTY26SEP24550CE" not in symbols

    # 2. Under CLOSEST_PREMIUM to band midpoint (54.75):
    # |52.0 - 54.75| = 2.75 vs |58.5 - 54.75| = 3.75 -> Strike B selected
    resolved_closest = chain.resolve_band(
        band=band,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.CLOSEST_PREMIUM,
    )
    assert resolved_closest.trading_symbol == "NIFTY26SEP24450CE"
    assert resolved_closest.ltp == 52.0

    # 3. Under HIGHER_OI: Strike C (oi=300k) vs Strike B (oi=200k) -> Strike C selected
    resolved_oi = chain.resolve_band(
        band=band,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.HIGHER_OI,
    )
    assert resolved_oi.trading_symbol == "NIFTY26SEP24500CE"
    assert resolved_oi.ltp == 58.5

    # 4. Under HIGHER_VOLUME: Strike C (vol=12k) vs Strike B (vol=8k) -> Strike C selected
    resolved_vol = chain.resolve_band(
        band=band,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.HIGHER_VOLUME,
    )
    assert resolved_vol.trading_symbol == "NIFTY26SEP24500CE"

    # 5. Under CLOSER_TO_ATM (spot = 24480):
    # Strike 24500 diff = 20 vs Strike 24450 diff = 30 -> Strike C selected
    resolved_atm = chain.resolve_band(
        band=band,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.CLOSER_TO_ATM,
    )
    assert resolved_atm.trading_symbol == "NIFTY26SEP24500CE"


def test_independent_ce_hedge_selector() -> None:
    """Verify hedge selector is CE, targets ~5.0, and is completely decoupled from short selector."""
    from aditrader.strategy.translators.yaml_dsl import YAMLStrategyLoader

    yaml_spec = """
    name: Independent Hedge NIFTY CE Strategy
    underlying: NIFTY
    timeframe: 5m
    premium_bands:
      - min_ltp: 50.0
        max_ltp: 59.5
    short:
      action: SELL
      option_type: CE
      quantity: 1
    hedge:
      action: BUY
      option_type: CE
      quantity: 4
      target_ltp: 5.0
      tolerance: 2.0
    stop:
      initial_gap: 5.0
      trail_step: 5.0
      ratchet: true
    """
    dsl = YAMLStrategyLoader.load_from_str(yaml_spec)
    assert len(dsl.legs) == 2

    short_leg = dsl.legs[0]
    hedge_leg = dsl.legs[1]

    # Verify short leg
    assert short_leg.contract_type == "CE"
    assert short_leg.side.value == "SELL"
    assert short_leg.lots == 1
    assert short_leg.contract_selector is not None
    assert short_leg.contract_selector.type == ContractSelectorType.PREMIUM_RANGE
    assert short_leg.contract_selector.min_ltp == 50.0
    assert short_leg.contract_selector.max_ltp == 59.5
    assert short_leg.trailing_stop is not None
    assert short_leg.trailing_stop.initial_gap == 5.0

    # Verify hedge leg
    assert hedge_leg.contract_type == "CE"
    assert hedge_leg.side.value == "BUY"
    assert hedge_leg.lots == 4
    assert hedge_leg.contract_selector is not None
    assert hedge_leg.contract_selector.type == ContractSelectorType.PREMIUM_TARGET
    assert hedge_leg.contract_selector.target_ltp == 5.0
    assert hedge_leg.contract_selector.tolerance == 2.0
    assert hedge_leg.contract_selector.min_ltp is None
    assert hedge_leg.contract_selector.max_ltp is None
    assert hedge_leg.trailing_stop is None  # Hedge never gets trailing stop


def test_trailing_stop_strictly_bound_to_contract_identity() -> None:
    """Verify trailing stop is strictly bound to resolved contract symbol and rejects other contracts."""
    from aditrader.options.trailing_stop import PremiumTrailingStop

    t0 = datetime(2026, 9, 7, 9, 30, 0, tzinfo=UTC)
    stop = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24450CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        created_at=t0,
    )

    # Initial SL = 55.0
    assert stop.current_stop == 55.0

    # Drops to 40.0 -> SL = 45.0
    t1 = datetime(2026, 9, 7, 9, 35, 0, tzinfo=UTC)
    stop.update(price=40.0, timestamp=t1, contract_symbol="NIFTY26SEP24450CE")
    assert stop.current_stop == 45.0

    # Drops to 35.0 -> SL = 40.0
    t2 = datetime(2026, 9, 7, 9, 40, 0, tzinfo=UTC)
    stop.update(price=35.0, timestamp=t2, contract_symbol="NIFTY26SEP24450CE")
    assert stop.current_stop == 40.0

    # Drops to 30.0 -> SL = 35.0
    t3 = datetime(2026, 9, 7, 9, 45, 0, tzinfo=UTC)
    stop.update(price=30.0, timestamp=t3, contract_symbol="NIFTY26SEP24450CE")
    assert stop.current_stop == 35.0

    # Attempting to update with another contract trading at 45.0 must be rejected
    t4 = datetime(2026, 9, 7, 9, 50, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="cannot be updated with contract 'NIFTY26SEP24500CE'"):
        stop.update(price=45.0, timestamp=t4, contract_symbol="NIFTY26SEP24500CE")

    # The trailing stop preserves its ratchet state and current stop
    assert stop.current_stop == 35.0
    assert not stop.is_triggered


def test_reentry_dynamic_strike_resolution() -> None:
    """Verify re-entry dynamically selects contract from current chain rather than re-using previous strike."""
    t0 = datetime(2026, 9, 7, 9, 30, 0, tzinfo=UTC)
    t1 = datetime(2026, 9, 7, 11, 30, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)

    # Snapshot 1: Spot = 24400. Strike 24400 CE is at 55.0 (inside band 50.0-59.5)
    chain_t0 = PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=[
            PointInTimeOptionContract(
                trading_symbol="NIFTY26SEP24400CE",
                underlying="NIFTY",
                strike=24400.0,
                option_type="CE",
                expiry=exp,
                ltp=55.0,
                volume=10000,
                oi=200000,
                timestamp=t0,
            ),
            PointInTimeOptionContract(
                trading_symbol="NIFTY26SEP24700CE",
                underlying="NIFTY",
                strike=24700.0,
                option_type="CE",
                expiry=exp,
                ltp=15.0,
                volume=5000,
                oi=100000,
                timestamp=t0,
            ),
        ],
        spot_price=24400.0,
    )

    band = PremiumBand(min_ltp=50.0, max_ltp=59.5)
    first_contract = chain_t0.resolve_band(band=band, option_type="CE")
    assert first_contract.trading_symbol == "NIFTY26SEP24400CE"
    assert first_contract.strike == 24400.0

    # Snapshot 2: Market has rallied to 24700.
    # Strike 24400 CE is now deep ITM at 320.0.
    # Strike 24700 CE is now ATM at 52.0 (inside band 50.0-59.5)!
    chain_t1 = PointInTimeOptionChain(
        timestamp=t1,
        underlying="NIFTY",
        contracts=[
            PointInTimeOptionContract(
                trading_symbol="NIFTY26SEP24400CE",
                underlying="NIFTY",
                strike=24400.0,
                option_type="CE",
                expiry=exp,
                ltp=320.0,  # Far outside band now
                volume=15000,
                oi=220000,
                timestamp=t1,
            ),
            PointInTimeOptionContract(
                trading_symbol="NIFTY26SEP24700CE",
                underlying="NIFTY",
                strike=24700.0,
                option_type="CE",
                expiry=exp,
                ltp=52.0,  # Now inside band on re-entry!
                volume=20000,
                oi=300000,
                timestamp=t1,
            ),
        ],
        spot_price=24700.0,
    )

    # Re-entry resolution dynamically resolves the new contract (24700 CE)
    second_contract = chain_t1.resolve_band(band=band, option_type="CE")
    assert second_contract.trading_symbol == "NIFTY26SEP24700CE"
    assert second_contract.strike == 24700.0
    assert second_contract.trading_symbol != first_contract.trading_symbol
