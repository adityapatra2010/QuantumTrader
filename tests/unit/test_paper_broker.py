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
    assert broker._orders[order.order_id].average_fill_price == pytest.approx(
        150.075, abs=0.01
    )  # with slippage


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


def test_partial_fill_and_multiple_fills(broker: PaperBroker) -> None:
    """Verify partial fills and multiple progressive fills on a single order."""
    now = datetime.now(UTC)
    symbol = "RELIANCE"

    order = broker.create_order(
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=100,
        price=2500.0,
        timestamp=now,
    )
    submitted = broker.submit_order(order, current_market_price=2600.0, timestamp=now)
    assert submitted.status == OrderStatus.SUBMITTED

    # 1. Partial fill: 40 shares @ 2500.0
    partially_filled = broker.fill_order(
        submitted.order_id, fill_qty=40, fill_price=2500.0, timestamp=now
    )
    assert partially_filled.status == OrderStatus.PARTIALLY_FILLED
    assert partially_filled.filled_qty == 40
    fill_price_1 = partially_filled.average_fill_price
    assert fill_price_1 == pytest.approx(2501.25, abs=0.01)

    pos = broker.get_positions()[0]
    assert pos.qty == 40
    assert pos.buy_avg_price == fill_price_1
    assert pos.realized_pnl == 0.0

    # 2. Second fill to complete order: 60 shares @ 2510.0
    fully_filled = broker.fill_order(
        submitted.order_id, fill_qty=60, fill_price=2510.0, timestamp=now
    )
    assert fully_filled.status == OrderStatus.FILLED
    assert fully_filled.filled_qty == 100
    fill_price_2 = broker.get_trades()[-1].fill_price
    expected_avg = round(((40 * fill_price_1) + (60 * fill_price_2)) / 100, 2)
    assert fully_filled.average_fill_price == pytest.approx(expected_avg, abs=0.01)

    # Position now holds all 100 shares at weighted average price
    pos2 = broker.get_positions()[0]
    assert pos2.qty == 100
    assert pos2.buy_avg_price == pytest.approx(expected_avg, abs=0.01)
    assert pos2.realized_pnl == 0.0


def test_partial_closing_and_realized_unrealized_separation(broker: PaperBroker) -> None:
    """Verify partial position close, preserving entry price for remaining lots and P&L separation."""
    now = datetime.now(UTC)
    symbol = "INFY"

    # 1. Buy 100 @ 1500.0
    buy_order = broker.create_order(
        symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET, qty=100, timestamp=now
    )
    filled_buy = broker.submit_order(buy_order, current_market_price=1500.0, timestamp=now)
    buy_price = filled_buy.average_fill_price

    # 2. Partially close position: Sell 40 @ 1600.0
    sell_order_1 = broker.create_order(
        symbol=symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, qty=40, timestamp=now
    )
    filled_sell_1 = broker.submit_order(sell_order_1, current_market_price=1600.0, timestamp=now)
    sell_price_1 = filled_sell_1.average_fill_price

    pos = broker.get_positions()[0]
    assert pos.qty == 60  # 60 remaining
    assert pos.buy_avg_price == buy_price  # Entry price of remaining lots preserved!

    expected_realized_1 = round((sell_price_1 - buy_price) * 40, 2)
    assert pos.realized_pnl == pytest.approx(expected_realized_1, abs=0.1)

    # Unrealized P&L is calculated on remaining 60 lots at latest sell price
    expected_unrealized_1 = round((sell_price_1 - buy_price) * 60, 2)
    assert pos.unrealized_pnl == pytest.approx(expected_unrealized_1, abs=0.1)

    # 3. Market moves to 1650.0: tick updates MTM unrealized P&L, realized stays fixed
    broker.on_tick(symbol, 1650.0, timestamp=now)
    pos_mtm = broker.get_positions()[0]
    assert pos_mtm.realized_pnl == pytest.approx(expected_realized_1, abs=0.1)
    expected_unrealized_2 = round((1650.0 - buy_price) * 60, 2)
    assert pos_mtm.unrealized_pnl == pytest.approx(expected_unrealized_2, abs=0.1)

    # 4. Fully close remaining 60 @ 1700.0
    sell_order_2 = broker.create_order(
        symbol=symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, qty=60, timestamp=now
    )
    filled_sell_2 = broker.submit_order(sell_order_2, current_market_price=1700.0, timestamp=now)
    sell_price_2 = filled_sell_2.average_fill_price

    pos_closed = broker.get_positions()[0]
    assert pos_closed.qty == 0
    assert pos_closed.unrealized_pnl == 0.0
    expected_realized_total = expected_realized_1 + round((sell_price_2 - buy_price) * 60, 2)
    assert pos_closed.realized_pnl == pytest.approx(expected_realized_total, abs=0.2)

    # AccountBalance separation check
    balance = broker.get_account_balance()
    assert balance.unrealized_pnl == 0.0
    assert balance.realized_pnl == pytest.approx(expected_realized_total, abs=0.2)


def test_position_reversal_long_to_short(broker: PaperBroker) -> None:
    """Verify reversing position from Net Long to Net Short in a single transaction."""
    now = datetime.now(UTC)
    symbol = "TCS"

    # Buy 50 @ 3500.0
    buy_order = broker.create_order(
        symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET, qty=50, timestamp=now
    )
    filled_buy = broker.submit_order(buy_order, current_market_price=3500.0, timestamp=now)
    buy_price = filled_buy.average_fill_price

    # Sell 80 @ 3600.0 (closes 50 long, opens 30 short)
    sell_order = broker.create_order(
        symbol=symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, qty=80, timestamp=now
    )
    filled_sell = broker.submit_order(sell_order, current_market_price=3600.0, timestamp=now)
    sell_price = filled_sell.average_fill_price

    pos = broker.get_positions()[0]
    assert pos.qty == -30  # Net Short 30
    assert pos.buy_avg_price == 0.0
    assert pos.sell_avg_price == sell_price  # Entry price for short position

    # Realized P&L from closing the 50 long
    expected_realized = round((sell_price - buy_price) * 50, 2)
    assert pos.realized_pnl == pytest.approx(expected_realized, abs=0.1)

    # Tick at 3550.0 (favorable for short)
    broker.on_tick(symbol, 3550.0, timestamp=now)
    pos_mtm = broker.get_positions()[0]
    expected_short_unrealized = round((sell_price - 3550.0) * 30, 2)
    assert pos_mtm.unrealized_pnl == pytest.approx(expected_short_unrealized, abs=0.1)


def test_short_and_long_total_capital_accounting(broker: PaperBroker) -> None:
    """Verify total_capital equity accounting does not inflate on shorting or double-count gains."""
    now = datetime.now(UTC)
    init_cap = broker.initial_capital

    # 1. Short 10 units @ 100.0
    order = broker.create_order(
        symbol="NIFTY_SHORT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        qty=10,
        timestamp=now,
    )
    broker.submit_order(order, current_market_price=100.0, timestamp=now)
    bal1 = broker.get_account_balance()
    # Total capital immediately after fill must equal initial capital minus slippage & fees
    assert bal1.total_capital < init_cap
    assert bal1.total_capital > init_cap - 50.0  # reasonable friction

    # 2. Adverse price move: rises from 100 to 120 (loss of ~200)
    broker.on_tick("NIFTY_SHORT", ltp=120.0, timestamp=now)
    bal_adverse = broker.get_account_balance()
    assert bal_adverse.unrealized_pnl < -190.0
    assert bal_adverse.total_capital == pytest.approx(
        bal1.total_capital + bal_adverse.unrealized_pnl, abs=1.0
    )

    # 3. Favorable price move: drops from 100 to 80 (gain of ~200)
    broker.on_tick("NIFTY_SHORT", ltp=80.0, timestamp=now)
    bal_favorable = broker.get_account_balance()
    assert bal_favorable.unrealized_pnl > 190.0
    assert bal_favorable.total_capital == pytest.approx(
        bal1.total_capital + bal_favorable.unrealized_pnl, abs=1.0
    )
