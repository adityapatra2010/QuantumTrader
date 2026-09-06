"""Unit tests verifying Core Paper Broker fill simulation, costs, margin, and portfolio accounting."""

from datetime import UTC, datetime

import pytest

from aditrader.core.broker import PaperBroker
from aditrader.core.costs import SlippageModel
from aditrader.core.models import OrderSide, OrderStatus, OrderType, Signal, SignalDirection


@pytest.fixture
def broker() -> PaperBroker:
    return PaperBroker(
        initial_capital=1_000_000.0,
        max_margin_utilization=0.85,
        slippage_model=SlippageModel(fixed_points=0.0, percentage=0.0005),  # 5 bps
        default_instrument="OPTIONS",
    )


def test_initial_state(broker: PaperBroker) -> None:
    """Verify initial capital balances and zero exposures."""
    balance = broker.get_account_balance()
    assert balance.total_capital == 1_000_000.0
    assert balance.available_margin == 850_000.0  # 85% of 1M
    assert balance.used_margin == 0.0
    assert balance.realized_pnl == 0.0
    assert balance.unrealized_pnl == 0.0
    assert len(broker.get_positions()) == 0
    assert len(broker.get_orders()) == 0
    assert len(broker.get_trades()) == 0


def test_market_buy_fill_and_charges(broker: PaperBroker) -> None:
    """Verify market buy execution, slippage, and cash deduction."""
    now = datetime.now(UTC)
    order = broker.create_order(
        symbol="NIFTY24DEC24000CE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=50,
        timestamp=now,
    )

    # Market price 100.0 -> Buy slippage +0.05 -> fill_price 100.05
    filled = broker.submit_order(order, current_market_price=100.0, timestamp=now)
    assert filled.status == OrderStatus.FILLED
    assert filled.filled_qty == 50
    assert filled.average_fill_price == 100.05

    trades = broker.get_trades()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.fill_price == 100.05
    assert trade.qty == 50
    assert trade.slippage == 0.05

    # Check Position
    positions = broker.get_open_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.symbol == "NIFTY24DEC24000CE"
    assert pos.qty == 50
    assert pos.buy_avg_price == 100.05

    # Check Cash: deducted (50 * 100.05) + total_charges
    balance = broker.get_account_balance()
    expected_turnover = 50 * 100.05
    assert broker.cash_balance < 1_000_000.0 - expected_turnover
    assert balance.used_margin > 0


def test_closing_position_realized_pnl(broker: PaperBroker) -> None:
    """Verify position closing, realized profit calculation, and STT application."""
    now = datetime.now(UTC)
    symbol = "NIFTY24DEC24000CE"

    # 1. Buy 50 @ 100.0
    buy_order = broker.create_order(
        symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET, qty=50, timestamp=now
    )
    broker.submit_order(buy_order, current_market_price=100.0, timestamp=now)

    # 2. Sell 50 @ 120.0
    sell_order = broker.create_order(
        symbol=symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, qty=50, timestamp=now
    )
    # Sell slippage: 120 - 0.06 = 119.94
    broker.submit_order(sell_order, current_market_price=120.0, timestamp=now)

    # Position should now be flat (qty == 0)
    pos = broker.get_positions()[0]
    assert pos.qty == 0
    # Expected gross profit: (119.94 - 100.05) * 50 = ~994.50
    assert pos.realized_pnl > 950.0

    # STT must be charged on sell side
    sell_trade = broker.get_trades()[1]
    assert sell_trade.stt > 0  # 0.1% of turnover on option sell


def test_limit_order_delayed_fill(broker: PaperBroker) -> None:
    """Verify limit order rests until tick matches limit criteria."""
    now = datetime.now(UTC)
    symbol = "BANKNIFTY50000PE"

    order = broker.create_order(
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=30,
        price=150.0,
        timestamp=now,
    )

    # Submit when market is 160.0 -> Should NOT execute immediately
    submitted = broker.submit_order(order, current_market_price=160.0, timestamp=now)
    assert submitted.status == OrderStatus.SUBMITTED
    assert len(broker.get_trades()) == 0

    # Market tick at 155.0 -> still above limit 150.0
    broker.on_tick(symbol, 155.0, timestamp=now)
    assert broker._orders[order.order_id].status == OrderStatus.SUBMITTED

    # Market tick drops to 149.0 -> triggers limit fill at order price 150.0
    trades = broker.on_tick(symbol, 149.0, timestamp=now)
    assert len(trades) == 1
    assert broker._orders[order.order_id].average_fill_price == pytest.approx(150.075, abs=0.01)  # with slippage


def test_margin_threshold_rejection(broker: PaperBroker) -> None:
    """Verify order rejection when margin requirement exceeds available balance."""
    now = datetime.now(UTC)
    huge_order = broker.create_order(
        symbol="NIFTY",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=100_000,  # 100k shares @ 24,000 = 2.4 Billion INR!
        timestamp=now,
    )
    result = broker.submit_order(huge_order, current_market_price=24000.0, timestamp=now)
    assert result.status == OrderStatus.REJECTED
    assert "Insufficient available margin" in str(result.rejection_reason)
    assert len(broker.get_trades()) == 0


def test_signal_ingestion_directive(broker: PaperBroker) -> None:
    """Verify on_signal() translates strategy signal into paper execution."""
    now = datetime.now(UTC)
    sig = Signal(
        timestamp=now,
        symbol="NIFTY24DEC24500CE",
        direction=SignalDirection.BUY,
        confidence=0.9,
    )

    executed_order = broker.on_signal(
        signal=sig,
        current_market_price=80.0,
        qty=50,
    )
    assert executed_order.status == OrderStatus.FILLED
    assert executed_order.qty == 50
    assert len(broker.get_open_positions()) == 1


def test_mark_to_market_unrealized_pnl(broker: PaperBroker) -> None:
    """Verify tick updates recompute MTM unrealized P&L dynamically."""
    now = datetime.now(UTC)
    symbol = "NIFTY24DEC24500CE"

    # Buy 50 @ 100.0
    order = broker.create_order(
        symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET, qty=50, timestamp=now
    )
    broker.submit_order(order, current_market_price=100.0, timestamp=now)

    # Market advances to 110.0
    broker.on_tick(symbol, 110.0, timestamp=now)
    balance = broker.get_account_balance()
    # Unrealized P&L should be ~ (110 - 100.05) * 50 = +497.50
    assert balance.unrealized_pnl > 450.0

    # Market drops to 90.0
    broker.on_tick(symbol, 90.0, timestamp=now)
    balance_loss = broker.get_account_balance()
    # Unrealized P&L should be ~ (90 - 100.05) * 50 = -502.50
    assert balance_loss.unrealized_pnl < -450.0
