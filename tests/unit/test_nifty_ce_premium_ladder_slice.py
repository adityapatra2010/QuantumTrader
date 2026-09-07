"""Comprehensive End-to-End Vertical Slice Tests for NIFTY CE Premium Ladder.

Validates the full institutional declarative options strategy slice:
- Canonical YAML strategy loading and AST validation
- StrategyRegistry built-in template integration and DNA profiling
- Point-in-time synthetic option chain contract resolution
- Dynamic premium band candidate matching and deterministic tie-breaking
- Isolated multi-leg position groups (Short CE + Independent 4x Hedge CE)
- Per-contract trailing ratchet stop state machine (50 -> 40 => SL 45 -> 35 => SL 40 -> 30 => SL 35)
- Cross-contract quote isolation (zero state pollution across bands or strikes)
- Adversarial boundaries across all 6 bands (50.0–59.5, 60.0–69.5, ..., 100.0–109.5)
- Strict CE-only enforcement (rejection of PE contracts)
- Fail-closed ambiguity protection vs deterministic tie-breaker
- Options air-gap and point-in-time temporal causality protections
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from aditrader.core.models.enums import OrderSide
from aditrader.options.chain_replay import (
    AmbiguousOptionContractError,
    NoEligibleOptionContractError,
    PointInTimeOptionChain,
    PointInTimeOptionContract,
    PremiumBand,
    StaleOptionQuoteError,
)
from aditrader.options.position_group import (
    OptionPositionGroup,
    PositionGroupLeg,
    PositionGroupStatus,
)
from aditrader.options.trailing_stop import (
    PremiumTrailingStop,
    TrailingStopEventType,
)
from aditrader.strategy.builder.schema import (
    ContractSelector,
    ContractSelectorType,
    SelectorTieBreaker,
    StrategyDSL,
)
from aditrader.strategy.library.dna import profile_strategy_dna
from aditrader.strategy.library.models import GammaRisk, MarginEfficiency, TradingStyle
from aditrader.strategy.library.registry import StrategyRegistry
from aditrader.strategy.translators.yaml_dsl import YAMLStrategyLoader
from aditrader.validation.models import OptionsReplayStatus, ValidationStatus
from aditrader.validation.policies import create_institutional_policy
from aditrader.validation.service import (
    StrategyValidationService,
    check_options_replay_readiness,
)

CANONICAL_YAML_PATH = Path("strategies/nifty_ce_premium_ladder.yaml")


# ==============================================================================
# 1. Canonical YAML Strategy Loading & AST Validation
# ==============================================================================


def test_load_and_validate_canonical_strategy_yaml() -> None:
    """Verify canonical YAML strategy loads into valid StrategyDSL and passes Institutional validation."""
    assert CANONICAL_YAML_PATH.is_file(), f"Missing canonical file: {CANONICAL_YAML_PATH}"

    dsl: StrategyDSL = YAMLStrategyLoader.load_from_file(CANONICAL_YAML_PATH)

    assert dsl.schema_version == "1.0"
    assert dsl.name == "NIFTY CE Premium Ladder"
    assert dsl.underlying == "NIFTY"
    assert dsl.timeframe == "5m"

    # Verify all 6 explicit premium bands
    assert dsl.premium_bands is not None
    assert len(dsl.premium_bands) == 6
    expected_bands = [
        (50.0, 59.5),
        (60.0, 69.5),
        (70.0, 79.5),
        (80.0, 89.5),
        (90.0, 99.5),
        (100.0, 109.5),
    ]
    for band, (exp_min, exp_max) in zip(dsl.premium_bands, expected_bands, strict=True):
        assert band.min_ltp == exp_min
        assert band.max_ltp == exp_max

    # Verify short leg
    assert len(dsl.legs) == 2
    short_leg = dsl.legs[0]
    assert short_leg.side == OrderSide.SELL
    assert short_leg.lots == 1
    assert short_leg.contract_type == "CE"
    assert short_leg.contract_selector is not None
    assert short_leg.contract_selector.type == ContractSelectorType.PREMIUM_RANGE
    assert short_leg.contract_selector.min_ltp == 50.0
    assert short_leg.contract_selector.max_ltp == 59.5
    assert short_leg.contract_selector.option_type == "CE"

    # Verify trailing stop on short leg
    assert short_leg.trailing_stop is not None
    assert short_leg.trailing_stop.type == "premium_trailing"
    assert short_leg.trailing_stop.initial_gap == 5.0
    assert short_leg.trailing_stop.trail_step == 5.0
    assert short_leg.trailing_stop.ratchet is True

    # Verify independent hedge leg
    hedge_leg = dsl.legs[1]
    assert hedge_leg.side == OrderSide.BUY
    assert hedge_leg.lots == 4
    assert hedge_leg.contract_type == "CE"
    assert hedge_leg.contract_selector is not None
    assert hedge_leg.contract_selector.type == ContractSelectorType.PREMIUM_TARGET
    assert hedge_leg.contract_selector.target_ltp == 5.0
    assert hedge_leg.contract_selector.tolerance == 2.0
    assert hedge_leg.contract_selector.option_type == "CE"
    assert hedge_leg.trailing_stop is None  # Never inherits trailing stop

    # Institutional validation
    val_service = StrategyValidationService(default_policy=create_institutional_policy())
    result = val_service.validate(dsl)
    assert result.status == ValidationStatus.APPROVED
    assert result.historical_vs_theoretical == "THEORETICAL"

    # Options Replay Readiness Diagnostics
    readiness = check_options_replay_readiness(dsl)
    assert readiness.status == OptionsReplayStatus.STRUCTURALLY_VALID_NOT_REPLAYABLE
    assert readiness.has_option_legs is True
    assert readiness.dynamic_selector_supported is True
    assert readiness.underlying == "NIFTY"
    assert readiness.option_type == "CE"
    assert readiness.short_summary == "SELL 1 dynamically selected CE"
    assert readiness.hedge_summary == (
        "BUY 4 dynamically selected CE | Target: ₹5.00 | Tolerance: ±₹2.00 (₹3.00–₹7.00)"
    )
    assert readiness.trailing_summary == "contract-specific premium ratchet"


# ==============================================================================
# 2. Built-in Template Registry & DNA Integration
# ==============================================================================


def test_builtin_template_registry_and_dna() -> None:
    """Verify built-in template registration, lookup by name/ID, and computed DNA."""
    registry = StrategyRegistry()

    record = registry.get("tpl-nifty-ce-premium-ladder-v1")
    assert record.id == "tpl-nifty-ce-premium-ladder-v1"
    assert record.name == "NIFTY CE Premium Ladder"

    # Also lookup by friendly name
    record_by_name = registry.get_by_name("NIFTY CE Premium Ladder")
    assert record_by_name.id == record.id

    # Verify DNA profile
    dna = profile_strategy_dna(record.dsl_definition)
    assert dna.gamma_risk == GammaRisk.LOW  # 4x long hedge covers 1x short call
    assert dna.margin_efficiency == MarginEfficiency.HIGH
    assert dna.style == TradingStyle.INTRADAY


# ==============================================================================
# 3. Synthetic Option Chain Fixture & Point-in-Time Resolution
# ==============================================================================


@pytest.fixture
def snapshot_chain() -> PointInTimeOptionChain:
    """Synthetic point-in-time option chain for NIFTY weekly expiry."""
    t0 = datetime(2026, 9, 24, 9, 30, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)
    contracts = [
        # Outside Band 1 (< 50.00)
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24400CE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="CE",
            expiry=exp,
            ltp=47.50,
            volume=50000,
            oi=120000,
            timestamp=t0,
        ),
        # Inside Band 1: 50.00–59.50 (diff from midpoint 54.75 is 2.75)
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24450CE",
            underlying="NIFTY",
            strike=24450.0,
            option_type="CE",
            expiry=exp,
            ltp=52.00,
            volume=65000,
            oi=150000,
            timestamp=t0,
        ),
        # Inside Band 1: 50.00–59.50 (diff from midpoint 54.75 is 3.75)
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24500CE",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=exp,
            ltp=58.50,
            volume=80000,
            oi=200000,
            timestamp=t0,
        ),
        # Inside Band 2: 60.00–69.50
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24550CE",
            underlying="NIFTY",
            strike=24550.0,
            option_type="CE",
            expiry=exp,
            ltp=61.00,
            volume=45000,
            oi=90000,
            timestamp=t0,
        ),
        # Hedge Target: around ₹5.00 (±2.00)
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24600CE",
            underlying="NIFTY",
            strike=24600.0,
            option_type="CE",
            expiry=exp,
            ltp=5.00,
            volume=110000,
            oi=350000,
            timestamp=t0,
        ),
    ]
    return PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=contracts,
        spot_price=24480.0,
        is_intraday=True,
    )


def test_synthetic_chain_band1_resolution(snapshot_chain: PointInTimeOptionChain) -> None:
    """Verify Band 1 resolves 24450 CE for short leg and 24600 CE for hedge leg."""
    band1 = PremiumBand(min_ltp=50.0, max_ltp=59.5)

    # 1. Candidates inside Band 1
    cands = snapshot_chain.find_band_candidates(band1, option_type="CE")
    cand_symbols = [c.trading_symbol for c in cands]
    assert "NIFTY26SEP24450CE" in cand_symbols
    assert "NIFTY26SEP24500CE" in cand_symbols
    assert "NIFTY26SEP24400CE" not in cand_symbols  # 47.50 is below 50.00
    assert "NIFTY26SEP24550CE" not in cand_symbols  # 61.00 is above 59.50
    assert "NIFTY26SEP24600CE" not in cand_symbols  # 5.00 is below 50.00

    # 2. Resolve Band 1 short contract: midpoint of [50.0, 59.5] is 54.75
    # 24450 CE @ 52.00 is closer to 54.75 than 24500 CE @ 58.50 (2.75 vs 3.75)
    resolved_short = snapshot_chain.resolve_band(
        band=band1,
        option_type="CE",
        tie_breaker=SelectorTieBreaker.CLOSEST_PREMIUM,
    )
    assert resolved_short.trading_symbol == "NIFTY26SEP24450CE"
    assert resolved_short.ltp == 52.00

    # 3. Resolve Hedge contract: target 5.0 ± 2.0
    hedge_sel = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=5.0,
        tolerance=2.0,
        option_type="CE",
        underlying="NIFTY",
    )
    resolved_hedge = snapshot_chain.resolve(hedge_sel)
    assert resolved_hedge.trading_symbol == "NIFTY26SEP24600CE"
    assert resolved_hedge.ltp == 5.00


# ==============================================================================
# 4. Multi-Leg Position Group Creation & Cash Flow Accounting
# ==============================================================================


def test_position_group_creation_and_accounting(
    snapshot_chain: PointInTimeOptionChain,
) -> None:
    """Verify position group creation attaches immutable contract identities and calculates net credit."""
    t0 = snapshot_chain.timestamp
    band1 = PremiumBand(min_ltp=50.0, max_ltp=59.5)

    short_contract = snapshot_chain.resolve_band(band1, option_type="CE")
    hedge_sel = ContractSelector(
        type=ContractSelectorType.PREMIUM_TARGET,
        target_ltp=5.0,
        tolerance=2.0,
        option_type="CE",
    )
    hedge_contract = snapshot_chain.resolve(hedge_sel)

    # Instantiate legs
    short_leg = PositionGroupLeg(
        leg_id="band1-short-1",
        contract_symbol=short_contract.trading_symbol,
        underlying=short_contract.underlying,
        strike=short_contract.strike,
        option_type=short_contract.option_type,
        expiry=short_contract.expiry,
        side=OrderSide.SELL,
        quantity=1,
        lot_size=25,
        entry_price=short_contract.ltp,
        entry_timestamp=t0,
        current_price=short_contract.ltp,
        current_timestamp=t0,
        trailing_stop=PremiumTrailingStop(
            contract_symbol=short_contract.trading_symbol,
            entry_price=short_contract.ltp,
            initial_gap=5.0,
            trail_step=5.0,
            side=OrderSide.SELL,
            ratchet=True,
            created_at=t0,
        ),
    )

    hedge_leg = PositionGroupLeg(
        leg_id="band1-hedge-1",
        contract_symbol=hedge_contract.trading_symbol,
        underlying=hedge_contract.underlying,
        strike=hedge_contract.strike,
        option_type=hedge_contract.option_type,
        expiry=hedge_contract.expiry,
        side=OrderSide.BUY,
        quantity=4,
        lot_size=25,
        entry_price=hedge_contract.ltp,
        entry_timestamp=t0,
        current_price=hedge_contract.ltp,
        current_timestamp=t0,
        trailing_stop=None,  # Hedge has no trailing stop
    )

    group = OptionPositionGroup(
        group_id="band-1-posgroup",
        strategy_name="NIFTY CE Premium Ladder",
        underlying="NIFTY",
        created_at=t0,
        legs=[short_leg, hedge_leg],
        band=band1,
        band_id="Band 1 (₹50.00–₹59.50)",
    )

    assert group.band == band1
    assert group.band_id == "Band 1 (₹50.00–₹59.50)"
    assert group.status == PositionGroupStatus.ACTIVE
    assert group.is_closed is False
    assert len(group.get_short_legs()) == 1
    assert len(group.get_hedge_legs()) == 1

    # Net Cash Flow Accounting:
    # Short: 1 lot * 25 shares * 52.00 = +1,300 INR (credit)
    # Hedge: 4 lots * 25 shares * 5.00 = -500 INR (debit)
    # Net: +800 INR credit
    assert group.net_cash_flow_entry == (52.00 * 25) - (5.00 * 100)  # +800.0 INR
    assert group.total_unrealized_pnl == 0.0


# ==============================================================================
# 5. Per-Contract Trailing Stop Ratchet Progression
# ==============================================================================


def test_trailing_stop_ratchet_progression() -> None:
    """Verify exact ratchet stepping: entry 50 -> 40 => SL 45 -> 35 => SL 40 -> 30 => SL 35."""
    t0 = datetime(2026, 9, 24, 9, 30, 0, tzinfo=UTC)
    symbol = "NIFTY26SEP24450CE"

    ts = PremiumTrailingStop(
        contract_symbol=symbol,
        entry_price=50.00,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        ratchet=True,
        created_at=t0,
    )

    # 1. Entry at 50.00 -> Initial Stop Loss = 50.0 + 5.0 = 55.0
    assert ts.current_stop == 55.00

    # 2. Premium drops to 40.00 (drop of 10.0 >= trail_step 5.0)
    # Low-water mark = 40.00 -> Stop Loss ratchets to 55.0 - 2*5.0 = 45.0
    t1 = t0 + timedelta(minutes=5)
    ev2 = ts.update(price=40.00, timestamp=t1, contract_symbol=symbol)
    assert ev2 is not None
    assert ev2.event_type == TrailingStopEventType.RATCHETED
    assert ev2.current_stop == 45.00
    assert ts.current_stop == 45.00

    # 3. Premium drops further to 35.00 (drop of 15.0 >= trail_step 5.0)
    # Low-water mark = 35.00 -> Stop Loss ratchets to 55.0 - 3*5.0 = 40.0
    t2 = t1 + timedelta(minutes=5)
    ev3 = ts.update(price=35.00, timestamp=t2, contract_symbol=symbol)
    assert ev3 is not None
    assert ev3.event_type == TrailingStopEventType.RATCHETED
    assert ev3.current_stop == 40.00
    assert ts.current_stop == 40.00

    # 4. Premium drops further to 30.00 (drop of 20.0 >= trail_step 5.0)
    # Low-water mark = 30.00 -> Stop Loss ratchets to 55.0 - 4*5.0 = 35.0
    t3 = t2 + timedelta(minutes=5)
    ev4 = ts.update(price=30.00, timestamp=t3, contract_symbol=symbol)
    assert ev4 is not None
    assert ev4.event_type == TrailingStopEventType.RATCHETED
    assert ev4.current_stop == 35.00
    assert ts.current_stop == 35.00

    # 5. Upward retrace: price rises back to 34.00
    # Ratchet NEVER loosens -> Stop Loss must remain exactly 35.00
    t4 = t3 + timedelta(minutes=5)
    ev5 = ts.update(price=34.00, timestamp=t4, contract_symbol=symbol)
    assert ev5 is not None
    assert ev5.event_type == TrailingStopEventType.IDLE
    assert ts.current_stop == 35.00

    # 6. Stop Hit: price breaches 35.00 to 35.20
    t5 = t4 + timedelta(minutes=5)
    ev6 = ts.update(price=35.20, timestamp=t5, contract_symbol=symbol)
    assert ev6 is not None
    assert ev6.event_type == TrailingStopEventType.TRIGGERED
    assert ts.is_triggered is True


# ==============================================================================
# 6. Cross-Contract & Multi-Band Isolation Invariant
# ==============================================================================


def test_cross_contract_and_multi_band_isolation(
    snapshot_chain: PointInTimeOptionChain,
) -> None:
    """Verify Band 1 and Band 2 positions maintain separate, isolated states without cross-talk."""
    t0 = snapshot_chain.timestamp

    # Band 1: [50.0, 59.5] -> 24450 CE @ 52.00
    band1 = PremiumBand(min_ltp=50.0, max_ltp=59.5)
    short1 = snapshot_chain.resolve_band(band1, option_type="CE")
    assert short1.trading_symbol == "NIFTY26SEP24450CE"

    # Band 2: [60.0, 69.5] -> 24550 CE @ 61.00
    band2 = PremiumBand(min_ltp=60.0, max_ltp=69.5)
    short2 = snapshot_chain.resolve_band(band2, option_type="CE")
    assert short2.trading_symbol == "NIFTY26SEP24550CE"

    # Instantiate Band 1 Group
    leg1 = PositionGroupLeg(
        leg_id="b1-s",
        contract_symbol=short1.trading_symbol,
        underlying=short1.underlying,
        strike=short1.strike,
        option_type=short1.option_type,
        expiry=short1.expiry,
        side=OrderSide.SELL,
        quantity=1,
        entry_price=52.00,
        entry_timestamp=t0,
        current_price=52.00,
        current_timestamp=t0,
        trailing_stop=PremiumTrailingStop(
            contract_symbol=short1.trading_symbol,
            entry_price=52.00,
            initial_gap=5.0,
            trail_step=5.0,
            side=OrderSide.SELL,
            ratchet=True,
            created_at=t0,
        ),
    )
    group1 = OptionPositionGroup(
        group_id="group-b1",
        strategy_name="NIFTY CE Premium Ladder",
        underlying="NIFTY",
        created_at=t0,
        legs=[leg1],
        band=band1,
        band_id="Band 1",
    )

    # Instantiate Band 2 Group
    leg2 = PositionGroupLeg(
        leg_id="b2-s",
        contract_symbol=short2.trading_symbol,
        underlying=short2.underlying,
        strike=short2.strike,
        option_type=short2.option_type,
        expiry=short2.expiry,
        side=OrderSide.SELL,
        quantity=1,
        entry_price=61.00,
        entry_timestamp=t0,
        current_price=61.00,
        current_timestamp=t0,
        trailing_stop=PremiumTrailingStop(
            contract_symbol=short2.trading_symbol,
            entry_price=61.00,
            initial_gap=5.0,
            trail_step=5.0,
            side=OrderSide.SELL,
            ratchet=True,
            created_at=t0,
        ),
    )
    group2 = OptionPositionGroup(
        group_id="group-b2",
        strategy_name="NIFTY CE Premium Ladder",
        underlying="NIFTY",
        created_at=t0,
        legs=[leg2],
        band=band2,
        band_id="Band 2",
    )

    # Initial SLs
    assert leg1.trailing_stop is not None
    assert leg1.trailing_stop.current_stop == 57.00  # 52 + 5
    assert leg2.trailing_stop is not None
    assert leg2.trailing_stop.current_stop == 66.00  # 61 + 5

    t1 = t0 + timedelta(minutes=5)
    # Price update on third strike: 24500 CE prints 45.00
    # Neither group contains 24500 CE, so neither trailing stop must change
    evs1 = group1.update_price("NIFTY26SEP24500CE", 45.00, t1)
    evs2 = group2.update_price("NIFTY26SEP24500CE", 45.00, t1)
    assert len(evs1) == 0
    assert len(evs2) == 0
    assert leg1.trailing_stop.current_stop == 57.00
    assert leg2.trailing_stop.current_stop == 66.00

    # Band 1 short contract moves from 52 to 42 (drops 10)
    evs1_move = group1.update_price("NIFTY26SEP24450CE", 42.00, t1)
    assert len(evs1_move) == 1
    assert leg1.trailing_stop.current_stop == 47.00  # 42 + 5
    # Band 2 must remain completely unaffected
    assert leg2.trailing_stop.current_stop == 66.00

    # Stop hit on Band 1
    t2 = t1 + timedelta(minutes=5)
    evs1_stop = group1.update_price("NIFTY26SEP24450CE", 48.00, t2)
    assert len(evs1_stop) == 1
    assert evs1_stop[0].event_type == TrailingStopEventType.TRIGGERED
    assert group1.is_any_trailing_stop_triggered is True
    # Group 1 closes
    group1.close_all(exit_prices={"NIFTY26SEP24450CE": 48.00}, timestamp=t2)
    assert group1.status == PositionGroupStatus.CLOSED

    # Group 2 is STILL active and untouched!
    assert group2.status == PositionGroupStatus.ACTIVE
    assert group2.is_any_trailing_stop_triggered is False
    assert leg2.current_price == 61.00


# ==============================================================================
# 7. Adversarial Boundary Precision: All 6 Bands
# ==============================================================================


@pytest.mark.parametrize(
    "min_b,max_b,inside_val,below_val,above_val",
    [
        (50.0, 59.5, 50.0, 49.99, 59.51),
        (50.0, 59.5, 59.5, 49.99, 59.51),
        (60.0, 69.5, 60.0, 59.99, 69.51),
        (60.0, 69.5, 69.5, 59.99, 69.51),
        (70.0, 79.5, 70.0, 69.99, 79.51),
        (70.0, 79.5, 79.5, 69.99, 79.51),
        (80.0, 89.5, 80.0, 79.99, 89.51),
        (80.0, 89.5, 89.5, 79.99, 89.51),
        (90.0, 99.5, 90.0, 89.99, 99.51),
        (90.0, 99.5, 99.5, 89.99, 99.51),
        (100.0, 109.5, 100.0, 99.99, 109.51),
        (100.0, 109.5, 109.5, 99.99, 109.51),
    ],
)
def test_adversarial_boundaries_all_six_bands(
    min_b: float,
    max_b: float,
    inside_val: float,
    below_val: float,
    above_val: float,
) -> None:
    """Verify inclusive boundary adherence and rejection of sub-cent deviations."""
    band = PremiumBand(min_ltp=min_b, max_ltp=max_b)

    assert band.contains(inside_val) is True
    assert band.contains(below_val) is False
    assert band.contains(above_val) is False


# ==============================================================================
# 8. Strict CE-Only Enforcement (Rejection of PE Contracts)
# ==============================================================================


def test_rejection_of_pe_contracts_in_ce_bands() -> None:
    """Verify option chain selector strictly rejects PE contracts for CE-only strategy."""
    t0 = datetime(2026, 9, 24, 9, 30, 0, tzinfo=UTC)
    chain = PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=[
            # PE contract matching the premium range
            PointInTimeOptionContract(
                trading_symbol="NIFTY26SEP24450PE",
                underlying="NIFTY",
                strike=24450.0,
                option_type="PE",
                expiry=date(2026, 9, 24),
                ltp=55.00,
                volume=10000,
                oi=20000,
                timestamp=t0,
            ),
        ],
        is_intraday=True,
    )

    band1 = PremiumBand(min_ltp=50.0, max_ltp=59.5)
    with pytest.raises(
        NoEligibleOptionContractError, match="No option contracts found for type 'CE'"
    ):
        chain.resolve_band(band1, option_type="CE")


# ==============================================================================
# 9. Fail-on-Ambiguity vs Deterministic Tie-Breaker
# ==============================================================================


def test_fail_on_ambiguity_vs_tie_breaker() -> None:
    """Verify ambiguous equidistant contracts raise error under fail_on_ambiguity, or resolve deterministically."""
    t0 = datetime(2026, 9, 24, 9, 30, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)
    # Two identical-premium equidistant contracts with identical OI and volume
    contracts = [
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24450CE",
            underlying="NIFTY",
            strike=24450.0,
            option_type="CE",
            expiry=exp,
            ltp=55.00,
            volume=50000,
            oi=100000,
            timestamp=t0,
        ),
        PointInTimeOptionContract(
            trading_symbol="NIFTY26SEP24500CE",
            underlying="NIFTY",
            strike=24500.0,
            option_type="CE",
            expiry=exp,
            ltp=55.00,
            volume=50000,
            oi=100000,
            timestamp=t0,
        ),
    ]
    chain = PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=contracts,
        is_intraday=True,
    )
    band = PremiumBand(min_ltp=50.0, max_ltp=60.0)

    # 1. With fail_on_ambiguity=True -> Fail Closed!
    with pytest.raises(AmbiguousOptionContractError, match="Ambiguous contract selection"):
        chain.resolve_band(band, option_type="CE", fail_on_ambiguity=True)

    # 2. With fail_on_ambiguity=False -> Resolves deterministically
    resolved = chain.resolve_band(band, option_type="CE", fail_on_ambiguity=False)
    assert resolved.trading_symbol in ("NIFTY26SEP24450CE", "NIFTY26SEP24500CE")


# ==============================================================================
# 10. Temporal Causality & Stale Quote Prevention
# ==============================================================================


def test_stale_quote_prevention() -> None:
    """Verify quotes older than max_quote_age are rejected with StaleOptionQuoteError."""
    t0 = datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC)
    stale_ts = t0 - timedelta(hours=1)  # 60 minutes old
    chain = PointInTimeOptionChain(
        timestamp=t0,
        underlying="NIFTY",
        contracts=[
            PointInTimeOptionContract(
                trading_symbol="NIFTY26SEP24450CE",
                underlying="NIFTY",
                strike=24450.0,
                option_type="CE",
                expiry=date(2026, 9, 24),
                ltp=52.00,
                volume=10000,
                oi=20000,
                timestamp=stale_ts,
            ),
        ],
        is_intraday=True,
    )

    band = PremiumBand(min_ltp=50.0, max_ltp=60.0)
    with pytest.raises(StaleOptionQuoteError, match="stale"):
        chain.resolve_band(
            band=band,
            option_type="CE",
            max_age_seconds=900.0,
        )
