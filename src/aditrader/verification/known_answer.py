"""Deterministic Known-Answer Testing (KAT) framework.

Provides pre-computed analytical benchmarks and high-risk boundary vectors
for cash P&L, statutory taxes, lot sizing, Black-Scholes Greeks, payoff curves,
risk metrics, and adversarial edge cases.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aditrader.backtesting.analytics.metrics import (
    calculate_expectancy,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_sqn,
)
from aditrader.core.broker import PaperBroker
from aditrader.core.costs import CostCalculator, SlippageModel
from aditrader.core.models.enums import OrderSide, OrderType
from aditrader.data.instruments.specs import resolve_contract_specs
from aditrader.options.greeks import calculate_greeks
from aditrader.options.iv import black_scholes_price
from aditrader.options.models import OptionLeg
from aditrader.options.payoff import calculate_leg_expiry_pnl
from aditrader.verification.tolerances import (
    TOLERANCE_GREEKS,
    TOLERANCE_MONETARY,
    TOLERANCE_PERCENT,
    TOLERANCE_RATIO,
)


class KATResult(BaseModel):
    """Outcome of an individual known-answer test vector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector_id: str = Field(..., description="Unique test vector identifier")
    category: str = Field(..., description="Subsystem category (e.g. PnL, TAX, GREEKS)")
    description: str = Field(..., description="Specification of what is being tested")
    passed: bool = Field(..., description="True if observed matches expected within tolerance")
    observed_output: Any = Field(default=None, description="Value produced by current engine")
    expected_output: Any = Field(default=None, description="Pre-computed analytical ground truth")
    delta: float | None = Field(default=None, description="Absolute difference if numerical")
    tolerance: float = Field(default=0.0, description="Calibrated tolerance applied")
    error_message: str | None = Field(
        default=None, description="Diagnostic error details if failed"
    )


class KATSuiteResult(BaseModel):
    """Aggregate summary of executing the full deterministic KAT suite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_tests: int = Field(ge=0)
    passed_tests: int = Field(ge=0)
    failed_tests: int = Field(ge=0)
    results: list[KATResult] = Field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True if 100% of KAT vectors passed."""
        return self.failed_tests == 0 and self.total_tests > 0


class KnownAnswerTestEngine:
    """Deterministic testing engine executing analytical ground-truth test vectors."""

    @classmethod
    def run_all(cls) -> KATSuiteResult:
        """Execute the complete catalog of known-answer test vectors."""
        results: list[KATResult] = []

        # 1. Cash PnL Vectors
        results.extend(cls._test_pnl_vectors())

        # 2. Statutory Taxes and Charges Vectors
        results.extend(cls._test_tax_vectors())

        # 3. Lot Sizing Vectors
        results.extend(cls._test_lot_sizing_vectors())

        # 4. Black-Scholes Greeks Benchmarks (Hull Analytical Standards)
        results.extend(cls._test_greeks_benchmarks())

        # 5. Options At-Expiry Payoff Points
        results.extend(cls._test_payoff_points())

        # 6. Performance & Risk Analytics
        results.extend(cls._test_performance_metrics())

        # 7. High-Risk Edge Cases (N=0, N=1, 100% Win, Flat Equity, Expiry Boundary)
        results.extend(cls._test_edge_cases())

        # 8. Negative Tests (Deliberately Broken Inputs & Tamper Detection)
        results.extend(cls._test_negative_cases())

        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed

        return KATSuiteResult(
            total_tests=len(results),
            passed_tests=passed,
            failed_tests=failed,
            results=results,
        )

    # --------------------------------------------------------------------------
    # Vector Test Implementations
    # --------------------------------------------------------------------------

    @staticmethod
    def _test_pnl_vectors() -> list[KATResult]:
        results: list[KATResult] = []

        # Vector 1: Long trade: Buy 50 @ 100, Sell 50 @ 150 = +2500 (Grounded via PaperBroker)
        b_long = PaperBroker(
            initial_capital=100_000.0,
            slippage_model=SlippageModel(fixed_points=0.0, percentage=0.0),
        )
        o1 = b_long.create_order(
            symbol="NIFTY", side=OrderSide.BUY, qty=50, order_type=OrderType.MARKET
        )
        b_long.submit_order(o1, current_market_price=100.0, bid=100.0, ask=100.0)
        o2 = b_long.create_order(
            symbol="NIFTY", side=OrderSide.SELL, qty=50, order_type=OrderType.MARKET
        )
        b_long.submit_order(o2, current_market_price=150.0, bid=150.0, ask=150.0)
        pos_long = next(p for p in b_long.get_positions() if p.symbol == "NIFTY")
        pnl_long = pos_long.realized_pnl
        delta_long = abs(pnl_long - 2500.0)
        results.append(
            KATResult(
                vector_id="KAT-PNL-001",
                category="PNL_ACCOUNTING",
                description="Long Trade: Buy 50 @ 100, Sell 50 @ 150 (PaperBroker)",
                passed=delta_long <= TOLERANCE_MONETARY,
                observed_output=pnl_long,
                expected_output=2500.0,
                delta=delta_long,
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Vector 2: Short trade: Sell 50 @ 150, Buy 50 @ 100 = +2500 (Grounded via PaperBroker)
        b_short = PaperBroker(
            initial_capital=100_000.0,
            slippage_model=SlippageModel(fixed_points=0.0, percentage=0.0),
        )
        s1 = b_short.create_order(
            symbol="NIFTY", side=OrderSide.SELL, qty=50, order_type=OrderType.MARKET
        )
        b_short.submit_order(s1, current_market_price=150.0, bid=150.0, ask=150.0)
        s2 = b_short.create_order(
            symbol="NIFTY", side=OrderSide.BUY, qty=50, order_type=OrderType.MARKET
        )
        b_short.submit_order(s2, current_market_price=100.0, bid=100.0, ask=100.0)
        pos_short = next(p for p in b_short.get_positions() if p.symbol == "NIFTY")
        pnl_short = pos_short.realized_pnl
        delta_short = abs(pnl_short - 2500.0)
        results.append(
            KATResult(
                vector_id="KAT-PNL-002",
                category="PNL_ACCOUNTING",
                description="Short Trade: Sell 50 @ 150, Buy 50 @ 100 (PaperBroker)",
                passed=delta_short <= TOLERANCE_MONETARY,
                observed_output=pnl_short,
                expected_output=2500.0,
                delta=delta_short,
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Vector 3: Losing trade: Buy 100 @ 200, Sell 100 @ 180 = -2000 (Grounded via PaperBroker)
        b_loss = PaperBroker(
            initial_capital=100_000.0,
            slippage_model=SlippageModel(fixed_points=0.0, percentage=0.0),
        )
        l1 = b_loss.create_order(
            symbol="NIFTY", side=OrderSide.BUY, qty=100, order_type=OrderType.MARKET
        )
        b_loss.submit_order(l1, current_market_price=200.0, bid=200.0, ask=200.0)
        l2 = b_loss.create_order(
            symbol="NIFTY", side=OrderSide.SELL, qty=100, order_type=OrderType.MARKET
        )
        b_loss.submit_order(l2, current_market_price=180.0, bid=180.0, ask=180.0)
        pos_loss = next(p for p in b_loss.get_positions() if p.symbol == "NIFTY")
        pnl_loss = pos_loss.realized_pnl
        delta_loss = abs(pnl_loss - (-2000.0))
        results.append(
            KATResult(
                vector_id="KAT-PNL-003",
                category="PNL_ACCOUNTING",
                description="Losing Long Trade: Buy 100 @ 200, Sell 100 @ 180 (PaperBroker)",
                passed=delta_loss <= TOLERANCE_MONETARY,
                observed_output=pnl_loss,
                expected_output=-2000.0,
                delta=delta_loss,
                tolerance=TOLERANCE_MONETARY,
            )
        )

        return results

    @staticmethod
    def _test_tax_vectors() -> list[KATResult]:
        results: list[KATResult] = []

        # Vector 1: Options SELL (50 contracts @ 100)
        c_opt_sell = CostCalculator.calculate(
            side=OrderSide.SELL, qty=50, price=100.0, instrument="OPTIONS"
        )
        # Expected: stt=5.00, exchange=2.50, sebi=0.01, stamp=0.00, brokerage=20.00, gst=4.05, total=31.56
        delta_total = abs(c_opt_sell.total_charges - 31.56)
        results.append(
            KATResult(
                vector_id="KAT-TAX-001",
                category="STATUTORY_TAXES",
                description="Options SELL: 50 @ 100.0 (STT 0.1% on premium, 18% GST)",
                passed=delta_total <= TOLERANCE_MONETARY
                and c_opt_sell.stt == 5.0
                and c_opt_sell.gst == 4.05,
                observed_output=c_opt_sell.total_charges,
                expected_output=31.56,
                delta=delta_total,
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Vector 2: Options BUY (50 contracts @ 100)
        c_opt_buy = CostCalculator.calculate(
            side=OrderSide.BUY, qty=50, price=100.0, instrument="OPTIONS"
        )
        # Expected: stt=0.00, exchange=2.50, sebi=0.01, stamp=0.15, brokerage=20.00, gst=4.05, total=26.71
        delta_buy = abs(c_opt_buy.total_charges - 26.71)
        results.append(
            KATResult(
                vector_id="KAT-TAX-002",
                category="STATUTORY_TAXES",
                description="Options BUY: 50 @ 100.0 (Stamp Duty 0.003%, zero STT)",
                passed=delta_buy <= TOLERANCE_MONETARY
                and c_opt_buy.stt == 0.0
                and c_opt_buy.stamp_duty == 0.15,
                observed_output=c_opt_buy.total_charges,
                expected_output=26.71,
                delta=delta_buy,
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Vector 3: Futures SELL (100 contracts @ 500)
        c_fut_sell = CostCalculator.calculate(
            side=OrderSide.SELL, qty=100, price=500.0, instrument="FUTURES"
        )
        # Expected: turnover=50,000; stt=10.00, exchange=1.00, sebi=0.05, stamp=0.00, brokerage=20.00, gst=3.79, total=34.84
        delta_fut = abs(c_fut_sell.total_charges - 34.84)
        results.append(
            KATResult(
                vector_id="KAT-TAX-003",
                category="STATUTORY_TAXES",
                description="Futures SELL: 100 @ 500.0 (STT 0.02% on turnover)",
                passed=delta_fut <= TOLERANCE_MONETARY and c_fut_sell.stt == 10.0,
                observed_output=c_fut_sell.total_charges,
                expected_output=34.84,
                delta=delta_fut,
                tolerance=TOLERANCE_MONETARY,
            )
        )

        return results

    @staticmethod
    def _test_lot_sizing_vectors() -> list[KATResult]:
        results: list[KATResult] = []

        # NIFTY lot size is 25
        step_nifty, lot_nifty = resolve_contract_specs("NIFTY")
        results.append(
            KATResult(
                vector_id="KAT-LOT-001",
                category="LOT_SIZING",
                description="NIFTY Index Contract Specifications (Lot size = 25, Strike step = 50.0)",
                passed=(lot_nifty == 25 and step_nifty == 50.0),
                observed_output={"lot_size": lot_nifty, "strike_step": step_nifty},
                expected_output={"lot_size": 25, "strike_step": 50.0},
                tolerance=0.0,
            )
        )

        # BANKNIFTY lot size is 15
        step_bnf, lot_bnf = resolve_contract_specs("BANKNIFTY")
        results.append(
            KATResult(
                vector_id="KAT-LOT-002",
                category="LOT_SIZING",
                description="BANKNIFTY Contract Specifications (Lot size = 15, Strike step = 100.0)",
                passed=(lot_bnf == 15 and step_bnf == 100.0),
                observed_output={"lot_size": lot_bnf, "strike_step": step_bnf},
                expected_output={"lot_size": 15, "strike_step": 100.0},
                tolerance=0.0,
            )
        )

        # RELIANCE lot size is 250
        step_rel, lot_rel = resolve_contract_specs("RELIANCE")
        results.append(
            KATResult(
                vector_id="KAT-LOT-003",
                category="LOT_SIZING",
                description="RELIANCE Stock Option Specifications (Lot size = 250, Strike step = 20.0)",
                passed=(lot_rel == 250 and step_rel == 20.0),
                observed_output={"lot_size": lot_rel, "strike_step": step_rel},
                expected_output={"lot_size": 250, "strike_step": 20.0},
                tolerance=0.0,
            )
        )

        return results

    @staticmethod
    def _test_greeks_benchmarks() -> list[KATResult]:
        results: list[KATResult] = []

        # Benchmark: Hull Textbook S=100, K=100, T=1.0, r=0.05, vol=0.20
        # European Call Price = 10.4506, Delta = 0.6368, Gamma = 0.01876, Vega = 0.3752
        p_ce = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=1.0,
            volatility=0.20,
            risk_free_rate=0.05,
            option_type="CE",
        )
        g_ce = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=1.0,
            volatility=0.20,
            risk_free_rate=0.05,
            option_type="CE",
        )

        d_price = abs(p_ce - 10.4506)
        d_delta = abs(g_ce.delta - 0.6368)
        d_gamma = abs(g_ce.gamma - 0.01876)
        d_vega = abs(g_ce.vega - 0.3752)

        results.append(
            KATResult(
                vector_id="KAT-BS-001",
                category="BLACK_SCHOLES",
                description="Hull Textbook Standard: Call Price (S=100, K=100, T=1, r=0.05, vol=0.20)",
                passed=d_price <= TOLERANCE_GREEKS,
                observed_output=round(p_ce, 4),
                expected_output=10.4506,
                delta=d_price,
                tolerance=TOLERANCE_GREEKS,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-BS-002",
                category="BLACK_SCHOLES",
                description="Hull Textbook Standard: Call Delta (N(d1) = 0.6368)",
                passed=d_delta <= TOLERANCE_GREEKS,
                observed_output=round(g_ce.delta, 4),
                expected_output=0.6368,
                delta=d_delta,
                tolerance=TOLERANCE_GREEKS,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-BS-003",
                category="BLACK_SCHOLES",
                description="Hull Textbook Standard: Call Gamma (0.01876)",
                passed=d_gamma <= TOLERANCE_GREEKS,
                observed_output=round(g_ce.gamma, 5),
                expected_output=0.01876,
                delta=d_gamma,
                tolerance=TOLERANCE_GREEKS,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-BS-004",
                category="BLACK_SCHOLES",
                description="Hull Textbook Standard: Call Vega per 1% vol (0.3752)",
                passed=d_vega <= TOLERANCE_GREEKS,
                observed_output=round(g_ce.vega, 4),
                expected_output=0.3752,
                delta=d_vega,
                tolerance=TOLERANCE_GREEKS,
            )
        )

        # Put-Call Parity: P = C - S + K * exp(-rT)
        p_pe = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=1.0,
            volatility=0.20,
            risk_free_rate=0.05,
            option_type="PE",
        )
        expected_pe = p_ce - 100.0 + 100.0 * math.exp(-0.05)
        d_parity = abs(p_pe - expected_pe)
        results.append(
            KATResult(
                vector_id="KAT-BS-005",
                category="BLACK_SCHOLES",
                description="Put-Call Parity Verification (P == C - S + K*exp(-rT))",
                passed=d_parity <= TOLERANCE_GREEKS,
                observed_output=round(p_pe, 4),
                expected_output=round(expected_pe, 4),
                delta=d_parity,
                tolerance=TOLERANCE_GREEKS,
            )
        )

        return results

    @staticmethod
    def _test_payoff_points() -> list[KATResult]:
        results: list[KATResult] = []

        exp_dt = datetime(2026, 9, 24, 15, 30, tzinfo=UTC)
        # Long Call: Strike 100, Entry 5, Qty 1
        leg_call = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=100.0,
            option_type="CE",
            side=OrderSide.BUY,
            entry_price=5.0,
            qty=1,
            lot_size=1,
        )
        # Spot 90 -> -5.0
        pnl_90 = calculate_leg_expiry_pnl(leg_call, 90.0)
        # Spot 105 -> 0.0 (breakeven)
        pnl_105 = calculate_leg_expiry_pnl(leg_call, 105.0)
        # Spot 120 -> +15.0
        pnl_120 = calculate_leg_expiry_pnl(leg_call, 120.0)

        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-001",
                category="OPTIONS_PAYOFF",
                description="Long Call Strike 100 Entry 5.0: PnL at Spot 90 (-5.0)",
                passed=abs(pnl_90 - (-5.0)) <= TOLERANCE_MONETARY,
                observed_output=pnl_90,
                expected_output=-5.0,
                delta=abs(pnl_90 - (-5.0)),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-002",
                category="OPTIONS_PAYOFF",
                description="Long Call Strike 100 Entry 5.0: Breakeven at Spot 105 (0.0)",
                passed=abs(pnl_105 - 0.0) <= TOLERANCE_MONETARY,
                observed_output=pnl_105,
                expected_output=0.0,
                delta=abs(pnl_105 - 0.0),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-003",
                category="OPTIONS_PAYOFF",
                description="Long Call Strike 100 Entry 5.0: Profit at Spot 120 (+15.0)",
                passed=abs(pnl_120 - 15.0) <= TOLERANCE_MONETARY,
                observed_output=pnl_120,
                expected_output=15.0,
                delta=abs(pnl_120 - 15.0),
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Bull Call Spread: Buy 100 CE @ 6, Sell 110 CE @ 2. Net Debit = 4.
        leg_buy = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=100.0,
            option_type="CE",
            side=OrderSide.BUY,
            entry_price=6.0,
            qty=1,
            lot_size=1,
        )
        leg_sell = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=110.0,
            option_type="CE",
            side=OrderSide.SELL,
            entry_price=2.0,
            qty=1,
            lot_size=1,
        )

        # Spot 90: Buy gives -6, Sell gives +2 => Net = -4 (max loss)
        spread_90 = calculate_leg_expiry_pnl(leg_buy, 90.0) + calculate_leg_expiry_pnl(
            leg_sell, 90.0
        )
        # Spot 104: Buy gives -2, Sell gives +2 => Net = 0 (breakeven)
        spread_104 = calculate_leg_expiry_pnl(leg_buy, 104.0) + calculate_leg_expiry_pnl(
            leg_sell, 104.0
        )
        # Spot 120: Buy gives 14, Sell gives -8 => Net = +6 (max profit)
        spread_120 = calculate_leg_expiry_pnl(leg_buy, 120.0) + calculate_leg_expiry_pnl(
            leg_sell, 120.0
        )

        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-004",
                category="OPTIONS_PAYOFF",
                description="Bull Call Spread 100/110 Debit 4.0: Max Loss at Spot 90 (-4.0)",
                passed=abs(spread_90 - (-4.0)) <= TOLERANCE_MONETARY,
                observed_output=spread_90,
                expected_output=-4.0,
                delta=abs(spread_90 - (-4.0)),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-005",
                category="OPTIONS_PAYOFF",
                description="Bull Call Spread 100/110 Debit 4.0: Breakeven at Spot 104 (0.0)",
                passed=abs(spread_104 - 0.0) <= TOLERANCE_MONETARY,
                observed_output=spread_104,
                expected_output=0.0,
                delta=abs(spread_104 - 0.0),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-006",
                category="OPTIONS_PAYOFF",
                description="Bull Call Spread 100/110 Debit 4.0: Max Profit at Spot 120 (+6.0)",
                passed=abs(spread_120 - 6.0) <= TOLERANCE_MONETARY,
                observed_output=spread_120,
                expected_output=6.0,
                delta=abs(spread_120 - 6.0),
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Long Straddle: Buy 100 CE @ 5.0, Buy 100 PE @ 5.0. Net Debit = 10.0
        leg_straddle_ce = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=100.0,
            option_type="CE",
            side=OrderSide.BUY,
            entry_price=5.0,
            qty=1,
            lot_size=1,
        )
        leg_straddle_pe = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=100.0,
            option_type="PE",
            side=OrderSide.BUY,
            entry_price=5.0,
            qty=1,
            lot_size=1,
        )
        # Spot 100: Max Loss = -10.0
        straddle_100 = calculate_leg_expiry_pnl(leg_straddle_ce, 100.0) + calculate_leg_expiry_pnl(
            leg_straddle_pe, 100.0
        )
        # Spot 110: Upper Breakeven = 0.0
        straddle_110 = calculate_leg_expiry_pnl(leg_straddle_ce, 110.0) + calculate_leg_expiry_pnl(
            leg_straddle_pe, 110.0
        )
        # Spot 90: Lower Breakeven = 0.0
        straddle_90 = calculate_leg_expiry_pnl(leg_straddle_ce, 90.0) + calculate_leg_expiry_pnl(
            leg_straddle_pe, 90.0
        )

        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-007",
                category="OPTIONS_PAYOFF",
                description="Long Straddle 100 Debit 10.0: Max Loss at Strike 100 (-10.0)",
                passed=abs(straddle_100 - (-10.0)) <= TOLERANCE_MONETARY,
                observed_output=straddle_100,
                expected_output=-10.0,
                delta=abs(straddle_100 - (-10.0)),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-008",
                category="OPTIONS_PAYOFF",
                description="Long Straddle 100 Debit 10.0: Upper Breakeven at Spot 110 (0.0)",
                passed=abs(straddle_110 - 0.0) <= TOLERANCE_MONETARY,
                observed_output=straddle_110,
                expected_output=0.0,
                delta=abs(straddle_110 - 0.0),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-009",
                category="OPTIONS_PAYOFF",
                description="Long Straddle 100 Debit 10.0: Lower Breakeven at Spot 90 (0.0)",
                passed=abs(straddle_90 - 0.0) <= TOLERANCE_MONETARY,
                observed_output=straddle_90,
                expected_output=0.0,
                delta=abs(straddle_90 - 0.0),
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Iron Condor: Buy 90 PE @ 1, Sell 95 PE @ 3, Sell 105 CE @ 3, Buy 110 CE @ 1. Net Credit = +4.0
        leg_ic_p_long = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=90.0,
            option_type="PE",
            side=OrderSide.BUY,
            entry_price=1.0,
            qty=1,
            lot_size=1,
        )
        leg_ic_p_short = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=95.0,
            option_type="PE",
            side=OrderSide.SELL,
            entry_price=3.0,
            qty=1,
            lot_size=1,
        )
        leg_ic_c_short = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=105.0,
            option_type="CE",
            side=OrderSide.SELL,
            entry_price=3.0,
            qty=1,
            lot_size=1,
        )
        leg_ic_c_long = OptionLeg(
            underlying="NIFTY",
            expiry=exp_dt,
            strike=110.0,
            option_type="CE",
            side=OrderSide.BUY,
            entry_price=1.0,
            qty=1,
            lot_size=1,
        )
        ic_legs = [leg_ic_p_long, leg_ic_p_short, leg_ic_c_short, leg_ic_c_long]

        # Spot 100 (in between 95 and 105): All expire OTM -> Net = +4.0 (Max Profit)
        ic_100 = sum(calculate_leg_expiry_pnl(leg, 100.0) for leg in ic_legs)
        # Spot 85 (below 90 PE): Put wing max loss = -1.0
        ic_85 = sum(calculate_leg_expiry_pnl(leg, 85.0) for leg in ic_legs)
        # Spot 115 (above 110 CE): Call wing max loss = -1.0
        ic_115 = sum(calculate_leg_expiry_pnl(leg, 115.0) for leg in ic_legs)

        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-010",
                category="OPTIONS_PAYOFF",
                description="Iron Condor 90/95/105/110 Credit 4.0: Max Profit in Body at Spot 100 (+4.0)",
                passed=abs(ic_100 - 4.0) <= TOLERANCE_MONETARY,
                observed_output=ic_100,
                expected_output=4.0,
                delta=abs(ic_100 - 4.0),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-011",
                category="OPTIONS_PAYOFF",
                description="Iron Condor 90/95/105/110 Credit 4.0: Put Wing Max Loss at Spot 85 (-1.0)",
                passed=abs(ic_85 - (-1.0)) <= TOLERANCE_MONETARY,
                observed_output=ic_85,
                expected_output=-1.0,
                delta=abs(ic_85 - (-1.0)),
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-PAYOFF-012",
                category="OPTIONS_PAYOFF",
                description="Iron Condor 90/95/105/110 Credit 4.0: Call Wing Max Loss at Spot 115 (-1.0)",
                passed=abs(ic_115 - (-1.0)) <= TOLERANCE_MONETARY,
                observed_output=ic_115,
                expected_output=-1.0,
                delta=abs(ic_115 - (-1.0)),
                tolerance=TOLERANCE_MONETARY,
            )
        )

        return results

    @staticmethod
    def _test_performance_metrics() -> list[KATResult]:
        results: list[KATResult] = []

        # Hand-calculated equity curve: [1000, 1200, 900, 1100, 800, 1300]
        # Peak 1200, lowest after peak 800 => max DD amt = 400.0, pct = 400/1200 = 0.333333...
        eq_curve = [1000.0, 1200.0, 900.0, 1100.0, 800.0, 1300.0]
        dd = calculate_max_drawdown(eq_curve)
        delta_dd_amt = abs(dd.max_drawdown_amount - 400.0)
        delta_dd_pct = abs(dd.max_drawdown_pct - (400.0 / 1200.0))

        results.append(
            KATResult(
                vector_id="KAT-METRIC-001",
                category="RISK_ANALYTICS",
                description="Max Drawdown Amount: [1000, 1200, 900, 1100, 800, 1300] (Peak 1200 -> Trough 800 = 400)",
                passed=delta_dd_amt <= TOLERANCE_MONETARY,
                observed_output=dd.max_drawdown_amount,
                expected_output=400.0,
                delta=delta_dd_amt,
                tolerance=TOLERANCE_MONETARY,
            )
        )
        results.append(
            KATResult(
                vector_id="KAT-METRIC-002",
                category="RISK_ANALYTICS",
                description="Max Drawdown Percentage: 400.0 / 1200.0 = 33.333%",
                passed=delta_dd_pct <= TOLERANCE_PERCENT,
                observed_output=round(dd.max_drawdown_pct, 6),
                expected_output=round(400.0 / 1200.0, 6),
                delta=delta_dd_pct,
                tolerance=TOLERANCE_PERCENT,
            )
        )

        # Mathematical Expectancy: [100, -50, 200, -50, 100] -> Total = 300 / 5 = 60.0
        trade_pnls = [100.0, -50.0, 200.0, -50.0, 100.0]
        exp_val = calculate_expectancy(trade_pnls)
        delta_exp = abs(exp_val - 60.0)
        results.append(
            KATResult(
                vector_id="KAT-METRIC-003",
                category="PERFORMANCE_ANALYTICS",
                description="Mathematical Expectancy: [100, -50, 200, -50, 100] (Mean = 60.0)",
                passed=delta_exp <= TOLERANCE_MONETARY,
                observed_output=exp_val,
                expected_output=60.0,
                delta=delta_exp,
                tolerance=TOLERANCE_MONETARY,
            )
        )

        # Profit Factor: Gross profit = 400, Gross loss = 100 => PF = 4.0
        pf_val = calculate_profit_factor(trade_pnls)
        delta_pf = abs((pf_val or 0.0) - 4.0)
        results.append(
            KATResult(
                vector_id="KAT-METRIC-004",
                category="PERFORMANCE_ANALYTICS",
                description="Profit Factor: Gross Profit (400) / Gross Loss (100) = 4.0",
                passed=delta_pf <= TOLERANCE_RATIO,
                observed_output=pf_val,
                expected_output=4.0,
                delta=delta_pf,
                tolerance=TOLERANCE_RATIO,
            )
        )

        return results

    @staticmethod
    def _test_edge_cases() -> list[KATResult]:
        results: list[KATResult] = []

        # Edge Case 1: Zero Trades (N = 0)
        exp_zero = calculate_expectancy([])
        pf_zero = calculate_profit_factor([])
        sqn_zero = calculate_sqn([])
        results.append(
            KATResult(
                vector_id="KAT-EDGE-001",
                category="STATISTICAL_EDGES",
                description="Zero Trades (N=0): Expectancy == 0.0, PF == 0.0, SQN == None",
                passed=(exp_zero == 0.0 and pf_zero == 0.0 and sqn_zero is None),
                observed_output={"expectancy": exp_zero, "profit_factor": pf_zero, "sqn": sqn_zero},
                expected_output={"expectancy": 0.0, "profit_factor": 0.0, "sqn": None},
                tolerance=0.0,
            )
        )

        # Edge Case 2: Single Trade (N = 1) -> sample variance undefined
        sqn_single = calculate_sqn([100.0])
        sharpe_single = calculate_sharpe_ratio([0.01])
        sortino_single = calculate_sortino_ratio([0.01])
        results.append(
            KATResult(
                vector_id="KAT-EDGE-002",
                category="STATISTICAL_EDGES",
                description="Single Trade (N=1): Sharpe, Sortino, SQN return None (undefined variance)",
                passed=(sqn_single is None and sharpe_single is None and sortino_single is None),
                observed_output={
                    "sharpe": sharpe_single,
                    "sortino": sortino_single,
                    "sqn": sqn_single,
                },
                expected_output={"sharpe": None, "sortino": None, "sqn": None},
                tolerance=0.0,
            )
        )

        # Edge Case 3: Zero Gross Losses (100% Win Rate)
        # Under ADR 011, Profit Factor must return None (NOT float('inf')), Sortino must return None
        pf_noloss = calculate_profit_factor([100.0, 200.0, 50.0])
        sortino_noloss = calculate_sortino_ratio([0.01, 0.02, 0.015])
        results.append(
            KATResult(
                vector_id="KAT-EDGE-003",
                category="STATISTICAL_EDGES",
                description="Zero Losses (100% Win): Profit Factor == None, Sortino == None (ADR 011)",
                passed=(pf_noloss is None and sortino_noloss is None),
                observed_output={"profit_factor": pf_noloss, "sortino": sortino_noloss},
                expected_output={"profit_factor": None, "sortino": None},
                tolerance=0.0,
            )
        )

        # Edge Case 4: Flat Equity Curve (Zero Return Variance)
        sharpe_flat = calculate_sharpe_ratio([0.0, 0.0, 0.0])
        sortino_flat = calculate_sortino_ratio([0.0, 0.0, 0.0])
        results.append(
            KATResult(
                vector_id="KAT-EDGE-004",
                category="STATISTICAL_EDGES",
                description="Flat Equity Curve: Sharpe and Sortino return None (zero variance)",
                passed=(sharpe_flat is None and sortino_flat is None),
                observed_output={"sharpe": sharpe_flat, "sortino": sortino_flat},
                expected_output={"sharpe": None, "sortino": None},
                tolerance=0.0,
            )
        )

        # Edge Case 5: Options Expiry Boundary (T <= 1e-7)
        # At expiry, ITM Call Delta = 1.0, Gamma = 0.0, Vega = 0.0
        g_exp_itm = calculate_greeks(
            spot=110.0, strike=100.0, time_to_expiry=1e-8, volatility=0.20, option_type="CE"
        )
        # At expiry, OTM Call Delta = 0.0
        g_exp_otm = calculate_greeks(
            spot=90.0, strike=100.0, time_to_expiry=1e-8, volatility=0.20, option_type="CE"
        )

        results.append(
            KATResult(
                vector_id="KAT-EDGE-005",
                category="OPTIONS_EXPIRY_BOUNDARY",
                description="Expiry Boundary (T <= 1e-7): ITM Delta == 1.0, OTM Delta == 0.0, Gamma == Vega == 0.0",
                passed=(
                    abs(g_exp_itm.delta - 1.0) <= TOLERANCE_GREEKS
                    and abs(g_exp_otm.delta - 0.0) <= TOLERANCE_GREEKS
                    and g_exp_itm.gamma == 0.0
                    and g_exp_itm.vega == 0.0
                ),
                observed_output={
                    "itm_delta": g_exp_itm.delta,
                    "otm_delta": g_exp_otm.delta,
                    "gamma": g_exp_itm.gamma,
                },
                expected_output={"itm_delta": 1.0, "otm_delta": 0.0, "gamma": 0.0},
                tolerance=TOLERANCE_GREEKS,
            )
        )

        return results

    @staticmethod
    def _test_negative_cases() -> list[KATResult]:
        results: list[KATResult] = []

        # Negative Test 1: Non-positive prices to calculate_greeks must raise ValueError
        threw_on_negative_spot = False
        try:
            calculate_greeks(
                spot=-100.0, strike=100.0, time_to_expiry=1.0, volatility=0.20, option_type="CE"
            )
        except ValueError:
            threw_on_negative_spot = True

        results.append(
            KATResult(
                vector_id="KAT-NEG-001",
                category="DEFENSIVE_GUARDS",
                description="Negative Spot Price rejected with ValueError",
                passed=threw_on_negative_spot,
                observed_output="ValueError Raised" if threw_on_negative_spot else "No Exception",
                expected_output="ValueError Raised",
                tolerance=0.0,
            )
        )

        # Negative Test 2: Negative strike to calculate_greeks must raise ValueError
        threw_on_negative_strike = False
        try:
            calculate_greeks(
                spot=100.0, strike=-50.0, time_to_expiry=1.0, volatility=0.20, option_type="CE"
            )
        except ValueError:
            threw_on_negative_strike = True

        results.append(
            KATResult(
                vector_id="KAT-NEG-002",
                category="DEFENSIVE_GUARDS",
                description="Negative Strike Price rejected with ValueError",
                passed=threw_on_negative_strike,
                observed_output="ValueError Raised" if threw_on_negative_strike else "No Exception",
                expected_output="ValueError Raised",
                tolerance=0.0,
            )
        )

        return results
