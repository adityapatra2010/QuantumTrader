"""Unit tests for pre-trade RiskEngine and institutional risk gates."""

from datetime import UTC, datetime

from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType
from aditrader.core.models.execution import AccountBalance, Position
from aditrader.core.models.order import Order
from aditrader.core.risk.engine import RiskEngine
from aditrader.core.risk.models import RiskLimits, RiskRejectionReason

_NOW = datetime(2026, 3, 26, 9, 30, tzinfo=UTC)


def _create_order(
    symbol: str = "NIFTY26MAR24000CE", side: OrderSide = OrderSide.BUY, qty: int = 50
) -> Order:
    return Order(
        order_id="ORD-TEST-001",
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        qty=qty,
        filled_qty=0,
        status=OrderStatus.CREATED,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_risk_engine_normal_pass() -> None:
    engine = RiskEngine(initial_capital=1_000_000.0)
    balance = AccountBalance(
        total_capital=1_000_000.0,
        available_margin=900_000.0,
        used_margin=100_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )
    order = _create_order(qty=50)
    result = engine.validate_order(order, balance, {}, current_market_price=100.0)

    assert result.passed is True
    assert result.reason is None
    assert result.detail is None


def test_risk_engine_margin_limit_exceeded() -> None:
    # 85% margin limit on 100,000 capital = 85,000 limit
    limits = RiskLimits(max_margin_utilization_pct=0.85)
    engine = RiskEngine(limits=limits, initial_capital=100_000.0)
    balance = AccountBalance(
        total_capital=100_000.0,
        available_margin=50_000.0,
        used_margin=50_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )

    # Order requires 40,000 margin -> 50,000 + 40,000 = 90,000 (90% utilization > 85%)
    order = _create_order(qty=40)
    result = engine.validate_order(order, balance, {}, current_market_price=1000.0)

    assert result.passed is False
    assert result.reason == RiskRejectionReason.MARGIN_LIMIT_EXCEEDED
    assert result.detail is not None
    assert "90.0%" in result.detail


def test_risk_engine_circuit_breaker_trigger_and_closing_exemption() -> None:
    # 5% drawdown circuit breaker
    limits = RiskLimits(portfolio_drawdown_limit_pct=0.05)
    engine = RiskEngine(limits=limits, initial_capital=1_000_000.0)

    # Equity rises to 1,200,000
    engine.update_equity(1_200_000.0)
    assert bool(engine.circuit_breaker_active) is False

    # Equity drops to 1,120,000 -> (1,200,000 - 1,120,000) / 1,200,000 = 6.67% > 5%
    engine.update_equity(1_120_000.0)
    assert bool(engine.circuit_breaker_active) is True

    balance = AccountBalance(
        total_capital=1_120_000.0,
        available_margin=1_000_000.0,
        used_margin=120_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )

    # New entry order must be rejected
    new_entry_order = _create_order(symbol="RELIANCE", side=OrderSide.BUY, qty=10)
    result_entry = engine.validate_order(new_entry_order, balance, {}, current_market_price=2500.0)
    assert result_entry.passed is False
    assert result_entry.reason == RiskRejectionReason.CIRCUIT_BREAKER_ACTIVE

    # Existing long position: SELL order must be PERMITTED as a closing order
    existing_long = Position(
        symbol="RELIANCE",
        qty=10,
        buy_avg_price=2500.0,
        sell_avg_price=0.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        updated_at=_NOW,
    )
    sell_closing_order = _create_order(symbol="RELIANCE", side=OrderSide.SELL, qty=10)
    result_close_long = engine.validate_order(
        sell_closing_order,
        balance,
        {"RELIANCE": existing_long},
        current_market_price=2500.0,
    )
    assert result_close_long.passed is True

    # Existing short position: BUY order must be PERMITTED as a closing order
    existing_short = Position(
        symbol="TCS",
        qty=-20,
        buy_avg_price=0.0,
        sell_avg_price=3500.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        updated_at=_NOW,
    )
    buy_closing_order = _create_order(symbol="TCS", side=OrderSide.BUY, qty=20)
    result_close_short = engine.validate_order(
        buy_closing_order,
        balance,
        {"TCS": existing_short},
        current_market_price=3500.0,
    )
    assert result_close_short.passed is True

    # Position flip: Existing long 10, SELL 25 attempts to flip to -15 short -> MUST BE REJECTED!
    sell_flip_order = _create_order(symbol="RELIANCE", side=OrderSide.SELL, qty=25)
    result_flip = engine.validate_order(
        sell_flip_order,
        balance,
        {"RELIANCE": existing_long},
        current_market_price=2500.0,
    )
    assert result_flip.passed is False
    assert result_flip.reason == RiskRejectionReason.CIRCUIT_BREAKER_ACTIVE


def test_risk_engine_expiry_naked_short_rejection() -> None:
    engine = RiskEngine()
    balance = AccountBalance(
        total_capital=1_000_000.0,
        available_margin=900_000.0,
        used_margin=100_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )

    short_call_order = _create_order(symbol="NIFTY26MAR24000CE", side=OrderSide.SELL, qty=50)

    # Expiry day and naked short -> rejected
    result = engine.validate_order(
        short_call_order,
        balance,
        {},
        current_market_price=20.0,
        is_expiry_day=True,
        is_naked_short=True,
    )
    assert result.passed is False
    assert result.reason == RiskRejectionReason.EXPIRY_NAKED_SHORT_PROHIBITED

    # Expiry day but hedged -> passed
    result_hedged = engine.validate_order(
        short_call_order,
        balance,
        {},
        current_market_price=20.0,
        is_expiry_day=True,
        is_naked_short=False,
    )
    assert result_hedged.passed is True

    # Non-expiry day naked short -> passed
    result_non_expiry = engine.validate_order(
        short_call_order,
        balance,
        {},
        current_market_price=20.0,
        is_expiry_day=False,
        is_naked_short=True,
    )
    assert result_non_expiry.passed is True


def test_risk_engine_position_limit_exceeded() -> None:
    limits = RiskLimits(max_concurrent_lots=10)
    engine = RiskEngine(limits=limits)
    balance = AccountBalance(
        total_capital=1_000_000.0,
        available_margin=900_000.0,
        used_margin=100_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )

    existing_positions = {
        "NIFTY": Position(
            symbol="NIFTY",
            qty=7,
            buy_avg_price=100.0,
            updated_at=_NOW,
        )
    }

    # 7 + 4 = 11 > 10
    excessive_order = _create_order(symbol="BANKNIFTY", side=OrderSide.BUY, qty=4)
    result = engine.validate_order(
        excessive_order,
        balance,
        existing_positions,
        current_market_price=100.0,
    )
    assert result.passed is False
    assert result.reason == RiskRejectionReason.POSITION_LIMIT_EXCEEDED

    # 7 + 3 = 10 <= 10 -> Passes
    valid_order = _create_order(symbol="BANKNIFTY", side=OrderSide.BUY, qty=3)
    result_valid = engine.validate_order(
        valid_order,
        balance,
        existing_positions,
        current_market_price=100.0,
    )
    assert result_valid.passed is True


def test_risk_engine_reset() -> None:
    engine = RiskEngine(initial_capital=500_000.0)
    engine.update_equity(400_000.0)  # 20% drawdown triggers circuit breaker
    assert bool(engine.circuit_breaker_active) is True

    engine.reset()
    assert bool(engine.circuit_breaker_active) is False
    assert engine.peak_equity == 500_000.0
    assert engine.current_equity == 500_000.0


def test_risk_engine_position_reversal_margin_limit() -> None:
    """Verify position reversal order that exceeds margin ceiling on new net exposure is rejected."""
    limits = RiskLimits(max_margin_utilization_pct=0.85)
    engine = RiskEngine(limits=limits, initial_capital=100_000.0)
    balance = AccountBalance(
        total_capital=100_000.0,
        available_margin=90_000.0,
        used_margin=10_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )
    existing_long = Position(symbol="NIFTY", qty=10, buy_avg_price=1000.0, updated_at=_NOW)
    positions = {"NIFTY": existing_long}

    # 1. Pure closing order: SELL 10 -> PASSES
    close_order = _create_order(symbol="NIFTY", side=OrderSide.SELL, qty=10)
    assert (
        engine.validate_order(close_order, balance, positions, current_market_price=1000.0).passed
        is True
    )

    # 2. Position reversal: SELL 100 -> closes 10, opens 90 short.
    # Released margin: 10,000; New margin: 90 * 1,000 = 90,000.
    # Projected used margin: 90,000 / 100,000 = 90% > 85% ceiling!
    reversal_order = _create_order(symbol="NIFTY", side=OrderSide.SELL, qty=100)
    res_reversal = engine.validate_order(
        reversal_order, balance, positions, current_market_price=1000.0
    )
    assert res_reversal.passed is False
    assert res_reversal.reason == RiskRejectionReason.MARGIN_LIMIT_EXCEEDED


def test_risk_engine_position_reversal_lot_limit() -> None:
    """Verify position reversal order that exceeds maximum concurrent lots is rejected."""
    limits = RiskLimits(max_concurrent_lots=20)
    engine = RiskEngine(limits=limits)
    balance = AccountBalance(
        total_capital=1_000_000.0,
        available_margin=900_000.0,
        used_margin=100_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )
    existing = {"STOCK_A": Position(symbol="STOCK_A", qty=15, buy_avg_price=100.0, updated_at=_NOW)}

    # Pure close: SELL 15 -> PASSES
    close_order = _create_order(symbol="STOCK_A", side=OrderSide.SELL, qty=15)
    assert (
        engine.validate_order(close_order, balance, existing, current_market_price=100.0).passed
        is True
    )

    # Reversal: SELL 40 -> closes 15, opens 25 short.
    # Projected lots: 0 + 25 = 25 > 20 allowable!
    reversal_order = _create_order(symbol="STOCK_A", side=OrderSide.SELL, qty=40)
    res_reversal = engine.validate_order(
        reversal_order, balance, existing, current_market_price=100.0
    )
    assert res_reversal.passed is False
    assert res_reversal.reason == RiskRejectionReason.POSITION_LIMIT_EXCEEDED


def test_risk_engine_lot_semantics_equities_futures_options() -> None:
    """Verify that RiskEngine Gate 4 evaluates contract lot counts rather than raw share quantities."""
    limits = RiskLimits(max_concurrent_lots=10)
    engine = RiskEngine(
        limits=limits,
        lot_sizes={
            "NIFTY26MAR24000CE": 25,
            "RELIANCE-FUT": 250,
            "TCS": 1,
        },
    )
    balance = AccountBalance(
        total_capital=2_000_000.0,
        available_margin=1_800_000.0,
        used_margin=200_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )

    # 1. Options order: NIFTY qty=50 with lot_size=25 -> 2 lots
    # Raw qty (50) would exceed max_concurrent_lots (10), but 2 lots passes easily!
    order_opt = _create_order(symbol="NIFTY26MAR24000CE", side=OrderSide.BUY, qty=50)
    res_opt = engine.validate_order(order_opt, balance, {}, current_market_price=150.0)
    assert res_opt.passed is True

    # 2. Futures order: RELIANCE qty=500 with lot_size=250 -> 2 lots
    # Raw qty (500) would vastly exceed limit, but 2 lots passes!
    order_fut = _create_order(symbol="RELIANCE-FUT", side=OrderSide.BUY, qty=500)
    res_fut = engine.validate_order(order_fut, balance, {}, current_market_price=2500.0)
    assert res_fut.passed is True

    # 3. Simulate holding both positions: 2 lots + 2 lots = 4 lots active
    positions = {
        "NIFTY26MAR24000CE": Position(
            symbol="NIFTY26MAR24000CE", qty=50, buy_avg_price=150.0, updated_at=_NOW
        ),
        "RELIANCE-FUT": Position(
            symbol="RELIANCE-FUT", qty=500, buy_avg_price=2500.0, updated_at=_NOW
        ),
    }

    # 4. Equities order: TCS qty=20 with lot_size=1 -> 20 lots.
    # Total projected lots = 4 (existing) + 20 (new) = 24 lots > 10 allowable -> REJECTED!
    order_eq = _create_order(symbol="TCS", side=OrderSide.BUY, qty=20)
    res_eq = engine.validate_order(order_eq, balance, positions, current_market_price=3500.0)
    assert res_eq.passed is False
    assert res_eq.reason == RiskRejectionReason.POSITION_LIMIT_EXCEEDED
    assert "Order lots (20) brings total lots (24)" in (res_eq.detail or "")

    # 5. Dynamic lot_size override parameter: INFOSYS with lot_size=100, qty=200 -> 2 lots
    # Total projected = 4 + 2 = 6 <= 10 -> PASSES
    order_override = _create_order(symbol="INFOSYS", side=OrderSide.BUY, qty=200)
    res_override = engine.validate_order(
        order_override, balance, positions, current_market_price=1600.0, lot_size=100
    )
    assert res_override.passed is True
