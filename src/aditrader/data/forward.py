"""Forward-testing observation stream, operational assumption recording, and latency auditing."""

import json
import threading
from collections import deque
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.execution import AccountBalance, Position, Trade
from aditrader.core.models.market_data import Bar, Tick
from aditrader.core.models.order import Order
from aditrader.data.session import EXCHANGE_TIMEZONE, is_market_open, normalize_to_ist


class ForwardTestStatus(StrEnum):
    """Lifecycle states of a forward-testing session."""

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ForwardTestObservation(BaseModel):
    """Point-in-time observation captured during forward testing or paper trading."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(default_factory=lambda: f"OBS-{uuid4().hex[:8].upper()}")
    timestamp: datetime = Field(..., description="Exchange tick timestamp in Asia/Kolkata")
    received_at: datetime = Field(
        ..., description="Local arrival timestamp when observation was ingested"
    )
    symbol: str = Field(..., min_length=1, description="Instrument trading symbol")
    ltp: float = Field(..., ge=0.0, description="Last traded price")
    bid: float | None = Field(default=None, ge=0.0, description="Best available bid price")
    ask: float | None = Field(default=None, ge=0.0, description="Best available ask price")
    volume: int = Field(default=0, ge=0, description="Session cumulative or traded volume")
    oi: int | None = Field(default=None, ge=0, description="Open interest if available")
    latency_ms: float | None = Field(
        default=None,
        description="Local arrival latency relative to exchange timestamp in milliseconds",
    )
    quality_flags: list[str] = Field(
        default_factory=list,
        description="Diagnostic flags (e.g. 'OFF_SESSION', 'MISSING_BID_ASK', 'HIGH_LATENCY')",
    )
    fill_evaluated_on_quotes: bool = Field(
        default=False,
        description="True if genuine bid/ask quotes were available for execution simulation",
    )
    is_synthetic: bool = Field(
        default=False, description="True if observation contains simulated data"
    )


class ForwardTestAssumptions(BaseModel):
    """Operational parameters and execution assumptions governing a forward-testing session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_mode: str = Field(
        default="AIR_GAPPED_PAPER",
        description="Execution mode (strictly air-gapped paper broker)",
    )
    quote_fill_enabled: bool = Field(
        default=True, description="Whether order fills use genuine bid/ask quotes when present"
    )
    enforce_session_hours: bool = Field(
        default=True, description="Whether ticks outside regular market hours are flagged"
    )
    max_tolerated_latency_ms: float = Field(
        default=5000.0,
        ge=0.0,
        description="Threshold above which tick latency is flagged as HIGH_LATENCY",
    )


class ForwardTestSession(BaseModel):
    """Audit summary of an active or concluded forward-testing session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(..., description="Unique forward testing session ID")
    symbol: str = Field(..., description="Target instrument symbol")
    started_at: datetime = Field(..., description="Session start timestamp")
    ended_at: datetime | None = Field(default=None, description="Session conclusion timestamp")
    status: ForwardTestStatus = Field(
        default=ForwardTestStatus.COMPLETED, description="Session lifecycle outcome status"
    )
    strategy_id: str | None = Field(default=None, description="Active strategy ID or name")
    strategy_version: str | None = Field(default=None, description="Active strategy version")
    total_ticks: int = Field(default=0, ge=0, description="Total tick observations recorded")
    valid_ticks: int = Field(default=0, ge=0, description="Total compliant observations")
    ticks_with_quotes: int = Field(
        default=0, ge=0, description="Observations with valid bid/ask quotes"
    )
    anomaly_count: int = Field(default=0, ge=0, description="Count of flagged observations")
    avg_latency_ms: float | None = Field(
        default=None, description="Mean tick arrival latency in milliseconds"
    )
    max_latency_ms: float | None = Field(
        default=None, description="Peak tick arrival latency in milliseconds"
    )
    bars_count: int = Field(default=0, ge=0, description="Total completed bars processed")
    orders_count: int = Field(default=0, ge=0, description="Total paper orders created")
    trades_count: int = Field(default=0, ge=0, description="Total executed paper trades")
    realized_pnl: float = Field(default=0.0, description="Realized net P&L from closed positions")
    unrealized_pnl: float = Field(default=0.0, description="Unrealized mark-to-market P&L")
    ending_capital: float | None = Field(
        default=None, description="Final paper capital including market value"
    )
    error_message: str | None = Field(
        default=None, description="Fatal failure message if session aborted"
    )
    stop_reason: str | None = Field(
        default=None, description="Trigger or reason for session termination"
    )
    assumptions: ForwardTestAssumptions = Field(
        default_factory=ForwardTestAssumptions,
        description="Active session operational assumptions",
    )


class ForwardTestRecorder:
    """Thread-safe recorder capturing and analyzing live tick observations and execution fidelity."""

    def __init__(
        self,
        symbol: str,
        session_id: str | None = None,
        strategy_id: str | None = None,
        strategy_version: str | None = None,
        assumptions: ForwardTestAssumptions | None = None,
        max_history: int = 50_000,
    ) -> None:
        self.symbol = symbol
        self.session_id = session_id or f"FWD-{uuid4().hex[:8].upper()}"
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.assumptions = assumptions or ForwardTestAssumptions()
        self.started_at = datetime.now(tz=EXCHANGE_TIMEZONE)
        self.ended_at: datetime | None = None
        self._status = ForwardTestStatus.STARTING
        self._error_message: str | None = None
        self._stop_reason: str | None = None

        self._lock = threading.Lock()
        self._observations: deque[ForwardTestObservation] = deque(maxlen=max_history)
        self._orders: list[Order] = []
        self._trades: list[Trade] = []
        self._bars: list[Bar] = []
        self._equity_snapshots: list[dict[str, Any]] = []
        self._positions: dict[str, Position] = {}
        self._errors: list[str] = []

        self._last_tick_time: datetime | None = None
        self._total_ticks = 0
        self._valid_ticks = 0
        self._ticks_with_quotes = 0
        self._anomaly_count = 0
        self._latency_sum = 0.0
        self._latency_samples = 0
        self._max_latency: float | None = None
        self._ending_capital: float | None = None
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0

    @property
    def status(self) -> ForwardTestStatus:
        with self._lock:
            return self._status

    def set_status(
        self,
        status: ForwardTestStatus,
        reason: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update session lifecycle status and optional reason or failure message."""
        with self._lock:
            self._status = status
            if reason:
                self._stop_reason = reason
            if error_message:
                self._error_message = error_message
                self._errors.append(error_message)

    def record_tick(
        self, tick: Tick, received_at: datetime | None = None
    ) -> ForwardTestObservation:
        """Record an incoming tick event and evaluate latency, quotes, and quality flags."""
        rec_time = (
            normalize_to_ist(received_at)
            if received_at is not None
            else datetime.now(tz=EXCHANGE_TIMEZONE)
        )
        tick_time = normalize_to_ist(tick.timestamp)

        latency_ms = max(0.0, (rec_time - tick_time).total_seconds() * 1000.0)

        quality_flags: list[str] = []

        # 1. Quote availability
        has_quotes = (
            tick.bid is not None and tick.ask is not None and tick.bid > 0.0 and tick.ask > 0.0
        )
        if not has_quotes:
            quality_flags.append("MISSING_BID_ASK")

        # 2. Session hours
        if self.assumptions.enforce_session_hours and not is_market_open(tick_time):
            quality_flags.append("OFF_SESSION")

        # 3. Latency check
        if latency_ms > self.assumptions.max_tolerated_latency_ms:
            quality_flags.append("HIGH_LATENCY")

        # 4. Synthetic observation
        if tick.is_synthetic:
            quality_flags.append("SYNTHETIC_DATA")

        with self._lock:
            # 5. Out of order detection
            if self._last_tick_time is not None and tick_time < self._last_tick_time:
                quality_flags.append("OUT_OF_ORDER")

            self._last_tick_time = tick_time

            fill_on_quotes = self.assumptions.quote_fill_enabled and has_quotes

            obs = ForwardTestObservation(
                timestamp=tick_time,
                received_at=rec_time,
                symbol=tick.symbol,
                ltp=tick.ltp,
                bid=tick.bid,
                ask=tick.ask,
                volume=tick.volume,
                oi=tick.oi,
                latency_ms=round(latency_ms, 2),
                quality_flags=quality_flags,
                fill_evaluated_on_quotes=fill_on_quotes,
                is_synthetic=tick.is_synthetic,
            )

            self._observations.append(obs)
            self._total_ticks += 1
            if not quality_flags:
                self._valid_ticks += 1
            else:
                self._anomaly_count += 1

            if has_quotes:
                self._ticks_with_quotes += 1

            self._latency_sum += latency_ms
            self._latency_samples += 1
            if self._max_latency is None or latency_ms > self._max_latency:
                self._max_latency = latency_ms

            return obs

    def record_order(self, order: Order) -> None:
        """Record paper order transition."""
        with self._lock:
            self._orders.append(order)

    def record_trade(self, trade: Trade) -> None:
        """Record paper trade fill."""
        with self._lock:
            self._trades.append(trade)

    def record_bar(self, bar: Bar) -> None:
        """Record completed bar."""
        with self._lock:
            self._bars.append(bar)

    def record_equity_snapshot(self, balance: AccountBalance, timestamp: datetime) -> None:
        """Record periodic account balance and capital snapshot."""
        with self._lock:
            self._ending_capital = balance.total_capital
            self._realized_pnl = balance.realized_pnl
            self._unrealized_pnl = balance.unrealized_pnl
            self._equity_snapshots.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "total_capital": balance.total_capital,
                    "available_margin": balance.available_margin,
                    "used_margin": balance.used_margin,
                    "realized_pnl": balance.realized_pnl,
                    "unrealized_pnl": balance.unrealized_pnl,
                }
            )

    def record_positions(self, positions: list[Position]) -> None:
        """Snapshot current active positions."""
        with self._lock:
            for p in positions:
                self._positions[p.symbol] = p

    def record_error(self, error: str, fatal: bool = False) -> None:
        """Record diagnostic error or warning."""
        with self._lock:
            self._errors.append(error)
            if fatal:
                self._status = ForwardTestStatus.FAILED
                self._error_message = error

    def get_observations(self) -> list[ForwardTestObservation]:
        """Return chronological snapshot of all recorded observations."""
        with self._lock:
            return list(self._observations)

    def get_orders(self) -> list[Order]:
        """Return copy of all recorded orders."""
        with self._lock:
            return list(self._orders)

    def get_trades(self) -> list[Trade]:
        """Return copy of all recorded trades."""
        with self._lock:
            return list(self._trades)

    def get_bars(self) -> list[Bar]:
        """Return copy of all completed bars."""
        with self._lock:
            return list(self._bars)

    def conclude_session(self) -> ForwardTestSession:
        """Conclude forward-testing session and record ending timestamp."""
        with self._lock:
            if self.ended_at is None:
                self.ended_at = datetime.now(tz=EXCHANGE_TIMEZONE)
            if self._status in (
                ForwardTestStatus.STARTING,
                ForwardTestStatus.RUNNING,
                ForwardTestStatus.STOPPING,
            ):
                self._status = ForwardTestStatus.COMPLETED
            return self._build_summary()

    def get_session_summary(self) -> ForwardTestSession:
        """Return current audit summary of the forward-testing session."""
        with self._lock:
            return self._build_summary()

    def _build_summary(self) -> ForwardTestSession:
        avg_lat = (
            round(self._latency_sum / self._latency_samples, 2)
            if self._latency_samples > 0
            else None
        )
        max_lat = round(self._max_latency, 2) if self._max_latency is not None else None

        return ForwardTestSession(
            session_id=self.session_id,
            symbol=self.symbol,
            started_at=self.started_at,
            ended_at=self.ended_at,
            status=self._status,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            total_ticks=self._total_ticks,
            valid_ticks=self._valid_ticks,
            ticks_with_quotes=self._ticks_with_quotes,
            anomaly_count=self._anomaly_count,
            avg_latency_ms=avg_lat,
            max_latency_ms=max_lat,
            bars_count=len(self._bars),
            orders_count=len(self._orders),
            trades_count=len(self._trades),
            realized_pnl=self._realized_pnl,
            unrealized_pnl=self._unrealized_pnl,
            ending_capital=self._ending_capital,
            error_message=self._error_message,
            stop_reason=self._stop_reason,
            assumptions=self.assumptions,
        )

    def export_dossier(self) -> dict[str, Any]:
        """Export comprehensive session dossier dictionary for offline persistence and inspection."""
        with self._lock:
            summary = self._build_summary().model_dump(mode="json")
            orders_dump = [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type.value,
                    "qty": o.qty,
                    "price": o.price,
                    "status": o.status.value,
                    "filled_qty": o.filled_qty,
                    "average_fill_price": o.average_fill_price,
                    "rejection_reason": o.rejection_reason,
                    "created_at": o.created_at.isoformat(),
                    "updated_at": o.updated_at.isoformat(),
                }
                for o in self._orders
            ]
            trades_dump = [
                {
                    "trade_id": t.trade_id,
                    "order_id": t.order_id,
                    "symbol": t.symbol,
                    "side": t.side.value,
                    "qty": t.qty,
                    "fill_price": t.fill_price,
                    "slippage": t.slippage,
                    "stt": t.stt,
                    "charges": t.charges,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in self._trades
            ]
            positions_dump = [
                {
                    "symbol": p.symbol,
                    "qty": p.qty,
                    "buy_avg_price": p.buy_avg_price,
                    "sell_avg_price": p.sell_avg_price,
                    "realized_pnl": p.realized_pnl,
                    "unrealized_pnl": p.unrealized_pnl,
                    "updated_at": p.updated_at.isoformat(),
                }
                for p in self._positions.values()
            ]

            obs_list = list(self._observations)
            obs_sample = [
                o.model_dump(mode="json")
                for o in (obs_list[:50] + obs_list[-50:] if len(obs_list) > 100 else obs_list)
            ]

            return {
                "session": summary,
                "assumptions": self.assumptions.model_dump(mode="json"),
                "orders": orders_dump,
                "trades": trades_dump,
                "positions": positions_dump,
                "equity_snapshots": list(self._equity_snapshots),
                "observations_sample": obs_sample,
                "errors": list(self._errors),
            }

    def save_to_json(self, file_path: Path | str) -> Path:
        """Write session dossier to disk."""
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        dossier = self.export_dossier()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(dossier, f, indent=2)
        return target
