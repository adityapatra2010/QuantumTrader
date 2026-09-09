"""Deterministic backtesting engine and execution orchestrator.

Per ARCHITECTURE.md, SPEC.md, and hostile audit remediation contracts:
- Strictly enforces zero lookahead bias:
  At bar index T, only data closed at or before T is accessible.
- Default execution occurs at next-bar open (T+1) with realistic slippage.
  Same-bar close execution only exists where explicitly configured and is flagged
  as ACADEMIC_EXPLORATORY.
- Fully deterministic replay: identical inputs yield identical outputs and Merkle roots.
- Two-sided high/low price clamping with explicit liquidity breach detection.
- Proportional transaction fee attribution on position reversals (no double counting).
- Authoritative TradeLedger and BacktestEvent stream sealed with SHA-256 digests.
- Structured RunDossier generation with atomic persistence to runs/backtest/.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections import deque
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.backtesting.analytics.metrics import (
    PerformanceReport,
    calculate_expectancy,
    generate_performance_report,
    resolve_periods_per_year,
)
from aditrader.backtesting.models import (
    BacktestEvent,
    ExecutionContractType,
    ExecutionEventType,
    RoundtripTrade,
    RunDossier,
    TradeLedger,
    compute_binary_merkle_root,
)
from aditrader.core.broker import PaperBroker
from aditrader.core.costs import CostCalculator, SlippageModel, resolve_instrument_class
from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType, SignalDirection
from aditrader.core.models.execution import Position, Trade
from aditrader.core.models.market_data import Bar, MarketDataSourceType
from aditrader.core.models.order import Order
from aditrader.core.models.trade_signal import Signal
from aditrader.core.risk.engine import RiskEngine
from aditrader.core.risk.models import RiskLimits
from aditrader.core.state_machine import OrderStateMachine
from aditrader.data.feeds.base import DataFeed
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.compiler.engine import ExecutableStrategy
from aditrader.verification.integrity import DataIntegrityChecker
from aditrader.verification.reconciliation import ReconciliationChecker

logger = logging.getLogger(__name__)


class UnsupportedStrategyError(ValueError):
    """Raised when a strategy definition cannot be deterministically simulated by the runner."""


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
    execution_contract: ExecutionContractType = Field(
        default=ExecutionContractType.INSTITUTIONAL_STRICT,
        description="Execution standard applied (INSTITUTIONAL_STRICT vs ACADEMIC_EXPLORATORY)",
    )
    risk_free_rate: float = Field(
        default=0.065, ge=0.0, description="Annualized benchmark risk-free rate"
    )
    periods_per_year: int | None = Field(
        default=None,
        gt=0,
        description="Frequency scaling factor for Sharpe/Sortino (defaults to timeframe-resolved factor)",
    )
    slippage_model: SlippageModel | None = Field(
        default=None, description="Custom slippage model configuration"
    )
    risk_limits: RiskLimits | None = Field(
        default=None, description="Pre-trade institutional risk thresholds"
    )
    max_volume_participation_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Maximum fraction of candle volume an order can consume (e.g., 0.10 for 10%)",
    )
    volume_limit_action: Literal["REJECT", "PARTIAL_FILL"] = Field(
        default="REJECT",
        description="Deterministic policy when order quantity exceeds volume participation ceiling ('REJECT' or 'PARTIAL_FILL')",
    )
    intraday_auto_squareoff: bool = Field(
        default=True,
        description="Enforce mandatory 15:15 IST auto-square-off on intraday positions",
    )
    strict_liquidity_rejection: bool = Field(
        default=False,
        description="Reject orders exceeding candle high/low boundary rather than clamping",
    )
    run_id: str | None = Field(default=None, description="Optional custom run ID")
    dataset_path: str | None = Field(
        default=None, description="Path to historical dataset on disk for audit provenance"
    )
    created_at: datetime | None = Field(
        default=None, description="Optional pinned timestamp for deterministic replay testing"
    )


class SimulationAssumptions(BaseModel):
    """Explicit recorded assumptions under which the historical simulation was conducted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_resolution: str | None = Field(
        default=None, description="Timeframe/resolution of data feed (e.g. '1m', '5m')"
    )
    quotes_present: bool = Field(
        default=False, description="Whether genuine bid/ask quotes were present in data"
    )
    fill_assumption: Literal["NEXT_BAR_OPEN", "SAME_BAR_CLOSE", "TICK_LEVEL", "MID_PRICE"] = Field(
        ..., description="Execution fill timing assumption"
    )
    slippage_model: str = Field(..., description="Slippage model name and configuration")
    slippage_bps: float = Field(default=0.0, description="Base slippage basis points")
    cost_model: str = Field(
        default="NSE_STATUTORY", description="Statutory and transaction fee schedule applied"
    )
    volume_participation_enforced: bool = Field(
        default=False, description="Whether volume participation limits were active"
    )
    max_volume_participation_pct: float | None = Field(
        default=None, description="Max candle volume participation ceiling"
    )
    volume_limit_action: str = Field(
        default="REJECT", description="Action taken when order exceeds volume ceiling"
    )
    data_source_type: MarketDataSourceType = Field(
        default=MarketDataSourceType.HISTORICAL_RECORD,
        description="Origin classification of input feed",
    )
    data_source_name: str | None = Field(
        default=None, description="Identifier of data feed provider or file"
    )
    is_synthetic_data: bool = Field(
        default=False, description="True if simulated/synthetic data was used"
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
    terminal_positions: list[Position] = Field(
        default_factory=list,
        description="Active open positions remaining unclosed at the end of the simulation",
    )
    terminal_unrealized_pnl: float = Field(
        default=0.0,
        description="Mark-to-market unrealized PnL of remaining open positions at final bar",
    )
    liquidated_ending_equity: float | None = Field(
        default=None,
        description="Hypothetical ending equity if all terminal open positions were liquidated at final bar close with friction",
    )
    terminal_adjusted_expectancy: float | None = Field(
        default=None,
        description="Expectancy factoring in liquidation of terminal unclosed positions",
    )
    performance: PerformanceReport = Field(..., description="Institutional performance summary")
    simulation_assumptions: SimulationAssumptions | None = Field(
        default=None,
        description="Audit record of explicit simulation assumptions applied during backtest",
    )
    dossier: RunDossier | None = Field(
        default=None,
        description="Cryptographically verified RunDossier with full event and trade ledgers",
    )
    events: list[BacktestEvent] = Field(
        default_factory=list, description="Chronological event stream recorded during replay"
    )
    ledger: list[RoundtripTrade] = Field(
        default_factory=list, description="Structured roundtrip trade ledger records"
    )
    event_stream_merkle_root: str | None = Field(
        default=None, description="SHA-256 Merkle root of event stream"
    )
    trade_ledger_merkle_root: str | None = Field(
        default=None, description="SHA-256 Merkle root of trade ledger"
    )


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
        """Execute deterministic backtest simulation and produce complete Run Dossier."""
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

        # Guard 1: Reject multi-leg option strategies from silent spot execution (ADR 011)
        if strategy.dsl.legs:
            raise UnsupportedStrategyError(
                f"Strategy '{strategy.dsl.name}' defines {len(strategy.dsl.legs)} option leg(s). "
                "BacktestRunner only simulates underlying spot/futures candle execution. "
                "Simulating multi-leg option strategies requires option-chain tick data and synthetic "
                "IV surface modeling (OptionsBacktestRunner). Silent proxy execution of option legs "
                "against underlying spot prices is strictly prohibited."
            )

        # Guard 2: Reject single-leg option contracts passed as underlying (Finding 9.2)
        inst_class = resolve_instrument_class(strategy.dsl.underlying)
        if inst_class == "OPTIONS":
            raise UnsupportedStrategyError(
                f"Underlying '{strategy.dsl.underlying}' is classified as an option contract. "
                "BacktestRunner simulates only linear spot and futures assets (ADR 011). "
                "Option contracts require point-in-time chain replay and Black-Scholes Greeks modeling."
            )

        # Guard 3: Pre-replay Data Integrity Verification
        is_syn = any(b.is_synthetic for b in bars) if bars else False
        integrity_rep = DataIntegrityChecker.audit_bars(
            bars,
            source_identifier=strategy.dsl.underlying,
            is_options_dataset=False,
        )
        if not integrity_rep.is_valid and not is_syn:
            raise ValueError(
                f"Dataset integrity verification failed: {'; '.join(integrity_rep.errors)}"
            )

        run_id = self.config.run_id or f"run_bt_{secrets.token_hex(4)}"

        # Initialize isolated execution subsystems
        broker = PaperBroker(
            initial_capital=self.config.initial_capital,
            slippage_model=self.config.slippage_model,
            deterministic=True,
        )
        risk_engine = RiskEngine(
            limits=self.config.risk_limits,
            initial_capital=self.config.initial_capital,
        )
        strategy.reset()

        events: list[BacktestEvent] = []
        event_seq = 0

        def record_event(
            event_type: ExecutionEventType,
            symbol: str,
            timestamp: datetime,
            details: dict[str, Any],
        ) -> None:
            nonlocal event_seq
            event_seq += 1
            evt = BacktestEvent(
                event_id=f"EVT-{event_seq:06d}",
                sequence_num=event_seq,
                timestamp=timestamp,
                event_type=event_type,
                symbol=symbol,
                details=details,
            )
            events.append(evt)

        recorded_signals: list[Signal] = []
        equity_curve: list[float] = []
        equity_timestamps: list[datetime] = []
        pending_signal: Signal | None = None
        current_session_date: date | None = None

        n_bars = len(bars)
        is_intraday = strategy.dsl.timeframe in ("1m", "5m", "15m", "30m", "1h")

        for i in range(n_bars):
            bar = bars[i]
            history = bars[: i + 1]

            record_event(
                ExecutionEventType.BAR_OBSERVED,
                strategy.dsl.underlying,
                bar.timestamp,
                {
                    "bar_index": i,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                },
            )

            # ------------------------------------------------------------------
            # 0. Intraday Session Transition Detection & Risk State Reset
            # ------------------------------------------------------------------
            bar_date = bar.timestamp.date()
            if current_session_date is None or bar_date != current_session_date:
                if current_session_date is not None and pending_signal is not None and is_intraday:
                    record_event(
                        ExecutionEventType.UNFULFILLED_SIGNAL,
                        pending_signal.symbol,
                        bar.timestamp,
                        {
                            "reason": "SESSION_BOUNDARY_CANCELLATION",
                            "staged_from": pending_signal.timestamp.isoformat(),
                        },
                    )
                    pending_signal = None
                current_session_date = bar_date
                pre_balance = broker.get_account_balance()
                risk_engine.on_session_start(bar.timestamp, pre_balance.total_capital)
                record_event(
                    ExecutionEventType.SESSION_START,
                    strategy.dsl.underlying,
                    bar.timestamp,
                    {
                        "session_date": str(bar_date),
                        "opening_equity": pre_balance.total_capital,
                    },
                )

            # ------------------------------------------------------------------
            # 1. Fill Pending Signal from Bar T-1 at Bar T Open (Default Anti-Lookahead)
            # ------------------------------------------------------------------
            if pending_signal is not None and not self.config.allow_same_bar_execution:
                record_event(
                    ExecutionEventType.EXECUTION_ELIGIBILITY,
                    pending_signal.symbol,
                    bar.timestamp,
                    {
                        "signal_id": f"SIG-{pending_signal.timestamp.isoformat()}",
                        "direction": pending_signal.direction.value,
                        "execution_price": bar.open,
                    },
                )
                self._process_signal_execution(
                    signal=pending_signal,
                    execution_price=bar.open,
                    timestamp=bar.timestamp,
                    bar=bar,
                    broker=broker,
                    risk_engine=risk_engine,
                    strategy=strategy,
                    record_event_fn=record_event,
                )
                pending_signal = None

            # ------------------------------------------------------------------
            # 2. Update Position MTM and Match Pending Limit Orders
            # ------------------------------------------------------------------
            broker.on_tick(strategy.dsl.underlying, ltp=bar.close, timestamp=bar.timestamp)
            current_balance = broker.get_account_balance()
            risk_engine.update_equity(current_balance.total_capital)

            record_event(
                ExecutionEventType.ACCOUNT_UPDATED,
                strategy.dsl.underlying,
                bar.timestamp,
                {
                    "cash": broker.cash_balance,
                    "equity": current_balance.total_capital,
                    "unrealized_pnl": current_balance.unrealized_pnl,
                },
            )

            # ------------------------------------------------------------------
            # 3. Strategy Evaluation at Candle Close (Synchronized Position State)
            # ------------------------------------------------------------------
            bar_ist = (
                bar.timestamp.astimezone(EXCHANGE_TIMEZONE)
                if bar.timestamp.tzinfo
                else bar.timestamp
            )
            is_past_intraday_cutoff = (
                is_intraday
                and self.config.intraday_auto_squareoff
                and bar_ist.time() >= time(15, 15)
            )

            has_active_position = any(
                p.symbol == strategy.dsl.underlying and p.qty != 0 for p in broker.get_positions()
            )
            strategy.sync_position_state(has_active_position)

            if is_past_intraday_cutoff:
                signal = None
                record_event(
                    ExecutionEventType.STRATEGY_EVALUATED,
                    strategy.dsl.underlying,
                    bar.timestamp,
                    {
                        "has_position": has_active_position,
                        "signal_emitted": False,
                        "cutoff_active": True,
                    },
                )
            else:
                signal = strategy.on_bar(history, position_active=has_active_position)
                record_event(
                    ExecutionEventType.STRATEGY_EVALUATED,
                    strategy.dsl.underlying,
                    bar.timestamp,
                    {
                        "has_position": has_active_position,
                        "signal_emitted": signal is not None,
                    },
                )

            if signal is not None:
                recorded_signals.append(signal)
                record_event(
                    ExecutionEventType.SIGNAL_GENERATED,
                    signal.symbol,
                    bar.timestamp,
                    {
                        "direction": signal.direction.value,
                        "action": signal.metadata.get("action", "UNKNOWN"),
                        "confidence": signal.confidence,
                    },
                )

                if self.config.allow_same_bar_execution:
                    # Configured Same-Bar Close Execution (Academic Exploratory)
                    self._process_signal_execution(
                        signal=signal,
                        execution_price=bar.close,
                        timestamp=bar.timestamp,
                        bar=bar,
                        broker=broker,
                        risk_engine=risk_engine,
                        strategy=strategy,
                        record_event_fn=record_event,
                    )
                else:
                    # Stage for next-bar open fill
                    pending_signal = signal
                    record_event(
                        ExecutionEventType.ORDER_STAGED,
                        signal.symbol,
                        bar.timestamp,
                        {"target_timing": "NEXT_BAR_OPEN"},
                    )

            # ------------------------------------------------------------------
            # 4. Mandatory Intraday 15:15 IST Auto-Squareoff Sweep (Finding 6.1)
            # ------------------------------------------------------------------
            if (
                self.config.intraday_auto_squareoff
                and is_intraday
                and bar_ist.time() >= time(15, 15)
            ):
                if pending_signal is not None:
                    record_event(
                        ExecutionEventType.UNFULFILLED_SIGNAL,
                        pending_signal.symbol,
                        bar.timestamp,
                        {
                            "reason": "INTRADAY_CUTOFF_PURGE",
                            "signal_id": f"SIG-{pending_signal.timestamp.isoformat()}",
                        },
                    )
                    pending_signal = None

                for p in broker.get_positions():
                    if p.symbol == strategy.dsl.underlying and p.qty != 0:
                        sq_side = OrderSide.SELL if p.qty > 0 else OrderSide.BUY
                        record_event(
                            ExecutionEventType.SESSION_SQUAREOFF,
                            p.symbol,
                            bar.timestamp,
                            {"position_qty": p.qty, "closing_price": bar.close},
                        )
                        sq_order = broker.create_order(
                            symbol=p.symbol,
                            side=sq_side,
                            order_type=OrderType.MARKET,
                            qty=abs(p.qty),
                            signal_id=f"SQOFF-{bar.timestamp.isoformat()}",
                            timestamp=bar.timestamp,
                        )
                        broker.submit_order(
                            sq_order,
                            current_market_price=bar.close,
                            timestamp=bar.timestamp,
                            exact_fill_price=bar.close,
                            slippage=0.0,
                        )
                        strategy.sync_position_state(False)

            # ------------------------------------------------------------------
            # 5. Record Equity Snapshot
            # ------------------------------------------------------------------
            snap_balance = broker.get_account_balance()
            equity_curve.append(snap_balance.total_capital)
            equity_timestamps.append(bar.timestamp)

        # ----------------------------------------------------------------------
        # 6. Terminal State Transitions & Unfulfilled Signals (Finding 1.2)
        # ----------------------------------------------------------------------
        if pending_signal is not None:
            record_event(
                ExecutionEventType.UNFULFILLED_SIGNAL,
                pending_signal.symbol,
                bars[-1].timestamp,
                {
                    "signal_id": f"SIG-{pending_signal.timestamp.isoformat()}",
                    "reason": "DATASET_TERMINUS_REACHED_BEFORE_NEXT_BAR",
                },
            )
            pending_signal = None

        record_event(
            ExecutionEventType.RUN_TERMINATED,
            strategy.dsl.underlying,
            bars[-1].timestamp,
            {
                "total_bars": n_bars,
                "final_equity": snap_balance.total_capital,
            },
        )

        # ----------------------------------------------------------------------
        # 7. Terminal Open Positions Accounting (Mark-to-Market & Liquidation)
        # ----------------------------------------------------------------------
        terminal_positions = [p for p in broker.get_positions() if p.qty != 0]
        terminal_unrealized_pnl = snap_balance.unrealized_pnl
        liquidated_ending_equity: float | None = None

        if terminal_positions:
            liq_friction = 0.0
            last_close = bars[-1].close
            for p in terminal_positions:
                liq_side = OrderSide.SELL if p.qty > 0 else OrderSide.BUY
                fill_p, slip = broker.slippage_model.calculate_fill_price(last_close, liq_side)
                instr_type = resolve_instrument_class(p.symbol)
                chgs = CostCalculator.calculate(
                    side=liq_side,
                    qty=abs(p.qty),
                    price=fill_p,
                    instrument=instr_type,
                )
                liq_friction += chgs.total_charges + (slip * abs(p.qty))
            liquidated_ending_equity = round(snap_balance.total_capital - liq_friction, 2)

        # ----------------------------------------------------------------------
        # 8. Authoritative Roundtrip Trade Ledger Generation (Findings 4.1 & 4.3)
        # ----------------------------------------------------------------------
        executed_trades = broker.get_trades()
        roundtrip_trades = self._build_roundtrip_trades(executed_trades, run_id=run_id)
        trade_ledger = TradeLedger.create(run_id=run_id, trades=roundtrip_trades)

        closed_trades = [t for t in roundtrip_trades if t.is_closed]
        roundtrip_pnls = [t.net_pnl for t in closed_trades]

        effective_periods_per_year = (
            self.config.periods_per_year
            if self.config.periods_per_year is not None
            else resolve_periods_per_year(strategy.dsl.timeframe)
        )

        performance = generate_performance_report(
            starting_equity=self.config.initial_capital,
            equity_curve=equity_curve,
            trade_pnls=roundtrip_pnls,
            risk_free_rate=self.config.risk_free_rate,
            periods_per_year=effective_periods_per_year,
        )

        # Dual Expectancy Calculation (Finding 4.3)
        closed_trade_expectancy = calculate_expectancy(roundtrip_pnls)
        if terminal_positions and liquidated_ending_equity is not None:
            total_liquidated_pnl = round(liquidated_ending_equity - self.config.initial_capital, 2)
            total_eval_count = len(closed_trades) + len(terminal_positions)
            terminal_adjusted_expectancy = (
                round(total_liquidated_pnl / total_eval_count, 2) if total_eval_count > 0 else 0.0
            )
        else:
            terminal_adjusted_expectancy = closed_trade_expectancy

        all_orders = broker.get_orders()

        # Compute binary Merkle root of event stream
        event_hashes = [e.compute_hash() for e in events]
        event_merkle_root = compute_binary_merkle_root(event_hashes)

        # Simulation Assumptions
        src_type = (
            MarketDataSourceType.SYNTHETIC_TEST
            if is_syn
            else MarketDataSourceType.HISTORICAL_RECORD
        )
        src_name: str = "in_memory_bars"
        dataset_path_str: str = "memory://bars"
        dataset_content_hash: str = hashlib.sha256(b"IN_MEMORY_BARS").hexdigest()

        resolved_ds_path = self.config.dataset_path or (
            str(data.file_path) if hasattr(data, "file_path") and data.file_path else None
        )
        if resolved_ds_path:
            p_obj = Path(resolved_ds_path)
            src_name = p_obj.name
            dataset_path_str = str(p_obj)
            try:
                with open(p_obj, "rb") as f:
                    dataset_content_hash = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                pass
        elif bars and bars[0].source:
            src_name = bars[0].source

        slip_name = (
            self.config.slippage_model.__class__.__name__
            if self.config.slippage_model
            else "SlippageModel"
        )
        slip_bps = (
            round(float(getattr(self.config.slippage_model, "percentage", 0.0)) * 10000.0, 2)
            if self.config.slippage_model
            else 0.0
        )

        assumptions = SimulationAssumptions(
            data_resolution=strategy.dsl.timeframe,
            quotes_present=False,
            fill_assumption=(
                "SAME_BAR_CLOSE" if self.config.allow_same_bar_execution else "NEXT_BAR_OPEN"
            ),
            slippage_model=slip_name,
            slippage_bps=slip_bps,
            cost_model="NSE_STATUTORY",
            volume_participation_enforced=self.config.max_volume_participation_pct is not None,
            max_volume_participation_pct=self.config.max_volume_participation_pct,
            volume_limit_action=self.config.volume_limit_action,
            data_source_type=src_type,
            data_source_name=src_name,
            is_synthetic_data=is_syn,
        )

        result_pre = BacktestResult(
            strategy_name=strategy.dsl.name,
            underlying=strategy.dsl.underlying,
            bar_count=n_bars,
            signals=recorded_signals,
            orders=all_orders,
            trades=executed_trades,
            equity_curve=equity_curve,
            equity_timestamps=equity_timestamps,
            terminal_positions=terminal_positions,
            terminal_unrealized_pnl=terminal_unrealized_pnl,
            liquidated_ending_equity=liquidated_ending_equity,
            terminal_adjusted_expectancy=terminal_adjusted_expectancy,
            performance=performance,
            simulation_assumptions=assumptions,
            events=events,
            ledger=roundtrip_trades,
            trade_ledger_merkle_root=trade_ledger.merkle_root,
            event_stream_merkle_root=event_merkle_root,
        )

        # ----------------------------------------------------------------------
        # 9. Verification Matrix & Balance Sheet Reconciliation Audit
        # ----------------------------------------------------------------------
        recon_audit = ReconciliationChecker.audit_session(
            starting_capital=self.config.initial_capital,
            ending_equity=snap_balance.total_capital,
            net_profit=round(snap_balance.total_capital - self.config.initial_capital, 2),
            positions=terminal_positions,
            trades=executed_trades,
            unrealized_pnl=terminal_unrealized_pnl,
            realized_roundtrip_pnls=[t.gross_pnl for t in closed_trades],
        )

        # Verification Service integration
        strat_hash = hashlib.sha256(
            json.dumps(strategy.dsl.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        ).hexdigest()

        from aditrader.verification.service import VerificationService

        ver_service = VerificationService()
        matrix, bundle, _ = ver_service.evaluate_strategy(
            strategy=strategy.dsl,
            dataset_path=dataset_path_str if Path(dataset_path_str).is_file() else None,
            backtest_result=result_pre,
        )

        # ----------------------------------------------------------------------
        # 10. Structured Run Dossier Construction & Atomic Persistence
        # ----------------------------------------------------------------------
        contract_type = (
            ExecutionContractType.ACADEMIC_EXPLORATORY
            if self.config.allow_same_bar_execution
            else self.config.execution_contract
        )
        created_now = self.config.created_at or datetime.now(UTC)

        tamper_digest = RunDossier.compute_tamper_digest(
            run_id=run_id,
            strategy_hash=strat_hash,
            dataset_hash=dataset_content_hash,
            initial_capital=self.config.initial_capital,
            net_profit=performance.net_profit,
            ending_equity=performance.ending_equity,
            event_stream_root=event_merkle_root,
            trade_ledger_root=trade_ledger.merkle_root,
            matrix_status=matrix.overall_status.value,
            created_at=created_now,
        )

        dossier = RunDossier(
            run_id=run_id,
            created_at=created_now,
            engine_version="1.0.0",
            execution_contract=contract_type,
            strategy_id=getattr(strategy.dsl, "id", strategy.dsl.name.lower().replace(" ", "_")),
            strategy_name=strategy.dsl.name,
            strategy_version=getattr(strategy.dsl, "version", "1.0"),
            strategy_hash=strat_hash,
            dataset_name=src_name,
            dataset_path=dataset_path_str,
            dataset_hash=dataset_content_hash,
            timeframe=strategy.dsl.timeframe,
            symbol=strategy.dsl.underlying,
            start_time=bars[0].timestamp,
            end_time=bars[-1].timestamp,
            bar_count=n_bars,
            integrity_passed=integrity_rep.is_valid or is_syn,
            initial_capital=self.config.initial_capital,
            slippage_bps=slip_bps,
            fill_assumption=assumptions.fill_assumption,
            cost_model=assumptions.cost_model,
            timezone="Asia/Kolkata",
            intraday_squareoff=self.config.intraday_auto_squareoff,
            event_count=len(events),
            order_count=len(all_orders),
            fill_count=len(executed_trades),
            rejected_count=sum(1 for o in all_orders if o.status == OrderStatus.REJECTED),
            trade_count=len(closed_trades),
            terminal_open_positions_count=len(terminal_positions),
            starting_equity=performance.starting_equity,
            ending_equity=performance.ending_equity,
            liquidated_ending_equity=liquidated_ending_equity,
            net_profit=performance.net_profit,
            return_pct=performance.return_pct,
            win_rate=performance.win_rate,
            closed_trade_expectancy=closed_trade_expectancy,
            terminal_adjusted_expectancy=terminal_adjusted_expectancy,
            profit_factor=performance.profit_factor,
            max_drawdown_amount=performance.max_drawdown_amount,
            max_drawdown_pct=performance.max_drawdown_pct,
            sharpe_ratio=performance.sharpe_ratio,
            sortino_ratio=performance.sortino_ratio,
            sqn=performance.sqn,
            verification_matrix=matrix,
            reconciliation=recon_audit,
            evidence_bundle_id=bundle.bundle_id,
            event_stream_merkle_root=event_merkle_root,
            trade_ledger_merkle_root=trade_ledger.merkle_root,
            tamper_digest=tamper_digest,
            events=events,
            ledger=roundtrip_trades,
            provenance=bundle.assumptions.get("baseline_metrics", {}),
        )

        # Atomic persistence of Run Dossier to runs/backtest/
        self._persist_dossier(dossier)

        return BacktestResult(
            strategy_name=strategy.dsl.name,
            underlying=strategy.dsl.underlying,
            bar_count=n_bars,
            signals=recorded_signals,
            orders=all_orders,
            trades=executed_trades,
            equity_curve=equity_curve,
            equity_timestamps=equity_timestamps,
            terminal_positions=terminal_positions,
            terminal_unrealized_pnl=terminal_unrealized_pnl,
            liquidated_ending_equity=liquidated_ending_equity,
            terminal_adjusted_expectancy=terminal_adjusted_expectancy,
            performance=performance,
            simulation_assumptions=assumptions,
            dossier=dossier,
            events=events,
            ledger=roundtrip_trades,
            trade_ledger_merkle_root=trade_ledger.merkle_root,
            event_stream_merkle_root=event_merkle_root,
        )

    def _persist_dossier(self, dossier: RunDossier) -> None:
        """Atomically persist Run Dossier JSON to runs/backtest/."""
        try:
            out_dir = Path("runs/backtest")
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = out_dir / f"dossier_{dossier.run_id}.tmp"
            target_path = out_dir / f"dossier_{dossier.run_id}.json"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(dossier.model_dump(mode="json"), f, indent=2)
            tmp_path.replace(target_path)
            logger.info("Persisted Run Dossier: %s", target_path)
        except Exception as exc:
            logger.warning("Could not persist Run Dossier: %s", exc)

    def _process_signal_execution(
        self,
        signal: Signal,
        execution_price: float,
        timestamp: datetime,
        bar: Bar,
        broker: PaperBroker,
        risk_engine: RiskEngine,
        strategy: ExecutableStrategy,
        record_event_fn: Any,
    ) -> None:
        """Route signal through volume constraint, two-sided clamping, and risk engine."""
        side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        requested_qty = self.config.trade_lots

        # Volume / Liquidity Participation Constraint Gate (Finding 3.3)
        if self.config.max_volume_participation_pct is not None:
            max_allowed_qty = int(bar.volume * self.config.max_volume_participation_pct)
            if requested_qty > max_allowed_qty:
                if self.config.volume_limit_action == "REJECT" or max_allowed_qty <= 0:
                    tentative_order = broker.create_order(
                        symbol=signal.symbol,
                        side=side,
                        order_type=OrderType.MARKET,
                        qty=requested_qty,
                        signal_id=f"SIG-{signal.timestamp.isoformat()}",
                        timestamp=timestamp,
                    )
                    rejected_order = OrderStateMachine.transition(
                        tentative_order,
                        OrderStatus.REJECTED,
                        timestamp=timestamp,
                        rejection_reason=(
                            f"Volume limit exceeded: order qty ({requested_qty}) exceeds "
                            f"max participation ({max_allowed_qty} = "
                            f"{self.config.max_volume_participation_pct * 100:.1f}% of bar volume {bar.volume})"
                        ),
                    )
                    broker._orders[rejected_order.order_id] = rejected_order
                    strategy.notify_order_rejected()
                    record_event_fn(
                        ExecutionEventType.ORDER_REJECTED,
                        signal.symbol,
                        timestamp,
                        {
                            "order_id": rejected_order.order_id,
                            "reason": rejected_order.rejection_reason,
                        },
                    )
                    return
                else:
                    # PARTIAL_FILL (Finding 3.3: retain requested quantity, record truncation)
                    unfilled_qty = requested_qty - max_allowed_qty
                    record_event_fn(
                        ExecutionEventType.LIQUIDITY_BREACH,
                        signal.symbol,
                        timestamp,
                        {
                            "requested_qty": requested_qty,
                            "max_allowed_qty": max_allowed_qty,
                            "unfilled_truncated": unfilled_qty,
                            "action": "PARTIAL_FILL",
                        },
                    )
                    requested_qty = max_allowed_qty

        # Two-Sided Clamping & Liquidity Breach Checks (Finding 3.1)
        raw_fill_price, _ = broker.slippage_model.calculate_fill_price(execution_price, side)
        is_breach = False
        if (
            side == OrderSide.BUY
            and raw_fill_price > bar.high
            or side == OrderSide.SELL
            and raw_fill_price < bar.low
        ):
            is_breach = True

        if is_breach:
            record_event_fn(
                ExecutionEventType.LIQUIDITY_BREACH,
                signal.symbol,
                timestamp,
                {
                    "raw_fill_price": raw_fill_price,
                    "bar_high": bar.high,
                    "bar_low": bar.low,
                    "side": side.value,
                },
            )
            if self.config.strict_liquidity_rejection:
                tentative_order = broker.create_order(
                    symbol=signal.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    qty=requested_qty,
                    signal_id=f"SIG-{signal.timestamp.isoformat()}",
                    timestamp=timestamp,
                )
                rejected_order = OrderStateMachine.transition(
                    tentative_order,
                    OrderStatus.REJECTED,
                    timestamp=timestamp,
                    rejection_reason=(
                        f"Slippage breached candle envelope: raw fill price {raw_fill_price} "
                        f"outside [{bar.low}, {bar.high}]"
                    ),
                )
                broker._orders[rejected_order.order_id] = rejected_order
                strategy.notify_order_rejected()
                record_event_fn(
                    ExecutionEventType.ORDER_REJECTED,
                    signal.symbol,
                    timestamp,
                    {
                        "order_id": rejected_order.order_id,
                        "reason": rejected_order.rejection_reason,
                    },
                )
                return

        # Physical clamping to bar bounds
        effective_price = min(max(raw_fill_price, bar.low), bar.high)

        tentative_order = broker.create_order(
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            qty=requested_qty,
            signal_id=f"SIG-{signal.timestamp.isoformat()}",
            timestamp=timestamp,
        )

        record_event_fn(
            ExecutionEventType.ORDER_SUBMITTED,
            signal.symbol,
            timestamp,
            {
                "order_id": tentative_order.order_id,
                "side": side.value,
                "qty": requested_qty,
                "order_type": "MARKET",
            },
        )

        balance = broker.get_account_balance()
        positions_map = {p.symbol: p for p in broker.get_positions()}

        is_expiry_day = bool(signal.metadata.get("is_expiry_day", False))
        is_naked_short = bool(signal.metadata.get("is_naked_short", False))

        risk_check = risk_engine.validate_order(
            order=tentative_order,
            balance=balance,
            positions=positions_map,
            current_market_price=effective_price,
            is_expiry_day=is_expiry_day,
            is_naked_short=is_naked_short,
        )

        if not risk_check.passed:
            # Order rejected by pre-trade risk engine (Finding 5.1: notify strategy)
            prefix = f"{risk_check.reason.value}: " if risk_check.reason else ""
            rejection_reason = f"{prefix}{risk_check.detail or 'Risk gate rejection'}"
            rejected_order = OrderStateMachine.transition(
                tentative_order,
                OrderStatus.REJECTED,
                timestamp=timestamp,
                rejection_reason=rejection_reason,
            )
            broker._orders[rejected_order.order_id] = rejected_order
            strategy.notify_order_rejected()
            record_event_fn(
                ExecutionEventType.ORDER_REJECTED,
                signal.symbol,
                timestamp,
                {
                    "order_id": rejected_order.order_id,
                    "reason": rejection_reason,
                },
            )
            return

        executed_order = broker.submit_order(
            tentative_order,
            current_market_price=execution_price,
            timestamp=timestamp,
            exact_fill_price=effective_price,
            slippage=round(abs(effective_price - execution_price), 2),
        )

        if executed_order.status == OrderStatus.REJECTED:
            strategy.notify_order_rejected()
            record_event_fn(
                ExecutionEventType.ORDER_REJECTED,
                signal.symbol,
                timestamp,
                {
                    "order_id": executed_order.order_id,
                    "reason": executed_order.rejection_reason or "Order rejected by broker",
                },
            )
            return

        # Record fill event matching this specific order
        matching_trade = next(
            (t for t in reversed(broker.get_trades()) if t.order_id == executed_order.order_id),
            None,
        )
        if matching_trade:
            record_event_fn(
                ExecutionEventType.ORDER_FILLED,
                matching_trade.symbol,
                timestamp,
                {
                    "trade_id": matching_trade.trade_id,
                    "order_id": executed_order.order_id,
                    "side": matching_trade.side.value,
                    "qty": matching_trade.qty,
                    "price": matching_trade.fill_price,
                    "fees": matching_trade.stt + matching_trade.charges + matching_trade.slippage,
                },
            )
            strategy.sync_position_state(True)

    def _build_roundtrip_trades(self, trades: list[Trade], run_id: str) -> list[RoundtripTrade]:
        """Construct authoritative roundtrip trades with proportional FIFO fee attribution (Finding 4.1)."""
        # Inventory entries: (trade_id, timestamp, qty, price, total_fees, stt, charges, slippage)
        long_inv: deque[tuple[str, datetime, int, float, float, float, float, float]] = deque()
        short_inv: deque[tuple[str, datetime, int, float, float, float, float, float]] = deque()
        roundtrip_trades: list[RoundtripTrade] = []
        trade_idx = 0

        for t in trades:
            remaining_qty = t.qty
            cur_fees_allocated = 0.0
            cur_stt_allocated = 0.0
            cur_charges_allocated = 0.0
            cur_slip_allocated = 0.0

            if t.side == OrderSide.BUY:
                # Match against short inventory
                while remaining_qty > 0 and short_inv:
                    (
                        s_id,
                        s_time,
                        s_qty,
                        s_price,
                        s_fees,
                        s_stt,
                        s_charges,
                        s_slippage,
                    ) = short_inv.popleft()
                    match_qty = min(remaining_qty, s_qty)

                    # Order t fees for this match
                    if match_qty == remaining_qty:
                        t_alloc_stt = round(t.stt - cur_stt_allocated, 2)
                        t_alloc_charges = round(t.charges - cur_charges_allocated, 2)
                        t_alloc_slip = round(t.slippage - cur_slip_allocated, 2)
                        t_alloc_fees = round(t_alloc_stt + t_alloc_charges + t_alloc_slip, 2)
                    else:
                        ratio_cur = match_qty / t.qty
                        t_alloc_stt = round(ratio_cur * t.stt, 2)
                        t_alloc_charges = round(ratio_cur * t.charges, 2)
                        t_alloc_slip = round(ratio_cur * t.slippage, 2)
                        t_alloc_fees = round(t_alloc_stt + t_alloc_charges + t_alloc_slip, 2)

                    cur_stt_allocated += t_alloc_stt
                    cur_charges_allocated += t_alloc_charges
                    cur_slip_allocated += t_alloc_slip
                    cur_fees_allocated += t_alloc_fees

                    # Inventory s fees for this match
                    if match_qty == s_qty:
                        s_alloc_stt = s_stt
                        s_alloc_charges = s_charges
                        s_alloc_slip = s_slippage
                    else:
                        ratio_inv = match_qty / s_qty
                        s_alloc_stt = round(ratio_inv * s_stt, 2)
                        s_alloc_charges = round(ratio_inv * s_charges, 2)
                        s_alloc_slip = round(ratio_inv * s_slippage, 2)

                        # Residual short inventory gets remainder by subtraction
                        rem_inv_qty = s_qty - match_qty
                        rem_s_stt = round(s_stt - s_alloc_stt, 2)
                        rem_s_charges = round(s_charges - s_alloc_charges, 2)
                        rem_s_slip = round(s_slippage - s_alloc_slip, 2)
                        rem_s_fees = round(rem_s_stt + rem_s_charges + rem_s_slip, 2)
                        short_inv.appendleft(
                            (
                                s_id,
                                s_time,
                                rem_inv_qty,
                                s_price,
                                rem_s_fees,
                                rem_s_stt,
                                rem_s_charges,
                                rem_s_slip,
                            )
                        )

                    prop_stt = round(t_alloc_stt + s_alloc_stt, 2)
                    prop_charges = round(t_alloc_charges + s_alloc_charges, 2)
                    prop_slip = round(t_alloc_slip + s_alloc_slip, 2)
                    prop_fees = round(prop_stt + prop_charges + prop_slip, 2)

                    gross = round((s_price - t.fill_price) * match_qty, 2)
                    net = round(gross - prop_fees, 2)

                    trade_idx += 1
                    rt = RoundtripTrade(
                        trade_id=f"TRD-{trade_idx:06d}",
                        run_id=run_id,
                        symbol=t.symbol,
                        side=OrderSide.SELL,  # Short position closed by buy
                        quantity=match_qty,
                        entry_time=s_time,
                        entry_price=s_price,
                        exit_time=t.timestamp,
                        exit_price=t.fill_price,
                        gross_pnl=gross,
                        stt=prop_stt,
                        charges=prop_charges,
                        slippage=prop_slip,
                        total_fees=prop_fees,
                        net_pnl=net,
                        exit_reason="SIGNAL",
                        is_closed=True,
                    )
                    roundtrip_trades.append(rt)
                    remaining_qty -= match_qty

                # Residual BUY opens Long inventory: residual fees by subtraction
                if remaining_qty > 0:
                    res_stt = round(t.stt - cur_stt_allocated, 2)
                    res_charges = round(t.charges - cur_charges_allocated, 2)
                    res_slip = round(t.slippage - cur_slip_allocated, 2)
                    res_fees = round(res_stt + res_charges + res_slip, 2)
                    long_inv.append(
                        (
                            t.trade_id,
                            t.timestamp,
                            remaining_qty,
                            t.fill_price,
                            res_fees,
                            res_stt,
                            res_charges,
                            res_slip,
                        )
                    )

            else:  # SELL
                # Match against long inventory
                while remaining_qty > 0 and long_inv:
                    (
                        l_id,
                        l_time,
                        l_qty,
                        l_price,
                        l_fees,
                        l_stt,
                        l_charges,
                        l_slippage,
                    ) = long_inv.popleft()
                    match_qty = min(remaining_qty, l_qty)

                    # Order t fees for this match
                    if match_qty == remaining_qty:
                        t_alloc_stt = round(t.stt - cur_stt_allocated, 2)
                        t_alloc_charges = round(t.charges - cur_charges_allocated, 2)
                        t_alloc_slip = round(t.slippage - cur_slip_allocated, 2)
                        t_alloc_fees = round(t_alloc_stt + t_alloc_charges + t_alloc_slip, 2)
                    else:
                        ratio_cur = match_qty / t.qty
                        t_alloc_stt = round(ratio_cur * t.stt, 2)
                        t_alloc_charges = round(ratio_cur * t.charges, 2)
                        t_alloc_slip = round(ratio_cur * t.slippage, 2)
                        t_alloc_fees = round(t_alloc_stt + t_alloc_charges + t_alloc_slip, 2)

                    cur_stt_allocated += t_alloc_stt
                    cur_charges_allocated += t_alloc_charges
                    cur_slip_allocated += t_alloc_slip
                    cur_fees_allocated += t_alloc_fees

                    # Inventory l fees for this match
                    if match_qty == l_qty:
                        l_alloc_stt = l_stt
                        l_alloc_charges = l_charges
                        l_alloc_slip = l_slippage
                    else:
                        ratio_inv = match_qty / l_qty
                        l_alloc_stt = round(ratio_inv * l_stt, 2)
                        l_alloc_charges = round(ratio_inv * l_charges, 2)
                        l_alloc_slip = round(ratio_inv * l_slippage, 2)

                        # Residual long inventory gets remainder by subtraction
                        rem_inv_qty = l_qty - match_qty
                        rem_l_stt = round(l_stt - l_alloc_stt, 2)
                        rem_l_charges = round(l_charges - l_alloc_charges, 2)
                        rem_l_slip = round(l_slippage - l_alloc_slip, 2)
                        rem_l_fees = round(rem_l_stt + rem_l_charges + rem_l_slip, 2)
                        long_inv.appendleft(
                            (
                                l_id,
                                l_time,
                                rem_inv_qty,
                                l_price,
                                rem_l_fees,
                                rem_l_stt,
                                rem_l_charges,
                                rem_l_slip,
                            )
                        )

                    prop_stt = round(t_alloc_stt + l_alloc_stt, 2)
                    prop_charges = round(t_alloc_charges + l_alloc_charges, 2)
                    prop_slip = round(t_alloc_slip + l_alloc_slip, 2)
                    prop_fees = round(prop_stt + prop_charges + prop_slip, 2)

                    gross = round((t.fill_price - l_price) * match_qty, 2)
                    net = round(gross - prop_fees, 2)

                    trade_idx += 1
                    rt = RoundtripTrade(
                        trade_id=f"TRD-{trade_idx:06d}",
                        run_id=run_id,
                        symbol=t.symbol,
                        side=OrderSide.BUY,  # Long position closed by sell
                        quantity=match_qty,
                        entry_time=l_time,
                        entry_price=l_price,
                        exit_time=t.timestamp,
                        exit_price=t.fill_price,
                        gross_pnl=gross,
                        stt=prop_stt,
                        charges=prop_charges,
                        slippage=prop_slip,
                        total_fees=prop_fees,
                        net_pnl=net,
                        exit_reason="SIGNAL",
                        is_closed=True,
                    )
                    roundtrip_trades.append(rt)
                    remaining_qty -= match_qty

                # Residual SELL opens Short inventory: residual fees by subtraction
                if remaining_qty > 0:
                    res_stt = round(t.stt - cur_stt_allocated, 2)
                    res_charges = round(t.charges - cur_charges_allocated, 2)
                    res_slip = round(t.slippage - cur_slip_allocated, 2)
                    res_fees = round(res_stt + res_charges + res_slip, 2)
                    short_inv.append(
                        (
                            t.trade_id,
                            t.timestamp,
                            remaining_qty,
                            t.fill_price,
                            res_fees,
                            res_stt,
                            res_charges,
                            res_slip,
                        )
                    )

        # Record any unclosed terminal positions (Finding 4.3)
        for (
            _l_id,
            l_time,
            l_qty,
            l_price,
            l_fees,
            l_stt,
            l_charges,
            l_slippage,
        ) in long_inv:
            trade_idx += 1
            roundtrip_trades.append(
                RoundtripTrade(
                    trade_id=f"TRD-{trade_idx:06d}",
                    run_id=run_id,
                    symbol=trades[0].symbol if trades else "UNKNOWN",
                    side=OrderSide.BUY,
                    quantity=l_qty,
                    entry_time=l_time,
                    entry_price=l_price,
                    exit_time=None,
                    exit_price=None,
                    gross_pnl=0.0,
                    stt=l_stt,
                    charges=l_charges,
                    slippage=l_slippage,
                    total_fees=l_fees,
                    net_pnl=0.0,
                    exit_reason="TERMINAL_OPEN",
                    is_closed=False,
                )
            )

        for (
            _s_id,
            s_time,
            s_qty,
            s_price,
            s_fees,
            s_stt,
            s_charges,
            s_slippage,
        ) in short_inv:
            trade_idx += 1
            roundtrip_trades.append(
                RoundtripTrade(
                    trade_id=f"TRD-{trade_idx:06d}",
                    run_id=run_id,
                    symbol=trades[0].symbol if trades else "UNKNOWN",
                    side=OrderSide.SELL,
                    quantity=s_qty,
                    entry_time=s_time,
                    entry_price=s_price,
                    exit_time=None,
                    exit_price=None,
                    gross_pnl=0.0,
                    stt=s_stt,
                    charges=s_charges,
                    slippage=s_slippage,
                    total_fees=s_fees,
                    net_pnl=0.0,
                    exit_reason="TERMINAL_OPEN",
                    is_closed=False,
                )
            )

        return roundtrip_trades

    def _calculate_roundtrip_pnls(self, trades: list[Trade]) -> list[float]:
        """Backward-compatible helper returning net PnLs for roundtrip closed positions."""
        rt_trades = self._build_roundtrip_trades(trades, run_id="legacy")
        return [t.net_pnl for t in rt_trades if t.is_closed]
