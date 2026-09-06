"""Pre-trade execution risk engine and safety barrier.

Per ARCHITECTURE.md and .agents/skills/risk-engine.md:
Evaluates pre-trade margin utilization (85% ceiling), portfolio drawdown
circuit breakers (5% limit), and unhedged expiry-day gamma protection.
Completely decoupled from strategy generation and evaluated at order submission.
"""

from aditrader.core.models.enums import OrderSide
from aditrader.core.models.execution import AccountBalance, Position
from aditrader.core.models.order import Order
from aditrader.core.risk.models import RiskCheckResult, RiskLimits, RiskRejectionReason


class RiskEngine:
    """Institutional pre-trade risk engine and portfolio safety gatekeeper."""

    def __init__(
        self, limits: RiskLimits | None = None, initial_capital: float = 1_000_000.0
    ) -> None:
        self.limits = limits or RiskLimits()
        self.initial_capital = initial_capital
        self.peak_equity = initial_capital
        self.current_equity = initial_capital
        self._circuit_breaker_active = False

    @property
    def circuit_breaker_active(self) -> bool:
        """Indicates whether portfolio drawdown circuit breaker is currently active."""
        return self._circuit_breaker_active

    def update_equity(self, current_equity: float) -> None:
        """Update current portfolio equity and evaluate circuit breaker threshold."""
        self.current_equity = current_equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        if self.peak_equity > 0.0:
            dd_pct = (self.peak_equity - current_equity) / self.peak_equity
            if dd_pct >= self.limits.portfolio_drawdown_limit_pct:
                self._circuit_breaker_active = True

    def reset(self) -> None:
        """Reset equity high-water mark and clear circuit breaker."""
        self.peak_equity = self.initial_capital
        self.current_equity = self.initial_capital
        self._circuit_breaker_active = False

    def validate_order(
        self,
        order: Order,
        balance: AccountBalance,
        positions: dict[str, Position],
        current_market_price: float,
        *,
        is_expiry_day: bool = False,
        is_naked_short: bool = False,
    ) -> RiskCheckResult:
        """Validate order against active pre-trade institutional risk gates.

        Args:
            order: Proposed Order to be executed.
            balance: Current point-in-time AccountBalance snapshot.
            positions: Map of active portfolio positions.
            current_market_price: Prevailing price for estimated margin calculations.
            is_expiry_day: True if current bar date is expiration date.
            is_naked_short: True if order represents an unhedged naked short option.

        Returns:
            RiskCheckResult indicating pass or failure classification.
        """
        existing_pos = positions.get(order.symbol)
        is_closing = False
        if (
            existing_pos
            and existing_pos.qty != 0
            and (
                (existing_pos.qty > 0 and order.side == OrderSide.SELL)
                or (existing_pos.qty < 0 and order.side == OrderSide.BUY)
            )
        ):
            is_closing = True

        # Gate 1: Portfolio Drawdown Circuit Breaker
        # Closing orders are always permitted to reduce portfolio risk.
        if self._circuit_breaker_active and not is_closing:
            return RiskCheckResult(
                passed=False,
                reason=RiskRejectionReason.CIRCUIT_BREAKER_ACTIVE,
                detail=(
                    f"Portfolio drawdown circuit breaker active (peak: {self.peak_equity:.2f}, "
                    f"current: {self.current_equity:.2f}). New entries prohibited."
                ),
            )

        # Gate 2: Expiry-Day Naked Short Option Protection
        if (
            is_expiry_day
            and self.limits.prohibit_expiry_naked_shorts
            and not is_closing
            and order.side == OrderSide.SELL
            and is_naked_short
        ):
            return RiskCheckResult(
                passed=False,
                reason=RiskRejectionReason.EXPIRY_NAKED_SHORT_PROHIBITED,
                detail=f"Unhedged naked short option on expiry day prohibited for {order.symbol}.",
            )

        # Gate 3: Maximum Margin Utilization (85% Ceiling)
        if not is_closing:
            order_margin = float(order.qty) * current_market_price
            projected_used_margin = balance.used_margin + order_margin
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
        if not is_closing:
            total_current_lots = sum(abs(p.qty) for p in positions.values())
            if total_current_lots + order.qty > self.limits.max_concurrent_lots:
                return RiskCheckResult(
                    passed=False,
                    reason=RiskRejectionReason.POSITION_LIMIT_EXCEEDED,
                    detail=(
                        f"Order qty ({order.qty}) brings total lots ({total_current_lots + order.qty}) "
                        f"above maximum allowable ({self.limits.max_concurrent_lots})."
                    ),
                )

        return RiskCheckResult(passed=True)
