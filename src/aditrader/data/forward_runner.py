"""Institutional air-gapped forward-testing and paper-trading orchestrator."""

import contextlib
import logging
import random
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.config.settings import get_settings
from aditrader.core.broker import PaperBroker
from aditrader.core.costs import SlippageModel, resolve_instrument_class
from aditrader.core.ledger.repository import LedgerRepository
from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType, SignalDirection
from aditrader.core.models.execution import AccountBalance, Position, Trade
from aditrader.core.models.market_data import Bar, Tick
from aditrader.core.models.order import Order
from aditrader.core.models.trade_signal import Signal
from aditrader.core.risk import RiskEngine, RiskLimits
from aditrader.core.state_machine import OrderStateMachine
from aditrader.data.adapters.base import AbstractBrokerAdapter
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.feeds.aggregator import TickAggregator
from aditrader.data.feeds.base import DataFeed
from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.forward import (
    ForwardTestAssumptions,
    ForwardTestObservation,
    ForwardTestRecorder,
    ForwardTestSession,
    ForwardTestStatus,
)
from aditrader.data.instruments.specs import resolve_contract_specs
from aditrader.data.quality import (
    DataQualityError,
    DataQualityReport,
    MarketDataQualityValidator,
)
from aditrader.data.session import EXCHANGE_TIMEZONE, is_market_open
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
)
from aditrader.strategy.compiler.engine import ExecutableStrategy
from aditrader.strategy.library.models import StrategyRecord
from aditrader.strategy.library.registry import StrategyRegistry

logger = logging.getLogger(__name__)


class UnsupportedStrategyError(ValueError):
    """Raised when a strategy definition cannot be deterministically simulated by the runner."""


class ForwardTestConfig(BaseModel):
    """Configuration governing an air-gapped forward paper-testing session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(..., min_length=1, description="Target trading instrument symbol")
    timeframe: str = Field(default="1m", description="Bar aggregation timeframe (e.g. '1m', '5m')")
    qty: int | None = Field(
        default=None,
        gt=0,
        description="Order execution quantity override (defaults to lot size for derivatives, 1 for equity)",
    )
    volume_mode: Literal["TICK_COUNT", "TRADED_VOLUME", "CUMULATIVE", "INCREMENTAL"] = Field(
        default="TRADED_VOLUME",
        description="Volume aggregation mode for TickAggregator (default: TRADED_VOLUME)",
    )
    initial_capital: float = Field(
        default=1_000_000.0, gt=0.0, description="Starting simulated capital in INR"
    )
    max_margin_utilization: float = Field(
        default=0.85, ge=0.1, le=1.0, description="Peak margin utilization floor"
    )
    slippage_bps: float = Field(
        default=2.5, ge=0.0, description="Model slippage penalty in basis points"
    )
    enforce_session_hours: bool = Field(
        default=False, description="Whether to reject/flag ticks outside NSE hours"
    )
    strict_quality_checks: bool = Field(
        default=False, description="Abort session immediately if market data quality fails"
    )
    max_ticks: int | None = Field(
        default=None, gt=0, description="Optional stop limit after processing N ticks"
    )
    max_bars: int | None = Field(
        default=None, gt=0, description="Optional stop limit after closing N bars"
    )
    duration_seconds: float | None = Field(
        default=None, gt=0.0, description="Optional session timeout in seconds"
    )
    output_path: Path | None = Field(
        default=None, description="Custom JSON path to persist session dossier"
    )
    enable_ledger_persistence: bool = Field(
        default=True, description="Persist orders and trades to local SQLite ledger"
    )
    database_url: str | None = Field(
        default=None, description="Custom SQLite database URL override"
    )
    risk_limits: RiskLimits = Field(
        default_factory=RiskLimits, description="Pre-trade risk constraints"
    )
    force_mock: bool = Field(
        default=False, description="Force mock data adapter even if broker credentials exist"
    )
    feed_readiness_timeout: float = Field(
        default=15.0,
        gt=0.0,
        description="Maximum seconds to wait for live feed readiness before failing closed",
    )


class ForwardTestResult(BaseModel):
    """Complete results and audit artifact from a forward-testing session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session: ForwardTestSession
    orders: list[Order]
    trades: list[Trade]
    positions: list[Position]
    ending_balance: AccountBalance
    dossier_path: Path | None
    quality_report: DataQualityReport | None


def _parse_timeframe_seconds(timeframe: str) -> int:
    """Parse timeframe string into seconds for TickAggregator."""
    tf = timeframe.lower().strip()
    try:
        if tf.endswith("s"):
            return max(1, int(tf[:-1]))
        if tf.endswith("m"):
            return max(1, int(tf[:-1]) * 60)
        if tf.endswith("h"):
            return max(1, int(tf[:-1]) * 3600)
        if tf.endswith("d"):
            return max(1, int(tf[:-1]) * 86400)
    except ValueError:
        return 60
    return 60


def _get_sample_ma_crossover(underlying: str = "NIFTY") -> StrategyDSL:
    """Deterministic linear MA crossover strategy for local testing and demonstration."""
    return StrategyDSL(
        schema_version="1.0",
        name="test_ma_crossover",
        underlying=underlying,
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=24000.0,
                )
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.LESS_THAN,
                    threshold=23950.0,
                )
            ],
        ),
    )


def resolve_strategy(
    strategy: StrategyDSL | ExecutableStrategy | str,
    registry: StrategyRegistry | None = None,
    symbol: str | None = None,
) -> tuple[ExecutableStrategy, StrategyDSL]:
    """Resolve strategy parameter into compiled ExecutableStrategy and source StrategyDSL."""
    if isinstance(strategy, ExecutableStrategy):
        return strategy, strategy.dsl

    if isinstance(strategy, StrategyDSL):
        return ExecutableStrategy(strategy), strategy

    if isinstance(strategy, str):
        strat_str = strategy.strip()
        reg = registry or StrategyRegistry()

        # 1. Check registry by ID or exact name
        try:
            record: StrategyRecord = reg.get(strat_str)
            return ExecutableStrategy(record.dsl_definition), record.dsl_definition
        except Exception:
            pass

        try:
            record = reg.get_by_name(strat_str)
            return ExecutableStrategy(record.dsl_definition), record.dsl_definition
        except Exception:
            pass

        # 2. Case-insensitive / normalized search
        q = strat_str.lower().replace("-", " ").replace("_", " ").strip()
        for rec in reg.list_all():
            name_clean = rec.name.lower().replace("-", " ").replace("_", " ").strip()
            id_clean = rec.id.lower().replace("-", " ").replace("_", " ").strip()
            if q in (name_clean, id_clean) or q in name_clean:
                return ExecutableStrategy(rec.dsl_definition), rec.dsl_definition

        # 3. Built-in linear sample fallback
        if q in ("test ma crossover", "ma crossover", "test_ma_crossover"):
            dsl = _get_sample_ma_crossover(underlying=symbol or "NIFTY")
            return ExecutableStrategy(dsl), dsl

        raise ValueError(
            f"Strategy '{strategy}' could not be resolved from registry or built-in templates."
        )

    raise TypeError(f"Unsupported strategy type: {type(strategy)}")


class ForwardTestRunner:
    """
    Unified application-level forward paper-testing session orchestrator.

    Architecture:
    Market Data Feed (Kotak Neo / Synthetic / CSV)
      ↓
    Canonical Tick (normalized to Asia/Kolkata)
      ↓
    Data Quality Validator (MarketDataQualityValidator)
      ↓
    TickAggregator (Bar aggregation)
      ↓
    Compiled Strategy (ExecutableStrategy)
      ↓
    Pre-Trade Risk Checks (RiskEngine)
      ↓
    Paper Broker Execution (PaperBroker, strictly air-gapped)
      ↓
    Audit Recorder (ForwardTestRecorder)
      ↓
    Persistent Session Dossier (.json) & Local SQLite Ledger
    """

    def __init__(
        self,
        config: ForwardTestConfig,
        strategy: StrategyDSL | ExecutableStrategy | str,
        adapter: AbstractBrokerAdapter | None = None,
        feed: DataFeed | None = None,
        ledger_repo: LedgerRepository | None = None,
        on_tick_callback: Callable[[Tick], None] | None = None,
        on_bar_callback: Callable[[Bar], None] | None = None,
        on_signal_callback: Callable[[Signal], None] | None = None,
        on_order_callback: Callable[[Order], None] | None = None,
        on_trade_callback: Callable[[Trade], None] | None = None,
    ) -> None:
        if not config.symbol or not config.symbol.strip():
            raise ValueError("ForwardTestConfig requires a valid, non-empty symbol")

        self.config = config
        self.executable_strategy, self.strategy_dsl = resolve_strategy(
            strategy, symbol=config.symbol
        )

        # Guard 1: Options air-gap barrier (matches BacktestRunner ADR 011)
        if self.strategy_dsl.legs:
            raise UnsupportedStrategyError(
                f"Strategy '{self.strategy_dsl.name}' defines {len(self.strategy_dsl.legs)} option leg(s). "
                "ForwardTestRunner only simulates underlying spot/futures candle execution. "
                "Simulating multi-leg option strategies requires option-chain tick data and synthetic "
                "IV surface modeling. Silent proxy execution of option legs "
                "against underlying spot prices is strictly prohibited."
            )

        # Guard 2: Static AST structural validation
        from aditrader.validation.ast.validator import ASTValidator
        from aditrader.validation.models import ValidationStatus

        val_res = ASTValidator.validate(self.strategy_dsl)
        if val_res.status == ValidationStatus.REJECTED:
            failed_gates = "; ".join(val_res.failed_gates)
            raise ValueError(
                f"Strategy '{self.strategy_dsl.name}' failed static AST validation: {failed_gates}"
            )

        # Resolve instrument class for statutory charges and fee schedule
        self.instrument_class = resolve_instrument_class(config.symbol)

        # Execution venue: strictly paper broker (air-gapped)
        self.broker = PaperBroker(
            initial_capital=config.initial_capital,
            max_margin_utilization=config.max_margin_utilization,
            slippage_model=SlippageModel(percentage=config.slippage_bps / 10000.0),
            default_instrument=self.instrument_class,
        )

        # Trade lot quantity resolution
        if config.qty is not None:
            self.trade_qty = config.qty
        elif self.instrument_class in ("FUTURES", "OPTIONS"):
            _, lot = resolve_contract_specs(config.symbol)
            self.trade_qty = lot
        else:
            self.trade_qty = 1

        # Pre-trade risk engine
        self.risk_engine = RiskEngine(
            limits=config.risk_limits,
            initial_capital=config.initial_capital,
        )

        # Audit recorder
        assumptions = ForwardTestAssumptions(
            broker_mode="AIR_GAPPED_PAPER",
            quote_fill_enabled=True,
            enforce_session_hours=config.enforce_session_hours,
        )
        self.recorder = ForwardTestRecorder(
            symbol=config.symbol,
            strategy_id=self.strategy_dsl.name,
            strategy_version=getattr(self.strategy_dsl, "schema_version", "1.0"),
            assumptions=assumptions,
        )

        # Bar aggregator
        interval_secs = _parse_timeframe_seconds(config.timeframe)
        self.aggregator = TickAggregator(
            symbol=config.symbol,
            interval_seconds=interval_secs,
            on_bar_close=self._on_bar_close,
            volume_mode=config.volume_mode,
        )

        # Local ledger repository
        self.ledger_repo: LedgerRepository | None = None
        if config.enable_ledger_persistence:
            settings = get_settings()
            db_url = config.database_url or settings.database_url
            try:
                self.ledger_repo = ledger_repo or LedgerRepository(database_url=db_url)
                self.ledger_repo.create_tables()
            except Exception as exc:
                logger.warning(
                    "Failed to initialize local SQLite ledger repository at '%s': %s. Continuing without transactional database persistence.",
                    db_url,
                    exc,
                )
                self.ledger_repo = None

        # Data feed & adapter resolution
        self.feed = feed
        self.adapter = adapter
        if self.adapter is None and self.feed is None:
            self.adapter = self._resolve_default_adapter()

        # Callbacks
        self.on_tick_callback = on_tick_callback
        self.on_bar_callback = on_bar_callback
        self.on_signal_callback = on_signal_callback
        self.on_order_callback = on_order_callback
        self.on_trade_callback = on_trade_callback

        # State tracking
        self._lock = threading.RLock()
        self._status = ForwardTestStatus.STARTING
        self._is_running = False
        self._history: list[Bar] = []
        self._latest_tick: Tick | None = None
        self._current_session_date: Any = None
        self._ticks_processed = 0
        self._start_wall_time: float | None = None
        self._prev_sigint_handler: Any = None
        self._mock_feeder_thread: threading.Thread | None = None
        self._dossier_path: Path | None = None

    @property
    def session_id(self) -> str:
        return self.recorder.session_id

    @property
    def status(self) -> ForwardTestStatus:
        with self._lock:
            return self._status

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def _resolve_default_adapter(self) -> AbstractBrokerAdapter:
        """Resolve and authenticate default KotakNeoAdapter based on environment settings.

        Fails closed truthfully if live credentials are configured but the live
        networking client is unsupported or missing.
        """
        settings = get_settings()
        has_credentials = bool(
            settings.kotak_consumer_key
            and settings.kotak_mobile_number
            and (settings.kotak_ucc or settings.kotak_password)
        )

        if has_credentials and not self.config.force_mock:
            adapter = KotakNeoAdapter(
                mock_mode=False,
                readiness_timeout=self.config.feed_readiness_timeout,
            )
            adapter.authenticate()
            return adapter

        adapter = KotakNeoAdapter(mock_mode=True)
        adapter.authenticate()
        return adapter

    def _run_mock_feeder(self) -> None:
        """Background thread feeding simulated ticks when using mock adapter."""
        sym = self.config.symbol.upper()
        if "BANK" in sym:
            start_price = 51000.0
        elif "NIFTY" in sym:
            start_price = 24005.0
        elif "SENSEX" in sym:
            start_price = 80000.0
        else:
            start_price = 1000.0

        tf_secs = _parse_timeframe_seconds(self.config.timeframe)
        now_ist = datetime.now(tz=EXCHANGE_TIMEZONE)
        if self.config.enforce_session_hours and not is_market_open(now_ist):
            base_date = now_ist.date()
            while base_date.weekday() >= 5:
                base_date += timedelta(days=1)
            curr_time = datetime(
                base_date.year, base_date.month, base_date.day, 9, 16, tzinfo=EXCHANGE_TIMEZONE
            )
        else:
            curr_time = now_ist

        curr_price = start_price
        tick_step_seconds = max(0.1, tf_secs / 10.0)

        while self.is_running:
            noise = random.uniform(-1.0, 1.0)
            curr_price = max(1.0, round(curr_price + noise, 2))
            spread = max(0.05, round(curr_price * 0.0002, 2))
            bid = round(curr_price - spread / 2.0, 2)
            ask = round(curr_price + spread / 2.0, 2)

            tick = Tick(
                symbol=self.config.symbol,
                ltp=curr_price,
                bid=bid,
                ask=ask,
                bid_qty=100,
                ask_qty=100,
                volume=random.randint(10, 500),
                oi=150000,
                timestamp=curr_time,
                source="MOCK_ADAPTER",
                is_synthetic=True,
            )

            if self.adapter is not None and hasattr(self.adapter, "emit_mock_tick"):
                self.adapter.emit_mock_tick(tick)
            else:
                self.process_tick(tick)

            curr_time += timedelta(seconds=tick_step_seconds)
            time.sleep(0.01)

    def start(self) -> None:
        """Initialize subscriptions, register signal handlers, and transition to RUNNING."""
        with self._lock:
            if self._is_running:
                return

            self._status = ForwardTestStatus.STARTING
            self.recorder.set_status(ForwardTestStatus.STARTING)
            self.executable_strategy.reset()
            self._start_wall_time = time.time()

            # Register graceful SIGINT handler
            try:
                self._prev_sigint_handler = signal.signal(signal.SIGINT, self._handle_sigint)
            except (ValueError, AttributeError):
                # May occur in non-main threads
                self._prev_sigint_handler = None

            # Subscribe to ticks on adapter if present
            if self.adapter is not None:
                if getattr(self.adapter, "feed_status", None) == "UNSUPPORTED":
                    raise NotImplementedError(
                        "Cannot start forward-testing session: broker feed is UNSUPPORTED in this environment. "
                        "Run with --mock or force_mock=True for simulated paper trading rehearsal."
                    )
                if not self.adapter.is_connected():
                    self.adapter.authenticate()
                self.adapter.subscribe_ticks([self.config.symbol], self.on_tick)
                if not getattr(self.adapter, "mock_mode", False) and hasattr(
                    self.adapter, "wait_until_ready"
                ):
                    try:
                        self.adapter.wait_until_ready(timeout=self.config.feed_readiness_timeout)
                    except Exception as readiness_exc:
                        self._status = ForwardTestStatus.FAILED
                        self.recorder.set_status(
                            ForwardTestStatus.FAILED, reason=str(readiness_exc)
                        )
                        self.recorder.record_error(str(readiness_exc), fatal=True)
                        raise

            # Subscribe on feed if present
            if self.feed is not None:
                self.feed.subscribe([self.config.symbol])

            self._is_running = True
            self._status = ForwardTestStatus.RUNNING
            self.recorder.set_status(ForwardTestStatus.RUNNING)

    def _handle_sigint(self, signum: int, frame: Any) -> None:
        """Handle SIGINT signal for graceful paper trading session conclusion."""
        sys.stderr.write(
            "\n[INTERRUPT] Received SIGINT (Ctrl+C). Concluding forward-testing session cleanly...\n"
        )
        self.stop(reason="SIGINT received (User interrupted session)")

    def process_tick(self, tick: Tick) -> ForwardTestObservation | None:
        """
        Process an incoming canonical market tick synchronously.

        Validates data quality, updates PaperBroker MTM, matches pending orders,
        aggregates into bars, and evaluates stop constraints.
        """
        with self._lock:
            if not self._is_running and self._status != ForwardTestStatus.STARTING:
                return None

            self._latest_tick = tick
            self._ticks_processed += 1

            # 1. Market Data Quality Validation
            try:
                quality_errors = MarketDataQualityValidator.validate_tick(
                    tick,
                    strict=self.config.strict_quality_checks,
                    session_check=self.config.enforce_session_hours,
                )
                if quality_errors and self.config.strict_quality_checks:
                    err_msg = f"Strict data quality failure on tick: {'; '.join(quality_errors)}"
                    self.recorder.record_error(err_msg, fatal=True)
                    self.stop(reason=err_msg)
                    raise DataQualityError(err_msg)
            except DataQualityError as dq_exc:
                err_msg = f"Strict data quality failure on tick: {dq_exc}"
                self.recorder.record_error(err_msg, fatal=True)
                self.stop(reason=err_msg)
                raise DataQualityError(err_msg) from dq_exc

            # 2. Record tick observation in audit recorder
            obs = self.recorder.record_tick(tick)

            # 3. Update Paper Broker MTM & Match Pending Limit Orders with genuine quotes
            executed_trades = self.broker.on_market_tick(tick)
            for trade in executed_trades:
                self.recorder.record_trade(trade)
                if self.ledger_repo:
                    self.ledger_repo.save_trade(trade, run_id=self.session_id)
                if self.on_trade_callback:
                    self.on_trade_callback(trade)

            # 4. Push to Bar Aggregator (invokes _on_bar_close callback when interval rolls over)
            self.aggregator.process_tick(tick)

            # 5. External listener callback
            if self.on_tick_callback:
                self.on_tick_callback(tick)

            # 6. Stop limits check
            if self.config.max_ticks is not None and self._ticks_processed >= self.config.max_ticks:
                self.stop(reason=f"Reached maximum tick count threshold ({self.config.max_ticks})")

            if self.config.duration_seconds is not None and self._start_wall_time is not None:
                elapsed = time.time() - self._start_wall_time
                if elapsed >= self.config.duration_seconds:
                    self.stop(
                        reason=f"Reached duration threshold ({self.config.duration_seconds:.1f}s)"
                    )

            return obs

    def on_tick(self, tick: Tick) -> None:
        """Adapter callback target forwarding ticks into the runner pipeline."""
        try:
            self.process_tick(tick)
        except Exception as exc:
            self.recorder.record_error(f"Error processing tick: {exc}")

    def _on_bar_close(self, bar: Bar) -> None:
        """Callback invoked by TickAggregator when a bar completes."""
        self._process_closed_bar(bar)

    def _process_closed_bar(self, bar: Bar) -> None:
        """Process a completed Bar: evaluate strategy rules, risk engine, and simulate order fills."""
        # 1. Anti-lookahead barrier: strictly append closed bar to history
        self._history.append(bar)
        self.recorder.record_bar(bar)

        # 2. Intraday Session Transition Check & Risk Engine Reset
        bar_date = bar.timestamp.date()
        if self._current_session_date is None or bar_date != self._current_session_date:
            self._current_session_date = bar_date
            bal = self.broker.get_account_balance()
            self.risk_engine.on_session_start(bar.timestamp, bal.total_capital)

        # 3. Strategy Evaluation (Uses identical on_bar(history) interface as Backtester)
        signal_obj = self.executable_strategy.on_bar(list(self._history))

        if signal_obj is not None and signal_obj.direction != SignalDirection.HOLD:
            if self.on_signal_callback:
                self.on_signal_callback(signal_obj)

            # 4. Pre-Trade Risk Verification
            # Determine order side and quantity
            side = OrderSide.BUY if signal_obj.direction == SignalDirection.BUY else OrderSide.SELL
            qty = self.trade_qty

            # Execution causality: event time and price are from the latest tick that closed the bar
            exec_ts = (
                self._latest_tick.timestamp if self._latest_tick is not None else bar.timestamp
            )
            exec_price = self._latest_tick.ltp if self._latest_tick is not None else bar.close

            tentative_order = self.broker.create_order(
                symbol=self.config.symbol,
                side=side,
                order_type=OrderType.MARKET,
                qty=qty,
                price=exec_price,
                signal_id=f"SIG-{exec_ts.isoformat()}",
                timestamp=exec_ts,
            )

            bal = self.broker.get_account_balance()
            positions_map = {p.symbol: p for p in self.broker.get_positions()}
            risk_check = self.risk_engine.validate_order(
                order=tentative_order,
                balance=bal,
                positions=positions_map,
                current_market_price=exec_price,
            )

            if not risk_check.passed:
                # Rejected by pre-trade risk engine
                rejection = f"{risk_check.reason.value if risk_check.reason else 'RISK_GATE'}: {risk_check.detail}"
                rejected_order = OrderStateMachine.transition(
                    tentative_order,
                    OrderStatus.REJECTED,
                    timestamp=exec_ts,
                    rejection_reason=rejection,
                )
                self.broker._orders[rejected_order.order_id] = rejected_order
                self.recorder.record_order(rejected_order)
                if self.on_order_callback:
                    self.on_order_callback(rejected_order)
            else:
                # 5. Paper Broker Execution (Quote-aware fill)
                bid_quote = self._latest_tick.bid if self._latest_tick else None
                ask_quote = self._latest_tick.ask if self._latest_tick else None

                executed_order = self.broker.submit_order(
                    tentative_order,
                    current_market_price=exec_price,
                    timestamp=exec_ts,
                    bid=bid_quote,
                    ask=ask_quote,
                )
                self.recorder.record_order(executed_order)
                if self.on_order_callback:
                    self.on_order_callback(executed_order)

                if self.ledger_repo:
                    self.ledger_repo.save_order(executed_order, run_id=self.session_id)

                if executed_order.status == OrderStatus.FILLED:
                    trade = self.broker.get_trades()[-1]
                    self.recorder.record_trade(trade)
                    if self.ledger_repo:
                        self.ledger_repo.save_trade(trade, run_id=self.session_id)
                    if self.on_trade_callback:
                        self.on_trade_callback(trade)

        # 6. Snapshot Portfolio Balance & Positions
        balance = self.broker.get_account_balance()
        self.risk_engine.update_equity(balance.total_capital)
        snap_ts = self._latest_tick.timestamp if self._latest_tick is not None else bar.timestamp
        self.recorder.record_equity_snapshot(balance, snap_ts)
        self.recorder.record_positions(self.broker.get_positions())

        if self.ledger_repo:
            self.ledger_repo.save_balance(balance, run_id=self.session_id)

        # 7. Bar listener callback
        if self.on_bar_callback:
            self.on_bar_callback(bar)

        # 8. Max bars stop check
        if self.config.max_bars is not None and len(self._history) >= self.config.max_bars:
            self.stop(reason=f"Reached maximum closed bar count threshold ({self.config.max_bars})")

    def stop(self, reason: str = "Normal completion") -> ForwardTestResult:
        """Conclude active session, flush buffers, persist dossiers, and clean up resources."""
        with self._lock:
            if not self._is_running and self._status in (
                ForwardTestStatus.COMPLETED,
                ForwardTestStatus.FAILED,
            ):
                return self._build_result(dossier_path=self._dossier_path)

            was_failed = (
                self._status == ForwardTestStatus.FAILED
                or self.recorder.status == ForwardTestStatus.FAILED
            )
            self._is_running = False
            if not was_failed:
                self._status = ForwardTestStatus.STOPPING
                self.recorder.set_status(ForwardTestStatus.STOPPING, reason=reason)

            # Restore original SIGINT handler
            if self._prev_sigint_handler is not None:
                with contextlib.suppress(ValueError, AttributeError):
                    signal.signal(signal.SIGINT, self._prev_sigint_handler)
                self._prev_sigint_handler = None

            # Unsubscribe adapter and disconnect background streams
            if self.adapter is not None:
                with contextlib.suppress(Exception):
                    self.adapter.unsubscribe_ticks([self.config.symbol])
                if hasattr(self.adapter, "disconnect"):
                    with contextlib.suppress(Exception):
                        self.adapter.disconnect()

            # Flush any unclosed aggregator ticks into a final bar WITHOUT emitting on_bar_close callback
            final_bar = self.aggregator.flush(emit_callback=False)
            if final_bar is not None:
                self.recorder.record_bar(final_bar)

            # Snapshot final balance and positions
            self.recorder.record_positions(self.broker.get_positions())
            self.recorder.conclude_session()

            final_status = ForwardTestStatus.FAILED if was_failed else ForwardTestStatus.COMPLETED
            self._status = final_status
            self.recorder.set_status(final_status, reason=reason)

            # Resolve output path and persist JSON dossier
            output_file: Path | None = None
            if self.config.output_path:
                output_file = self.recorder.save_to_json(self.config.output_path)
            else:
                default_path = Path("runs/forward") / f"session_{self.session_id.lower()}.json"
                output_file = self.recorder.save_to_json(default_path)

            self._dossier_path = output_file

        if (
            self._mock_feeder_thread is not None
            and self._mock_feeder_thread.is_alive()
            and threading.current_thread() != self._mock_feeder_thread
        ):
            self._mock_feeder_thread.join(timeout=2.0)

        return self._build_result(dossier_path=self._dossier_path)

    def _build_result(self, dossier_path: Path | None) -> ForwardTestResult:
        """Construct the complete ForwardTestResult."""
        session_summary = self.recorder.get_session_summary()
        balance = self.broker.get_account_balance()

        # Audit quality of collected bars
        quality_report: DataQualityReport | None = None
        if self._history:
            quality_report = MarketDataQualityValidator.validate_bar_sequence(
                self._history,
                strict=False,
                session_check=self.config.enforce_session_hours,
            )

        return ForwardTestResult(
            session=session_summary,
            orders=self.broker.get_orders(),
            trades=self.broker.get_trades(),
            positions=self.broker.get_positions(),
            ending_balance=balance,
            dossier_path=dossier_path,
            quality_report=quality_report,
        )

    def run(self) -> ForwardTestResult:
        """
        Execute forward-testing session loop.

        If a synchronous DataFeed is attached, iterates until exhaustion.
        If an asynchronous adapter is attached, waits until stopped or limits reached.
        """
        self.start()

        # 1. Synchronous DataFeed execution path
        if self.feed is not None:
            feed_obj: DataFeed = self.feed
            try:
                if hasattr(feed_obj, "stream_ticks"):
                    tick_iter: Iterator[Tick] = feed_obj.stream_ticks()
                elif isinstance(feed_obj, SyntheticDataFeed):
                    syn_feed = feed_obj

                    def _gen() -> Iterator[Tick]:
                        for b in syn_feed.stream():
                            yield from syn_feed.generate_ticks_for_bar(b)

                    tick_iter = _gen()
                else:

                    def _gen_bars() -> Iterator[Tick]:
                        for b in feed_obj.stream():
                            yield Tick(
                                symbol=str(b.symbol),
                                ltp=b.close,
                                bid=None,
                                ask=None,
                                volume=b.volume,
                                oi=b.oi,
                                timestamp=b.timestamp,
                                source=b.source or "REPLAY",
                                is_synthetic=b.is_synthetic,
                            )

                    tick_iter = _gen_bars()

                for tick in tick_iter:
                    if not self.is_running:
                        break
                    self.process_tick(tick)
            except Exception as exc:
                self.recorder.record_error(f"Feed error during streaming: {exc}", fatal=True)
                return self.stop(reason=f"DataFeed streaming error: {exc}")

            return self.stop(reason="DataFeed tick stream completed")

        # 2. Asynchronous Adapter wait loop
        if self.adapter is not None and getattr(self.adapter, "mock_mode", False):
            self._mock_feeder_thread = threading.Thread(
                target=self._run_mock_feeder,
                daemon=True,
                name="MockTickFeeder",
            )
            self._mock_feeder_thread.start()

        while self.is_running:
            if self.config.duration_seconds is not None and self._start_wall_time is not None:
                elapsed = time.time() - self._start_wall_time
                if elapsed >= self.config.duration_seconds:
                    self.stop(
                        reason=f"Reached duration threshold ({self.config.duration_seconds:.1f}s)"
                    )
                    break
            time.sleep(0.02)

        return self.stop(reason="Session finished")
