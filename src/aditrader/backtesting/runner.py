"""Deterministic backtesting engine and execution orchestrator.

Per ARCHITECTURE.md and .agents/skills/backtesting-engine.md:
- Strictly enforces zero lookahead bias:
  At bar index T, only data closed at or before T is accessible.
- Default execution occurs at next-bar open (T+1) with realistic slippage.
  Same-bar close execution only exists where explicitly configured.
- Fully deterministic replay: identical inputs yield identical outputs.
- Connects: DataFeed -> ExecutableStrategy -> RiskEngine -> PaperBroker.
"""

from collections import deque
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from aditrader.backtesting.analytics.metrics import PerformanceReport, generate_performance_report
from aditrader.core.broker import PaperBroker
from aditrader.core.costs import SlippageModel
from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType, SignalDirection
from aditrader.core.models.execution import Trade
from aditrader.core.models.market_data import Bar
from aditrader.core.models.order import Order
from aditrader.core.models.trade_signal import Signal
from aditrader.core.risk.engine import RiskEngine
from aditrader.core.risk.models import RiskLimits
from aditrader.core.state_machine import OrderStateMachine
from aditrader.data.feeds.base import DataFeed
from aditrader.strategy.compiler.engine import ExecutableStrategy


class BacktestConfig(BaseModel):
    """Execution simulation configuration for backtesting runs."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    initial_capital: float = Field(
        default=1_000_000.0, gt=0.0, description="Starting cash capital in INR"
    )
    trade_lots: int = Field(default=1, gt=0, description="Order execution quantity (lots/shares)")
    allow_same_bar_execution: bool = Field(
        default=False,
        description="If True, fills at current bar close; if False, fills at next-bar open (default anti-lookahead)",
    )
    risk_free_rate: float = Field(
        default=0.065, ge=0.0, description="Annualized benchmark risk-free rate"
    )
    periods_per_year: int = Field(
        default=252, gt=0, description="Frequency scaling factor for Sharpe/Sortino"
    )
    slippage_model: SlippageModel | None = Field(
        default=None, description="Custom slippage model configuration"
    )
    risk_limits: RiskLimits | None = Field(
        default=None, description="Pre-trade institutional risk thresholds"
    )


class BacktestResult(BaseModel):
    """Complete immutable audit trail of a completed backtest run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = Field(..., description="Name of the evaluated strategy")
    underlying: str = Field(..., description="Target asset symbol")
    bar_count: int = Field(..., ge=0, description="Total historical bars processed")
    signals: list[Signal] = Field(default_factory=list, description="All emitted signals")
    orders: list[Order] = Field(default_factory=list, description="All submitted orders")
    trades: list[Trade] = Field(default_factory=list, description="All executed fills")
    equity_curve: list[float] = Field(
        default_factory=list, description="Point-in-time equity values"
    )
    equity_timestamps: list[datetime] = Field(
        default_factory=list, description="Timestamps corresponding to equity curve"
    )
    performance: PerformanceReport = Field(..., description="Institutional performance summary")


class BacktestRunner:
    """Deterministic orchestrator executing strategies against historical data."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(
        self,
        strategy: ExecutableStrategy,
        data: DataFeed | list[Bar],
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> BacktestResult:
        """Execute deterministic backtest simulation.

        Args:
            strategy: Compiled ExecutableStrategy instance.
            data: DataFeed provider or pre-loaded chronological list of Bar objects.
            start_time: Optional start window filter if passing a DataFeed.
            end_time: Optional end window filter if passing a DataFeed.

        Returns:
            BacktestResult containing complete event history and performance metrics.
        """
        if isinstance(data, list):
            bars = data
        else:
            s_time = start_time or datetime(2000, 1, 1, tzinfo=UTC)
            e_time = end_time or datetime(2099, 1, 1, tzinfo=UTC)
            bars = data.get_history(
                symbol=strategy.dsl.underlying, start_time=s_time, end_time=e_time
            )

        if not bars:
            raise ValueError("Backtest data is empty. At least one bar is required.")

        # Initialize isolated execution subsystems
        broker = PaperBroker(
            initial_capital=self.config.initial_capital,
            slippage_model=self.config.slippage_model,
        )
        risk_engine = RiskEngine(
            limits=self.config.risk_limits,
            initial_capital=self.config.initial_capital,
        )
        strategy.reset()

        recorded_signals: list[Signal] = []
        equity_curve: list[float] = []
        equity_timestamps: list[datetime] = []
        pending_signal: Signal | None = None

        n_bars = len(bars)
        for i in range(n_bars):
            bar = bars[i]
            history = bars[: i + 1]

            # ------------------------------------------------------------------
            # 1. Fill Pending Signal from Bar T-1 at Bar T Open (Default Anti-Lookahead)
            # ------------------------------------------------------------------
            if pending_signal is not None and not self.config.allow_same_bar_execution:
                self._process_signal_execution(
                    signal=pending_signal,
                    execution_price=bar.open,
                    timestamp=bar.timestamp,
                    broker=broker,
                    risk_engine=risk_engine,
                )
                pending_signal = None

            # ------------------------------------------------------------------
            # 2. Update Position MTM and Risk High-Water Mark
            # ------------------------------------------------------------------
            broker.on_tick(strategy.dsl.underlying, ltp=bar.close, timestamp=bar.timestamp)

            current_balance = broker.get_account_balance()
            risk_engine.update_equity(current_balance.total_capital)

            # ------------------------------------------------------------------
            # 3. Strategy Evaluation at Candle Close
            # ------------------------------------------------------------------
            signal = strategy.on_bar(history)

            if signal is not None:
                recorded_signals.append(signal)

                if self.config.allow_same_bar_execution:
                    # Configured Same-Bar Close Execution
                    self._process_signal_execution(
                        signal=signal,
                        execution_price=bar.close,
                        timestamp=bar.timestamp,
                        broker=broker,
                        risk_engine=risk_engine,
                    )
                else:
                    # Stage for next-bar open fill
                    pending_signal = signal

            # ------------------------------------------------------------------
            # 4. Record Equity Snapshot
            # ------------------------------------------------------------------
            snap_balance = broker.get_account_balance()
            equity_curve.append(snap_balance.total_capital)
            equity_timestamps.append(bar.timestamp)

        # ----------------------------------------------------------------------
        # 5. Roundtrip PnL Matching & Performance Report Generation
        # ----------------------------------------------------------------------
        executed_trades = broker.get_trades()
        roundtrip_pnls = self._calculate_roundtrip_pnls(executed_trades)

        performance = generate_performance_report(
            starting_equity=self.config.initial_capital,
            equity_curve=equity_curve,
            trade_pnls=roundtrip_pnls,
            risk_free_rate=self.config.risk_free_rate,
            periods_per_year=self.config.periods_per_year,
        )

        all_orders = broker.get_orders()

        return BacktestResult(
            strategy_name=strategy.dsl.name,
            underlying=strategy.dsl.underlying,
            bar_count=n_bars,
            signals=recorded_signals,
            orders=all_orders,
            trades=executed_trades,
            equity_curve=equity_curve,
            equity_timestamps=equity_timestamps,
            performance=performance,
        )

    def _process_signal_execution(
        self,
        signal: Signal,
        execution_price: float,
        timestamp: datetime,
        broker: PaperBroker,
        risk_engine: RiskEngine,
    ) -> None:
        """Route signal through pre-trade risk engine before broker execution."""
        side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        tentative_order = broker.create_order(
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            qty=self.config.trade_lots,
            signal_id=f"SIG-{signal.timestamp.isoformat()}",
            timestamp=timestamp,
        )

        balance = broker.get_account_balance()
        positions_map = {p.symbol: p for p in broker.get_positions()}

        is_expiry_day = bool(signal.metadata.get("is_expiry_day", False))
        is_naked_short = bool(signal.metadata.get("is_naked_short", False))

        risk_check = risk_engine.validate_order(
            order=tentative_order,
            balance=balance,
            positions=positions_map,
            current_market_price=execution_price,
            is_expiry_day=is_expiry_day,
            is_naked_short=is_naked_short,
        )

        if not risk_check.passed:
            # Order rejected by pre-trade risk engine
            prefix = f"{risk_check.reason.value}: " if risk_check.reason else ""
            rejection_reason = f"{prefix}{risk_check.detail or 'Risk gate rejection'}"
            rejected_order = OrderStateMachine.transition(
                tentative_order,
                OrderStatus.REJECTED,
                timestamp=timestamp,
                rejection_reason=rejection_reason,
            )
            broker._orders[rejected_order.order_id] = rejected_order
            return

        broker.submit_order(
            tentative_order,
            current_market_price=execution_price,
            timestamp=timestamp,
        )

    def _calculate_roundtrip_pnls(self, trades: list[Trade]) -> list[float]:
        """Compute realized FIFO PnLs for roundtrip closed positions."""
        long_inventory: deque[tuple[int, float, float]] = deque()  # (qty, price, fees)
        short_inventory: deque[tuple[int, float, float]] = deque()
        pnls: list[float] = []

        for t in trades:
            trade_fees = t.stt + t.charges + t.slippage
            remaining_qty = t.qty

            if t.side == OrderSide.BUY:
                # First match against open short positions
                while remaining_qty > 0 and short_inventory:
                    s_qty, s_price, s_fees = short_inventory.popleft()
                    match_qty = min(remaining_qty, s_qty)
                    prop_fee = (match_qty / t.qty) * trade_fees + (match_qty / s_qty) * s_fees
                    pnl = (s_price - t.fill_price) * match_qty - prop_fee
                    pnls.append(round(pnl, 2))

                    remaining_qty -= match_qty
                    if s_qty > match_qty:
                        short_inventory.appendleft((s_qty - match_qty, s_price, s_fees - prop_fee))

                # Any residual BUY opens/adds to long position
                if remaining_qty > 0:
                    long_inventory.append((remaining_qty, t.fill_price, trade_fees))

            else:  # SELL
                # Match against open long positions
                while remaining_qty > 0 and long_inventory:
                    l_qty, l_price, l_fees = long_inventory.popleft()
                    match_qty = min(remaining_qty, l_qty)
                    prop_fee = (match_qty / t.qty) * trade_fees + (match_qty / l_qty) * l_fees
                    pnl = (t.fill_price - l_price) * match_qty - prop_fee
                    pnls.append(round(pnl, 2))

                    remaining_qty -= match_qty
                    if l_qty > match_qty:
                        long_inventory.appendleft((l_qty - match_qty, l_price, l_fees - prop_fee))

                # Any residual SELL opens/adds to short position
                if remaining_qty > 0:
                    short_inventory.append((remaining_qty, t.fill_price, trade_fees))

        return pnls
