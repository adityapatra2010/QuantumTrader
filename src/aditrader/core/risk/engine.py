"""Pre-trade execution risk engine and safety barrier.

Per ARCHITECTURE.md and .agents/skills/risk-engine.md:
Evaluates pre-trade margin utilization (85% ceiling), portfolio drawdown
circuit breakers (5% limit), and unhedged expiry-day gamma protection.
Completely decoupled from strategy generation and evaluated at order submission.
"""

import math
from datetime import datetime

from aditrader.core.models.enums import OrderSide
from aditrader.core.models.execution import AccountBalance, Position
from aditrader.core.models.order import Order
from aditrader.core.risk.models import RiskCheckResult, RiskLimits, RiskRejectionReason


class RiskEngine:
    """Institutional pre-trade risk engine and portfolio safety gatekeeper."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        initial_capital: float = 1_000_000.0,
        lot_sizes: dict[str, int] | None = None,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.initial_capital = initial_capital
        self.peak_equity = initial_capital
        self.current_equity = initial_capital
        self.session_starting_equity = initial_capital
        self.session_peak_equity = initial_capital
        self._circuit_breaker_active = False
        self.lot_sizes: dict[str, int] = dict(lot_sizes or {})

    @property
    def circuit_breaker_active(self) -> bool:
        """Indicates whether portfolio drawdown circuit breaker is currently active."""
        return self._circuit_breaker_active

    def on_session_start(self, timestamp: datetime, current_equity: float) -> None:
        """Reset intraday circuit breaker for a new trading session while preserving cumulative risk state."""
        self.session_starting_equity = current_equity
        self.session_peak_equity = current_equity
        self._circuit_breaker_active = False

    def update_equity(self, current_equity: float) -> None:
        """Update current portfolio equity and evaluate intraday circuit breaker threshold."""
        self.current_equity = current_equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        if current_equity > self.session_peak_equity:
            self.session_peak_equity = current_equity

        # Intraday Drawdown Breaker (evaluated relative to current session peak)
        if self.session_peak_equity > 0.0:
            dd_pct = (self.session_peak_equity - current_equity) / self.session_peak_equity
            if dd_pct >= self.limits.portfolio_drawdown_limit_pct:
                self._circuit_breaker_active = True

    def reset(self) -> None:
        """Reset equity high-water mark and clear circuit breaker."""
        self.peak_equity = self.initial_capital
        self.current_equity = self.initial_capital
        self.session_starting_equity = self.initial_capital
        self.session_peak_equity = self.initial_capital
        self._circuit_breaker_active = False

    def resolve_lots(self, symbol: str, qty: int, default_lot_size: int = 1) -> int:
        """Compute integer lot count for a raw instrument quantity.

        Uses registered lot size from `lot_sizes` or fallback `default_lot_size`.
        """
        lot_size = self.lot_sizes.get(symbol, default_lot_size)
        if lot_size <= 0:
            lot_size = 1
        return math.ceil(abs(qty) / lot_size)

    def validate_order(
        self,
        order: Order,
        balance: AccountBalance,
        positions: dict[str, Position],
        current_market_price: float,
        *,
        lot_size: int | None = None,
        is_expiry_day: bool = False,
        is_naked_short: bool = False,
    ) -> RiskCheckResult:
        """Validate order against active pre-trade institutional risk gates.

        Args:
            order: Proposed Order to be executed.
            balance: Current point-in-time AccountBalance snapshot.
            positions: Map of active portfolio positions.
            current_market_price: Prevailing price for estimated margin calculations.
            lot_size: Optional contract lot size for derivative lot conversion (defaults to 1 for shares).
            is_expiry_day: True if current bar date is expiration date.
            is_naked_short: True if order represents an unhedged naked short option.

        Returns:
            RiskCheckResult indicating pass or failure classification.
        """
        existing_pos = positions.get(order.symbol)
        is_opposite = (
            existing_pos is not None
            and existing_pos.qty != 0
            and (
                (existing_pos.qty > 0 and order.side == OrderSide.SELL)
                or (existing_pos.qty < 0 and order.side == OrderSide.BUY)
            )
        )
        existing_qty_abs = abs(existing_pos.qty) if is_opposite and existing_pos is not None else 0
        net_new_qty = (order.qty - existing_qty_abs) if is_opposite else order.qty
        is_pure_closing = is_opposite and (order.qty <= existing_qty_abs)

        # Gate 1: Portfolio Drawdown Circuit Breaker
        # Only strictly closing/reducing orders are permitted to reduce portfolio risk.
        if self._circuit_breaker_active and not is_pure_closing:
            return RiskCheckResult(
                passed=False,
                reason=RiskRejectionReason.CIRCUIT_BREAKER_ACTIVE,
                detail=(
                    f"Portfolio drawdown circuit breaker active (session peak: {self.session_peak_equity:.2f}, "
                    f"current: {self.current_equity:.2f}). New entries and position flips prohibited."
                ),
            )

        # Gate 2: Expiry-Day Naked Short Option Protection
        if (
            is_expiry_day
            and self.limits.prohibit_expiry_naked_shorts
            and not is_pure_closing
            and order.side == OrderSide.SELL
            and is_naked_short
        ):
            return RiskCheckResult(
                passed=False,
                reason=RiskRejectionReason.EXPIRY_NAKED_SHORT_PROHIBITED,
                detail=f"Unhedged naked short option on expiry day prohibited for {order.symbol}.",
            )

        # Gate 3: Maximum Margin Utilization (85% Ceiling)
        if not is_pure_closing:
            released_margin = float(existing_qty_abs) * current_market_price if is_opposite else 0.0
            order_margin = float(net_new_qty) * current_market_price
            projected_used_margin = max(0.0, balance.used_margin - released_margin) + order_margin
            total_cap = (
                balance.total_capital if balance.total_capital > 0.0 else self.initial_capital
            )

            utilization_pct = (projected_used_margin / total_cap) if total_cap > 0.0 else 1.0

            if utilization_pct > self.limits.max_margin_utilization_pct:
                return RiskCheckResult(
                    passed=False,
                    reason=RiskRejectionReason.MARGIN_LIMIT_EXCEEDED,
                    detail=(
                        f"Projected margin utilization ({utilization_pct * 100:.1f}%) exceeds "
                        f"institutional ceiling ({self.limits.max_margin_utilization_pct * 100:.1f}%)."
                    ),
                )

        # Gate 4: Maximum Position Limits (lots)
        if not is_pure_closing:
            if lot_size is not None:
                self.lot_sizes[order.symbol] = lot_size
            sym_lot_size = lot_size or self.lot_sizes.get(order.symbol, 1)

            order_lots = self.resolve_lots(order.symbol, order.qty, default_lot_size=sym_lot_size)
            existing_lots = (
                self.resolve_lots(order.symbol, existing_qty_abs, default_lot_size=sym_lot_size)
                if is_opposite
                else 0
            )
            net_new_lots = max(0, order_lots - existing_lots) if is_opposite else order_lots

            total_current_lots = sum(
                self.resolve_lots(
                    p.symbol,
                    p.qty,
                    default_lot_size=sym_lot_size if p.symbol == order.symbol else 1,
                )
                for p in positions.values()
            )
            projected_lots = total_current_lots - existing_lots + net_new_lots
            if projected_lots > self.limits.max_concurrent_lots:
                return RiskCheckResult(
                    passed=False,
                    reason=RiskRejectionReason.POSITION_LIMIT_EXCEEDED,
                    detail=(
                        f"Order lots ({order_lots}) brings total lots ({projected_lots}) "
                        f"above maximum allowable ({self.limits.max_concurrent_lots})."
                    ),
                )

        return RiskCheckResult(passed=True)
