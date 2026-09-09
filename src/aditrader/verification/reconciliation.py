"""Balance sheet reconciliation engine enforcing fundamental accounting invariants.

Audits:
1. Balance Sheet Invariant:
   Ending Equity = Starting Capital + Net Profit
2. Trade & Position Accretion Invariant:
   Net Profit = Realized Roundtrip PnL + Terminal Unrealized PnL - Open Position Charges
3. Physical Currency Precision:
   Reconciliation holds within 1 paisa (₹0.01).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.execution import Position, Trade
from aditrader.verification.tolerances import TOLERANCE_MONETARY

logger = logging.getLogger(__name__)


class ReconciliationReport(BaseModel):
    """Detailed balance sheet reconciliation report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_reconciled: bool = Field(
        ..., description="True if balance sheet invariants hold within tolerance"
    )
    starting_capital: float = Field(..., description="Starting capital in INR")
    ending_equity: float = Field(..., description="Observed ending portfolio capital")
    total_realized_pnl: float = Field(..., description="Sum of closed roundtrip trade PnLs")
    total_unrealized_pnl: float = Field(
        ..., description="Mark-to-market unrealized PnL of open positions"
    )
    total_charges: float = Field(
        ..., description="Cumulative statutory exchange taxes and brokerage"
    )
    expected_equity: float = Field(
        ..., description="Starting Capital + Realized + Unrealized - Open Charges"
    )
    equity_discrepancy: float = Field(..., description="Ending Equity minus Expected Equity")
    cash_balance: float | None = Field(
        default=None, description="Current broker cash balance if available"
    )
    portfolio_market_value: float | None = Field(default=None, description="Sum of pos.qty * LTP")
    tolerance: float = Field(
        default=TOLERANCE_MONETARY, description="Allowed currency tolerance (1 paisa)"
    )
    details: str = Field(default="", description="Audit conclusion summary")


class ReconciliationChecker:
    """Verifies internal accounting consistency of backtest and forward sessions."""

    @classmethod
    def audit_session(
        cls,
        *,
        starting_capital: float,
        ending_equity: float,
        net_profit: float,
        positions: list[Position] | None = None,
        trades: list[Trade] | None = None,
        realized_roundtrip_pnls: list[float] | None = None,
        unrealized_pnl: float = 0.0,
        total_statutory_charges: float | None = None,
        cash_balance: float | None = None,
    ) -> ReconciliationReport:
        """Verify the complete ledger balance sheet against executed trades and fees."""
        pos_list = positions or []
        trade_list = trades or []

        # 1. Closed roundtrip realized PnL
        if realized_roundtrip_pnls is not None:
            realized = round(sum(realized_roundtrip_pnls), 2)
        else:
            realized = round(sum(p.realized_pnl for p in pos_list), 2)

        # 2. Terminal unrealized PnL
        unrealized = round(
            unrealized_pnl if unrealized_pnl != 0.0 else sum(p.unrealized_pnl for p in pos_list),
            2,
        )

        # 3. Total charges incurred across executed trades
        charges = round(
            total_statutory_charges
            if total_statutory_charges is not None
            else sum((t.charges + t.stt) for t in trade_list),
            2,
        )

        # 4. ADR 010 Portfolio Market Value: sum(pos.qty * ltp)
        portfolio_market_val = 0.0
        for p in pos_list:
            if p.qty != 0:
                if p.qty > 0 and p.buy_avg_price > 0:
                    ltp = p.buy_avg_price + (p.unrealized_pnl / p.qty)
                    portfolio_market_val += p.qty * ltp
                elif p.qty < 0 and p.sell_avg_price > 0:
                    ltp = p.sell_avg_price - (p.unrealized_pnl / abs(p.qty))
                    portfolio_market_val += p.qty * ltp
        portfolio_market_val = round(portfolio_market_val, 2)

        # 5. Expected ending equity by net accretion
        expected_equity = round(starting_capital + net_profit, 2)
        observed_equity = round(ending_equity, 2)
        equity_discrepancy = round(abs(observed_equity - expected_equity), 2)

        # 6. Substantive Net Profit Invariant: Net Profit == Realized + Unrealized - Charges
        # Only evaluate if execution records (trades or positions) were provided
        has_execution_records = bool(trade_list or pos_list or realized_roundtrip_pnls is not None)
        computed_net_profit = round(realized + unrealized - charges, 2)
        net_profit_discrepancy = (
            round(abs(net_profit - computed_net_profit), 2) if has_execution_records else 0.0
        )

        # 7. Cash Balance Reconciliation: Ending Equity == Cash Balance + Portfolio Market Value
        cash_discrepancy = 0.0
        if cash_balance is not None:
            expected_from_cash = round(cash_balance + portfolio_market_val, 2)
            cash_discrepancy = round(abs(observed_equity - expected_from_cash), 2)

        is_reconciled = (
            equity_discrepancy <= TOLERANCE_MONETARY
            and net_profit_discrepancy <= TOLERANCE_MONETARY
            and cash_discrepancy <= TOLERANCE_MONETARY
        )

        if is_reconciled:
            details = (
                f"Balance sheet perfectly reconciled: Expected ₹{expected_equity:.2f} == Observed ₹{observed_equity:.2f} "
                f"(realized: ₹{realized:.2f}, unrealized: ₹{unrealized:.2f}, charges: ₹{charges:.2f}, "
                f"equity_delta: ₹{equity_discrepancy:.2f})"
            )
        else:
            reasons = []
            if equity_discrepancy > TOLERANCE_MONETARY:
                reasons.append(
                    f"Equity mismatch: Expected ₹{expected_equity:.2f} vs Observed ₹{observed_equity:.2f} (delta: ₹{equity_discrepancy:.2f})"
                )
            if net_profit_discrepancy > TOLERANCE_MONETARY:
                reasons.append(
                    f"Net profit mismatch: Reported ₹{net_profit:.2f} != Realized(₹{realized:.2f}) + Unrealized(₹{unrealized:.2f}) - Charges(₹{charges:.2f}) [Computed: ₹{computed_net_profit:.2f}, delta: ₹{net_profit_discrepancy:.2f}]"
                )
            if cash_discrepancy > TOLERANCE_MONETARY:
                reasons.append(
                    f"Cash + Holdings mismatch: Equity ₹{observed_equity:.2f} != Cash(₹{cash_balance:.2f}) + MarketVal(₹{portfolio_market_val:.2f}) [delta: ₹{cash_discrepancy:.2f}]"
                )
            details = "ACCOUNTING MISMATCH: " + "; ".join(reasons)

        return ReconciliationReport(
            is_reconciled=is_reconciled,
            starting_capital=starting_capital,
            ending_equity=observed_equity,
            total_realized_pnl=realized,
            total_unrealized_pnl=unrealized,
            total_charges=charges,
            expected_equity=expected_equity,
            equity_discrepancy=equity_discrepancy,
            cash_balance=cash_balance,
            portfolio_market_value=portfolio_market_val,
            tolerance=TOLERANCE_MONETARY,
            details=details,
        )
