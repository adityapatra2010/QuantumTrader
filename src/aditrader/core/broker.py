"""Air-gapped Core Paper Broker simulating realistic execution, margin, and portfolio accounting."""

from datetime import UTC, datetime
from uuid import uuid4

from aditrader.core.costs import CostCalculator, InstrumentClass, SlippageModel
from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType, SignalDirection
from aditrader.core.models.execution import AccountBalance, Position, Trade
from aditrader.core.models.order import Order
from aditrader.core.models.trade_signal import Signal
from aditrader.core.state_machine import OrderStateMachine


class PaperBroker:
    """Institutional-grade simulated execution venue maintaining local ledgers."""

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        max_margin_utilization: float = 0.85,
        slippage_model: SlippageModel | None = None,
        default_instrument: InstrumentClass = "OPTIONS",
    ):
        self.initial_capital: float = round(float(initial_capital), 2)
        self.cash_balance: float = self.initial_capital
        self.max_margin_utilization: float = max_margin_utilization
        self.slippage_model: SlippageModel = slippage_model or SlippageModel()
        self.default_instrument: InstrumentClass = default_instrument

        # Active state registries
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._trades: list[Trade] = []
        self._latest_prices: dict[str, float] = {}

    def _now(self) -> datetime:
        """Return current timestamp."""
        return datetime.now(UTC)

    # --------------------------------------------------------------------------
    # Balance & Portfolio Queries
    # --------------------------------------------------------------------------

    def get_account_balance(self) -> AccountBalance:
        """Compute current capital, margin allocations, and P&L state."""
        realized_pnl = sum(t.fill_price for t in self._trades if False)  # placeholder
        realized_pnl = sum(pos.realized_pnl for pos in self._positions.values())
        unrealized_pnl = sum(pos.unrealized_pnl for pos in self._positions.values())

        # Used margin represents capital committed to open positions
        used_margin = 0.0
        for pos in self._positions.values():
            if pos.qty != 0:
                current_price = self._latest_prices.get(
                    pos.symbol, pos.buy_avg_price if pos.qty > 0 else pos.sell_avg_price
                )
                used_margin += abs(pos.qty) * current_price

        used_margin = round(used_margin, 2)
        total_capital = round(self.cash_balance + used_margin + unrealized_pnl, 2)
        available_margin = round(
            max(0.0, (total_capital * self.max_margin_utilization) - used_margin), 2
        )

        return AccountBalance(
            total_capital=total_capital,
            available_margin=available_margin,
            used_margin=used_margin,
            realized_pnl=round(realized_pnl, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
        )

    def get_positions(self) -> list[Position]:
        """Return all tracked active and historical positions."""
        return list(self._positions.values())

    def get_open_positions(self) -> list[Position]:
        """Return currently active, non-zero positions."""
        return [p for p in self._positions.values() if p.qty != 0]

    def get_orders(self) -> list[Order]:
        """Return all created and processed orders."""
        return list(self._orders.values())

    def get_trades(self) -> list[Trade]:
        """Return all executed trade fills."""
        return list(self._trades)

    # --------------------------------------------------------------------------
    # Order Management & State Transitions
    # --------------------------------------------------------------------------

    def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        qty: int,
        price: float | None = None,
        signal_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> Order:
        """Construct an immutable order in CREATED state."""
        ts = timestamp or self._now()
        order = Order(
            order_id=f"ORD-{uuid4().hex[:12].upper()}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
            status=OrderStatus.CREATED,
            created_at=ts,
            updated_at=ts,
            signal_id=signal_id,
        )
        self._orders[order.order_id] = order
        return order

    def submit_order(
        self,
        order: Order,
        current_market_price: float | None = None,
        timestamp: datetime | None = None,
    ) -> Order:
        """
        Validate risk gates and transition order from CREATED -> SUBMITTED (and FILLED if executable).
        """
        ts = timestamp or self._now()
        market_price = current_market_price or self._latest_prices.get(order.symbol)

        # Estimate capital required for pre-trade margin verification
        estimated_price = order.price if order.order_type == OrderType.LIMIT else market_price
        if estimated_price is None:
            rejected = OrderStateMachine.transition(
                order,
                OrderStatus.REJECTED,
                timestamp=ts,
                rejection_reason="Market price unavailable for order validation",
            )
            self._orders[rejected.order_id] = rejected
            return rejected

        balance = self.get_account_balance()
        required_margin = float(order.qty) * estimated_price

        # Margin Gate: Reject order if margin requirement exceeds available margin
        if order.side == OrderSide.BUY and required_margin > balance.available_margin:
            rejected = OrderStateMachine.transition(
                order,
                OrderStatus.REJECTED,
                timestamp=ts,
                rejection_reason=f"Insufficient available margin: required {required_margin:.2f} > available {balance.available_margin:.2f}",
            )
            self._orders[rejected.order_id] = rejected
            return rejected

        # Transition to SUBMITTED
        submitted = OrderStateMachine.transition(order, OrderStatus.SUBMITTED, timestamp=ts)
        self._orders[submitted.order_id] = submitted

        # If market price is available, check for immediate execution
        if market_price is not None:
            if submitted.order_type == OrderType.MARKET:
                return self._execute_fill(submitted, market_price, submitted.qty, ts)
            elif submitted.order_type == OrderType.LIMIT and submitted.price is not None:
                is_executable = (
                    market_price <= submitted.price
                    if submitted.side == OrderSide.BUY
                    else market_price >= submitted.price
                )
                if is_executable:
                    return self._execute_fill(submitted, submitted.price, submitted.qty, ts)

        return submitted

    def cancel_order(self, order_id: str, timestamp: datetime | None = None) -> Order:
        """Cancel a pending open order."""
        ts = timestamp or self._now()
        order = self._orders.get(order_id)
        if not order:
            raise KeyError(f"Order '{order_id}' not found")

        cancelled = OrderStateMachine.transition(order, OrderStatus.CANCELLED, timestamp=ts)
        self._orders[cancelled.order_id] = cancelled
        return cancelled

    # --------------------------------------------------------------------------
    # Market Data & Execution Matching
    # --------------------------------------------------------------------------

    def on_tick(
        self, tick_symbol: str, ltp: float, timestamp: datetime | None = None
    ) -> list[Trade]:
        """
        Process market price update: evaluate pending limit orders and update MTM P&L.
        """
        ts = timestamp or self._now()
        self._latest_prices[tick_symbol] = ltp

        # Update unrealized MTM P&L on active positions
        if tick_symbol in self._positions:
            self._update_position_mtm(self._positions[tick_symbol], ltp, ts)

        # Match pending SUBMITTED limit orders for this symbol
        executed_trades: list[Trade] = []
        for order in list(self._orders.values()):
            if (
                order.symbol == tick_symbol
                and order.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)
                and order.order_type == OrderType.LIMIT
                and order.price is not None
            ):
                remaining_qty = order.qty - order.filled_qty
                is_executable = (
                    ltp <= order.price if order.side == OrderSide.BUY else ltp >= order.price
                )
                if is_executable and remaining_qty > 0:
                    self._execute_fill(order, order.price, remaining_qty, ts)
                    if self._trades:
                        executed_trades.append(self._trades[-1])

        return executed_trades

    def on_signal(
        self,
        signal: Signal,
        current_market_price: float,
        qty: int,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
    ) -> Order:
        """
        Ingest a Strategy Signal, construct an Order, and route to paper execution.
        """
        if signal.direction == SignalDirection.HOLD:
            raise ValueError("HOLD signal does not generate actionable orders")

        side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        order = self.create_order(
            symbol=signal.symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            price=limit_price if order_type == OrderType.LIMIT else None,
            signal_id=f"SIG-{signal.timestamp.isoformat()}",
            timestamp=signal.timestamp,
        )
        return self.submit_order(
            order, current_market_price=current_market_price, timestamp=signal.timestamp
        )

    # --------------------------------------------------------------------------
    # Private Accounting & Fill Engine
    # --------------------------------------------------------------------------

    def _execute_fill(
        self, order: Order, raw_price: float, fill_qty: int, timestamp: datetime
    ) -> Order:
        """Apply slippage, statutory fees, update order state, positions, and cash balance atomically."""
        fill_price, slippage = self.slippage_model.calculate_fill_price(raw_price, order.side)

        charges = CostCalculator.calculate(
            side=order.side,
            qty=fill_qty,
            price=fill_price,
            instrument=self.default_instrument,
        )

        trade = Trade(
            trade_id=f"TRD-{uuid4().hex[:12].upper()}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            qty=fill_qty,
            fill_price=fill_price,
            slippage=slippage,
            stt=charges.stt,
            charges=charges.total_charges - charges.stt,
            timestamp=timestamp,
        )
        self._trades.append(trade)

        # Update position
        self._apply_trade_to_position(trade, timestamp)

        # Cash accounting
        turnover = float(fill_qty) * fill_price
        if order.side == OrderSide.BUY:
            self.cash_balance -= turnover + charges.total_charges
        else:
            self.cash_balance += turnover - charges.total_charges
        self.cash_balance = round(self.cash_balance, 2)

        # Update order state
        total_filled = order.filled_qty + fill_qty
        new_status = (
            OrderStatus.FILLED if total_filled == order.qty else OrderStatus.PARTIALLY_FILLED
        )

        # Calculate weighted average fill price
        prev_value = order.average_fill_price * float(order.filled_qty)
        new_avg = round((prev_value + (fill_price * float(fill_qty))) / float(total_filled), 2)

        filled_order = OrderStateMachine.transition(
            order,
            new_status,
            timestamp=timestamp,
            filled_qty=total_filled,
            average_fill_price=new_avg,
        )
        self._orders[filled_order.order_id] = filled_order
        return filled_order

    def _apply_trade_to_position(self, trade: Trade, timestamp: datetime) -> None:
        """Update position quantity, average entry price, and calculate realized P&L."""
        existing = self._positions.get(
            trade.symbol,
            Position(symbol=trade.symbol, updated_at=timestamp),
        )

        old_qty = existing.qty
        trade_signed_qty = trade.qty if trade.side == OrderSide.BUY else -trade.qty
        new_qty = old_qty + trade_signed_qty
        realized_pnl_delta = 0.0

        new_buy_avg = existing.buy_avg_price
        new_sell_avg = existing.sell_avg_price

        # Closing or reducing position
        if (old_qty > 0 and trade_signed_qty < 0) or (old_qty < 0 and trade_signed_qty > 0):
            closed_qty = min(abs(old_qty), abs(trade_signed_qty))
            if old_qty > 0:  # Closing Long
                realized_pnl_delta = round(
                    (trade.fill_price - existing.buy_avg_price) * closed_qty, 2
                )
            else:  # Closing Short
                realized_pnl_delta = round(
                    (existing.sell_avg_price - trade.fill_price) * closed_qty, 2
                )

        # Updating entry averages
        if trade.side == OrderSide.BUY:
            if new_qty > 0 and old_qty >= 0:
                total_val = (old_qty * existing.buy_avg_price) + (trade.qty * trade.fill_price)
                new_buy_avg = round(total_val / new_qty, 2)
            elif new_qty == 0:
                new_buy_avg = 0.0
                new_sell_avg = 0.0
        else:  # SELL
            if new_qty < 0 and old_qty <= 0:
                total_val = (abs(old_qty) * existing.sell_avg_price) + (
                    trade.qty * trade.fill_price
                )
                new_sell_avg = round(total_val / abs(new_qty), 2)
            elif new_qty == 0:
                new_buy_avg = 0.0
                new_sell_avg = 0.0

        # Calculate current unrealized P&L
        current_price = self._latest_prices.get(trade.symbol, trade.fill_price)
        unrealized = 0.0
        if new_qty > 0:
            unrealized = round((current_price - new_buy_avg) * new_qty, 2)
        elif new_qty < 0:
            unrealized = round((new_sell_avg - current_price) * abs(new_qty), 2)

        updated_pos = Position(
            symbol=trade.symbol,
            qty=new_qty,
            buy_avg_price=new_buy_avg,
            sell_avg_price=new_sell_avg,
            realized_pnl=round(existing.realized_pnl + realized_pnl_delta, 2),
            unrealized_pnl=unrealized,
            updated_at=timestamp,
        )
        self._positions[trade.symbol] = updated_pos

    def _update_position_mtm(
        self, pos: Position, current_price: float, timestamp: datetime
    ) -> None:
        """Recompute unrealized P&L at market price."""
        if pos.qty == 0:
            return
        if pos.qty > 0:
            unrealized = round((current_price - pos.buy_avg_price) * pos.qty, 2)
        else:
            unrealized = round((pos.sell_avg_price - current_price) * abs(pos.qty), 2)

        self._positions[pos.symbol] = pos.model_copy(
            update={"unrealized_pnl": unrealized, "updated_at": timestamp}
        )
