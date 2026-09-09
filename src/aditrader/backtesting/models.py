"""Deterministic backtesting domain models, event stream, and Run Dossier schemas.

Per ARCHITECTURE.md, SPEC.md, and hostile audit remediation contracts:
- Formal ExecutionEventType lifecycle enum
- BacktestEvent with sequence numbering and canonical hashing
- RoundtripTrade ledger separating Gross PnL from Net PnL and fee attribution
- TradeLedger with Merkle root hash computation
- Structured RunDossier schema unifying Identity, Dataset, Configuration, Execution,
  Results, Verification, and Provenance.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.enums import OrderSide
from aditrader.verification.models import VerificationMatrix
from aditrader.verification.reconciliation import ReconciliationReport


def compute_binary_merkle_root(leaf_hashes: list[str]) -> str:
    """Compute deterministic binary SHA-256 Merkle root over an ordered sequence of leaf hashes."""
    if not leaf_hashes:
        return hashlib.sha256(b"EMPTY_MERKLE_TREE").hexdigest()

    current_level = list(leaf_hashes)
    while len(current_level) > 1:
        next_level: list[str] = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            combined = hashlib.sha256(f"{left}:{right}".encode()).hexdigest()
            next_level.append(combined)
        current_level = next_level
    return current_level[0]


class ExecutionContractType(StrEnum):
    """Institutional vs Academic execution standard."""

    INSTITUTIONAL_STRICT = "INSTITUTIONAL_STRICT"
    ACADEMIC_EXPLORATORY = "ACADEMIC_EXPLORATORY"


class ExecutionEventType(StrEnum):
    """Discrete, ordered execution event types in the backtest lifecycle."""

    BAR_OBSERVED = "BAR_OBSERVED"
    SESSION_START = "SESSION_START"
    EXECUTION_ELIGIBILITY = "EXECUTION_ELIGIBILITY"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    UNFULFILLED_SIGNAL = "UNFULFILLED_SIGNAL"
    POSITION_CHANGED = "POSITION_CHANGED"
    ACCOUNT_UPDATED = "ACCOUNT_UPDATED"
    STRATEGY_EVALUATED = "STRATEGY_EVALUATED"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    ORDER_STAGED = "ORDER_STAGED"
    LIQUIDITY_BREACH = "LIQUIDITY_BREACH"
    SESSION_SQUAREOFF = "SESSION_SQUAREOFF"
    SESSION_END = "SESSION_END"
    RUN_TERMINATED = "RUN_TERMINATED"


class BacktestEvent(BaseModel):
    """Individual immutable execution event in the deterministic replay timeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(..., description="Unique deterministic event ID (e.g. EVT-000001)")
    sequence_num: int = Field(..., ge=1, description="Strictly monotonic sequence number")
    timestamp: datetime = Field(..., description="Point-in-time timestamp of event occurrence")
    event_type: ExecutionEventType = Field(..., description="Classification of lifecycle event")
    symbol: str = Field(..., description="Target instrument symbol")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Structured contextual event attributes"
    )

    def compute_hash(self) -> str:
        """Compute canonical SHA-256 hash of this event."""
        payload = {
            "details": self.details,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "sequence_num": self.sequence_num,
            "symbol": self.symbol,
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class RoundtripTrade(BaseModel):
    """Authoritative roundtrip closed or open position trade record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str = Field(..., description="Unique deterministic trade ID (e.g. TRD-000001)")
    run_id: str = Field(..., description="Owning backtest run identifier")
    symbol: str = Field(..., description="Target scrip or index symbol")
    side: OrderSide = Field(..., description="Position side (BUY = Long, SELL = Short)")
    quantity: int = Field(..., gt=0, description="Quantity traded in shares/contracts")
    entry_time: datetime = Field(..., description="Fill timestamp of position opening")
    entry_price: float = Field(..., gt=0.0, description="Effective entry execution price")
    exit_time: datetime | None = Field(
        default=None, description="Fill timestamp of position closing (None if open)"
    )
    exit_price: float | None = Field(
        default=None, description="Effective exit execution price (None if open)"
    )
    gross_pnl: float = Field(default=0.0, description="Pre-fee realized P&L in INR")
    stt: float = Field(default=0.0, ge=0.0, description="Securities Transaction Tax in INR")
    charges: float = Field(
        default=0.0, ge=0.0, description="Exchange, SEBI, stamp duty, and GST in INR"
    )
    slippage: float = Field(default=0.0, ge=0.0, description="Total slippage friction in INR")
    total_fees: float = Field(
        default=0.0, ge=0.0, description="Cumulative statutory fees and taxes"
    )
    net_pnl: float = Field(default=0.0, description="Post-fee realized P&L in INR")
    duration_bars: int = Field(default=0, ge=0, description="Holding duration in bars")
    exit_reason: str = Field(
        default="OPEN", description="Trigger for closing (SIGNAL, SL, TP, SQUAREOFF, OPEN)"
    )
    is_closed: bool = Field(default=True, description="True if roundtrip position is fully closed")

    def compute_hash(self) -> str:
        """Compute canonical SHA-256 hash of this trade record."""
        payload = {
            "charges": round(self.charges, 2),
            "duration_bars": self.duration_bars,
            "entry_price": round(self.entry_price, 4),
            "entry_time": self.entry_time.astimezone(UTC).isoformat(),
            "exit_price": round(self.exit_price, 4) if self.exit_price is not None else None,
            "exit_reason": self.exit_reason,
            "exit_time": (
                self.exit_time.astimezone(UTC).isoformat() if self.exit_time is not None else None
            ),
            "gross_pnl": round(self.gross_pnl, 2),
            "is_closed": self.is_closed,
            "net_pnl": round(self.net_pnl, 2),
            "quantity": self.quantity,
            "run_id": self.run_id,
            "side": self.side.value,
            "slippage": round(self.slippage, 2),
            "stt": round(self.stt, 2),
            "symbol": self.symbol,
            "total_fees": round(self.total_fees, 2),
            "trade_id": self.trade_id,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class TradeLedger(BaseModel):
    """Deterministic trade ledger containing all roundtrip executions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Owning backtest run identifier")
    trades: list[RoundtripTrade] = Field(default_factory=list, description="All roundtrip trades")
    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    losing_trades: int = Field(default=0, ge=0)
    gross_profit: float = Field(default=0.0, ge=0.0)
    gross_loss: float = Field(default=0.0, ge=0.0)
    net_profit: float = Field(default=0.0)
    total_fees: float = Field(default=0.0, ge=0.0)
    merkle_root: str = Field(..., description="SHA-256 Merkle root of all trade hashes")

    @classmethod
    def create(cls, run_id: str, trades: list[RoundtripTrade]) -> TradeLedger:
        """Construct ledger and compute deterministic Merkle root."""
        closed = [t for t in trades if t.is_closed]
        wins = [t for t in closed if t.net_pnl > 0.0]
        losses = [t for t in closed if t.net_pnl < 0.0]
        gp = round(sum(t.net_pnl for t in wins), 2)
        gl = round(abs(sum(t.net_pnl for t in losses)), 2)
        np_val = round(sum(t.net_pnl for t in closed), 2)
        tf = round(sum(t.total_fees for t in trades), 2)

        # Compute binary Merkle root over trade hashes
        root = compute_binary_merkle_root([t.compute_hash() for t in trades])

        return cls(
            run_id=run_id,
            trades=trades,
            total_trades=len(closed),
            winning_trades=len(wins),
            losing_trades=len(losses),
            gross_profit=gp,
            gross_loss=gl,
            net_profit=np_val,
            total_fees=tf,
            merkle_root=root,
        )


class RunDossier(BaseModel):
    """Structured, reproducible institutional quantitative research and execution dossier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 1. Identity
    run_id: str = Field(..., description="Unique run identifier (e.g. run_bt_a1b2c3d4)")
    created_at: datetime = Field(..., description="Timestamp of run completion")
    engine_version: str = Field(default="1.0.0", description="AdiTrader execution engine version")
    execution_contract: ExecutionContractType = Field(
        default=ExecutionContractType.INSTITUTIONAL_STRICT,
        description="Execution standard applied",
    )
    strategy_id: str = Field(..., description="Strategy identifier")
    strategy_name: str = Field(..., description="Strategy name")
    strategy_version: str = Field(default="1.0", description="Strategy definition version")
    strategy_hash: str = Field(..., description="Canonical SHA-256 digest of strategy AST")

    # 2. Dataset
    dataset_name: str = Field(..., description="Name of dataset file")
    dataset_path: str = Field(..., description="Path to dataset file")
    dataset_hash: str = Field(..., description="SHA-256 digest of raw dataset content")
    timeframe: str = Field(..., description="Data bar timeframe (e.g. 1m, 5m)")
    symbol: str = Field(..., description="Instrument symbol")
    start_time: datetime = Field(..., description="Earliest bar timestamp")
    end_time: datetime = Field(..., description="Latest bar timestamp")
    bar_count: int = Field(..., ge=0, description="Total historical bars processed")
    integrity_passed: bool = Field(..., description="True if dataset passed DataIntegrityChecker")

    # 3. Configuration & Assumptions
    initial_capital: float = Field(..., gt=0.0, description="Starting cash capital in INR")
    slippage_bps: float = Field(..., ge=0.0, description="Configured slippage in basis points")
    fill_assumption: str = Field(
        ..., description="Fill timing assumption (NEXT_BAR_OPEN vs SAME_BAR_CLOSE)"
    )
    cost_model: str = Field(default="NSE_STATUTORY", description="Fee schedule applied")
    timezone: str = Field(default="Asia/Kolkata", description="Exchange operating timezone")
    intraday_squareoff: bool = Field(
        default=True, description="Whether 15:15 IST auto-squareoff was enforced"
    )

    # 4. Execution Counts
    event_count: int = Field(..., ge=0, description="Total lifecycle events recorded")
    order_count: int = Field(..., ge=0, description="Total orders submitted")
    fill_count: int = Field(..., ge=0, description="Total fill transactions executed")
    rejected_count: int = Field(..., ge=0, description="Total orders rejected by risk/liquidity")
    trade_count: int = Field(..., ge=0, description="Total completed roundtrip trades")
    terminal_open_positions_count: int = Field(
        default=0, ge=0, description="Unclosed positions at backtest terminus"
    )

    # 5. Results & Metrics
    starting_equity: float = Field(..., ge=0.0)
    ending_equity: float = Field(..., description="Final mark-to-market portfolio equity")
    liquidated_ending_equity: float | None = Field(
        default=None,
        description="Hypothetical ending equity after liquidating terminal open positions",
    )
    net_profit: float = Field(..., description="Total net profit/loss in INR")
    return_pct: float = Field(..., description="Percentage return on initial capital")
    win_rate: float = Field(..., ge=0.0, le=1.0)
    closed_trade_expectancy: float = Field(
        ..., description="Expectancy calculated strictly on closed trades"
    )
    terminal_adjusted_expectancy: float = Field(
        ..., description="Expectancy factoring in terminal liquidation friction"
    )
    profit_factor: float | None = Field(default=None)
    max_drawdown_amount: float = Field(..., ge=0.0)
    max_drawdown_pct: float = Field(..., ge=0.0, le=1.0)
    sharpe_ratio: float | None = Field(default=None)
    sortino_ratio: float | None = Field(default=None)
    sqn: float | None = Field(default=None)

    # 6. Verification & Auditing
    verification_matrix: VerificationMatrix = Field(
        ..., description="7-pillar institutional verification matrix"
    )
    reconciliation: ReconciliationReport = Field(
        ..., description="Balance sheet reconciliation audit"
    )
    evidence_bundle_id: str | None = Field(
        default=None, description="Associated EvidenceBundle identifier"
    )
    event_stream_merkle_root: str = Field(
        ..., description="SHA-256 Merkle root of all backtest events"
    )
    trade_ledger_merkle_root: str = Field(
        ..., description="SHA-256 Merkle root of all trade ledger records"
    )
    tamper_digest: str = Field(..., description="Cryptographic SHA-256 digest sealing this dossier")

    # 7. Embedded Audit Trail
    events: list[BacktestEvent] = Field(default_factory=list, description="Ordered event timeline")
    ledger: list[RoundtripTrade] = Field(default_factory=list, description="Trade ledger entries")
    provenance: dict[str, Any] = Field(
        default_factory=dict, description="Step-by-step metric calculation traces"
    )

    @classmethod
    def compute_tamper_digest(
        cls,
        *,
        run_id: str,
        strategy_hash: str,
        dataset_hash: str,
        initial_capital: float,
        net_profit: float,
        ending_equity: float,
        event_stream_root: str,
        trade_ledger_root: str,
        matrix_status: str,
        created_at: datetime,
    ) -> str:
        """Compute top-level SHA-256 tamper digest binding config, data, ledger, and event stream."""
        payload = {
            "created_at": created_at.astimezone(UTC).isoformat(),
            "dataset_hash": dataset_hash,
            "ending_equity": round(ending_equity, 2),
            "event_stream_root": event_stream_root,
            "initial_capital": round(initial_capital, 2),
            "matrix_status": matrix_status,
            "net_profit": round(net_profit, 2),
            "run_id": run_id,
            "strategy_hash": strategy_hash,
            "trade_ledger_root": trade_ledger_root,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def verify_tamper_digest(self) -> bool:
        """Verify that the dossier contents match the cryptographic tamper digest.

        Re-hashes every trade in the ledger and every event in the event stream from raw data
        to detect any mutation of individual trade or event records in storage.
        """
        # 1. Recompute binary Merkle root over all trades in ledger
        fresh_trade_hashes = [t.compute_hash() for t in self.ledger]
        fresh_trade_root = compute_binary_merkle_root(fresh_trade_hashes)
        if fresh_trade_root != self.trade_ledger_merkle_root:
            return False

        # 2. Recompute binary Merkle root over all events in stream
        fresh_event_hashes = [e.compute_hash() for e in self.events]
        fresh_event_root = compute_binary_merkle_root(fresh_event_hashes)
        if fresh_event_root != self.event_stream_merkle_root:
            return False

        # 3. Verify top-level tamper digest
        computed = self.compute_tamper_digest(
            run_id=self.run_id,
            strategy_hash=self.strategy_hash,
            dataset_hash=self.dataset_hash,
            initial_capital=self.initial_capital,
            net_profit=self.net_profit,
            ending_equity=self.ending_equity,
            event_stream_root=self.event_stream_merkle_root,
            trade_ledger_root=self.trade_ledger_merkle_root,
            matrix_status=self.verification_matrix.overall_status.value,
            created_at=self.created_at,
        )
        return secrets.compare_digest(computed, self.tamper_digest)
