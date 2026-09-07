"""Unit tests for OptionPositionGroup and PositionGroupLeg.

Verifies:
- Creation of coordinated short (SELL 1) and hedge (BUY 4) legs
- Immutable preservation of resolved contract identities (symbols, strikes, expiries)
- Accurate per-leg and group aggregate unrealized and realized P&L
- Coordinated trailing stop evaluation on short leg
- Leg and full group exit lifecycle transitions
"""

from datetime import UTC, date, datetime

from aditrader.core.models.enums import OrderSide
from aditrader.options.position_group import (
    OptionPositionGroup,
    PositionGroupLeg,
    PositionGroupStatus,
)
from aditrader.options.trailing_stop import PremiumTrailingStop


def test_position_group_creation_and_contract_identity_preservation() -> None:
    """Verify short + hedge legs maintain immutable contract identity and quantities."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)

    # Short Leg: SELL 1 @ 50.0 (NIFTY 24500 CE)
    ts_short = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        created_at=t0,
    )
    short_leg = PositionGroupLeg(
        leg_id="leg_short",
        contract_symbol="NIFTY26SEP24500CE",
        underlying="NIFTY",
        strike=24500.0,
        option_type="CE",
        expiry=exp,
        side=OrderSide.SELL,
        quantity=1,
        lot_size=25,
        entry_price=50.0,
        entry_timestamp=t0,
        current_price=50.0,
        current_timestamp=t0,
        trailing_stop=ts_short,
    )

    # Hedge Leg: BUY 4 @ 5.0 (NIFTY 25500 CE)
    hedge_leg = PositionGroupLeg(
        leg_id="leg_hedge",
        contract_symbol="NIFTY26SEP25500CE",
        underlying="NIFTY",
        strike=25500.0,
        option_type="CE",
        expiry=exp,
        side=OrderSide.BUY,
        quantity=4,
        lot_size=25,
        entry_price=5.0,
        entry_timestamp=t0,
        current_price=5.0,
        current_timestamp=t0,
    )

    group = OptionPositionGroup(
        group_id="grp_ladder_50",
        strategy_name="Premium Ladder 50-100",
        underlying="NIFTY",
        created_at=t0,
        legs=[short_leg, hedge_leg],
        target_premium_level=50.0,
    )

    assert group.group_id == "grp_ladder_50"
    assert group.status == PositionGroupStatus.ACTIVE
    assert len(group.legs) == 2
    assert not group.is_closed

    # Verify contract identity is preserved
    leg_s = group.get_leg("NIFTY26SEP24500CE")
    assert leg_s is not None
    assert leg_s.strike == 24500.0
    assert leg_s.option_type == "CE"
    assert leg_s.side == OrderSide.SELL
    assert leg_s.quantity == 1
    assert leg_s.lot_size == 25
    assert leg_s.total_units == 25

    leg_h = group.get_leg("NIFTY26SEP25500CE")
    assert leg_h is not None
    assert leg_h.strike == 25500.0
    assert leg_h.option_type == "CE"
    assert leg_h.side == OrderSide.BUY
    assert leg_h.quantity == 4
    assert leg_h.lot_size == 25
    assert leg_h.total_units == 100

    # Net entry cash flow:
    # Short: + 50.0 * 25 = +1250 INR
    # Hedge: - 5.0 * 100 = -500 INR
    # Net: +750 INR (Net credit)
    assert group.net_cash_flow_entry == 750.0


def test_position_group_pnl_and_trailing_stop_updates() -> None:
    """Verify price updates compute correct per-leg and group PnL and ratchet stop."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)

    short_leg = PositionGroupLeg(
        leg_id="leg_short",
        contract_symbol="NIFTY26SEP24500CE",
        underlying="NIFTY",
        strike=24500.0,
        option_type="CE",
        expiry=exp,
        side=OrderSide.SELL,
        quantity=1,
        lot_size=25,
        entry_price=50.0,
        entry_timestamp=t0,
        current_price=50.0,
        current_timestamp=t0,
        trailing_stop=PremiumTrailingStop(
            contract_symbol="NIFTY26SEP24500CE",
            entry_price=50.0,
            initial_gap=5.0,
            trail_step=5.0,
            side=OrderSide.SELL,
            created_at=t0,
        ),
    )

    hedge_leg = PositionGroupLeg(
        leg_id="leg_hedge",
        contract_symbol="NIFTY26SEP25500CE",
        underlying="NIFTY",
        strike=25500.0,
        option_type="CE",
        expiry=exp,
        side=OrderSide.BUY,
        quantity=4,
        lot_size=25,
        entry_price=5.0,
        entry_timestamp=t0,
        current_price=5.0,
        current_timestamp=t0,
    )

    group = OptionPositionGroup(
        group_id="grp_ladder_50",
        strategy_name="Premium Ladder 50-100",
        underlying="NIFTY",
        created_at=t0,
        legs=[short_leg, hedge_leg],
    )

    assert group.total_unrealized_pnl == 0.0

    # Market move: Short drops from 50.0 to 40.0; Hedge drops from 5.0 to 3.0
    t1 = datetime(2026, 9, 7, 9, 25, 0, tzinfo=UTC)
    evs = group.update_price("NIFTY26SEP24500CE", price=40.0, timestamp=t1)
    group.update_price("NIFTY26SEP25500CE", price=3.0, timestamp=t1)

    # Trailing stop should have ratcheted down to 45.0
    assert len(evs) == 1
    assert evs[0].current_stop == 45.0
    assert short_leg.trailing_stop is not None
    assert short_leg.trailing_stop.current_stop == 45.0

    # Short PnL: (50 - 40) * 25 = +250 INR
    assert short_leg.unrealized_pnl == 250.0
    # Hedge PnL: (3 - 5) * 100 = -200 INR
    assert hedge_leg.unrealized_pnl == -200.0
    # Group PnL: +250 - 200 = +50 INR
    assert group.total_unrealized_pnl == 50.0
    assert not group.is_any_trailing_stop_triggered


def test_position_group_stop_trigger_and_group_exit() -> None:
    """Verify trailing stop trigger flag and collective position closing."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    exp = date(2026, 9, 24)

    short_leg = PositionGroupLeg(
        leg_id="leg_short",
        contract_symbol="NIFTY26SEP24500CE",
        underlying="NIFTY",
        strike=24500.0,
        option_type="CE",
        expiry=exp,
        side=OrderSide.SELL,
        quantity=1,
        lot_size=25,
        entry_price=50.0,
        entry_timestamp=t0,
        current_price=50.0,
        current_timestamp=t0,
        trailing_stop=PremiumTrailingStop(
            contract_symbol="NIFTY26SEP24500CE",
            entry_price=50.0,
            initial_gap=5.0,
            trail_step=5.0,
            side=OrderSide.SELL,
            created_at=t0,
        ),
    )

    hedge_leg = PositionGroupLeg(
        leg_id="leg_hedge",
        contract_symbol="NIFTY26SEP25500CE",
        underlying="NIFTY",
        strike=25500.0,
        option_type="CE",
        expiry=exp,
        side=OrderSide.BUY,
        quantity=4,
        lot_size=25,
        entry_price=5.0,
        entry_timestamp=t0,
        current_price=5.0,
        current_timestamp=t0,
    )

    group = OptionPositionGroup(
        group_id="grp_ladder_50",
        strategy_name="Premium Ladder 50-100",
        underlying="NIFTY",
        created_at=t0,
        legs=[short_leg, hedge_leg],
    )

    # Ratchet down to 30 => SL = 35.0
    t1 = datetime(2026, 9, 7, 9, 25, 0, tzinfo=UTC)
    group.update_price("NIFTY26SEP24500CE", price=30.0, timestamp=t1)
    assert short_leg.trailing_stop is not None
    assert short_leg.trailing_stop.current_stop == 35.0

    # Price rebounds to 35.0 => triggers stop!
    t2 = datetime(2026, 9, 7, 9, 30, 0, tzinfo=UTC)
    evs = group.update_price("NIFTY26SEP24500CE", price=35.0, timestamp=t2)
    assert len(evs) == 1
    assert evs[0].is_triggered
    assert group.is_any_trailing_stop_triggered

    # Execute collective exit at current market prices
    group.close_all(
        exit_prices={"NIFTY26SEP24500CE": 35.0, "NIFTY26SEP25500CE": 4.0},
        timestamp=t2,
    )

    assert group.is_closed
    assert group.status == PositionGroupStatus.CLOSED
    assert group.total_unrealized_pnl == 0.0

    # Short realized PnL: (50 - 35) * 25 = +375 INR
    assert short_leg.realized_pnl == 375.0
    # Hedge realized PnL: (4 - 5) * 100 = -100 INR
    assert hedge_leg.realized_pnl == -100.0
    # Group realized PnL: +275 INR
    assert group.total_realized_pnl == 275.0
