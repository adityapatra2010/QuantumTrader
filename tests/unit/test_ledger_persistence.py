"""Unit tests verifying local SQLite ledger persistence, ORM mappings, and WAL mode."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from aditrader.core.ledger.repository import LedgerRepository
from aditrader.core.models import (
    AccountBalance,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Trade,
)


@pytest.fixture
def repo(tmp_path: Path) -> LedgerRepository:
    db_path = tmp_path / "test_ledger.db"
    repository = LedgerRepository(f"sqlite:///{db_path}")
    repository.create_tables()
    return repository


def test_sqlite_wal_mode_enforced(repo: LedgerRepository) -> None:
    """Verify WAL pragma is enabled on the SQLite engine (ADR 008)."""
    with repo.engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert str(mode).upper() == "WAL"


def test_save_and_retrieve_order_lifecycle(repo: LedgerRepository) -> None:
    """Verify saving initial order and updating state transitions."""
    now = datetime.now(UTC)
    run_id = "RUN-001"

    order = Order(
        order_id="ORD-PERSIST-1",
        symbol="NIFTY",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=50,
        price=24000.0,
        status=OrderStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    repo.save_order(order, run_id=run_id)

    orders = repo.get_orders(run_id=run_id)
    assert len(orders) == 1
    assert orders[0].order_id == "ORD-PERSIST-1"
    assert orders[0].status == OrderStatus.CREATED

    # Update to FILLED
    updated = order.model_copy(
        update={
            "status": OrderStatus.FILLED,
            "filled_qty": 50,
            "average_fill_price": 24005.0,
            "updated_at": now,
        }
    )
    repo.save_order(updated, run_id=run_id)

    orders_updated = repo.get_orders(run_id=run_id)
    assert len(orders_updated) == 1
    assert orders_updated[0].status == OrderStatus.FILLED
    assert orders_updated[0].filled_qty == 50
    assert orders_updated[0].average_fill_price == 24005.0


def test_append_only_trades_ledger(repo: LedgerRepository) -> None:
    """Verify trades ledger is strictly append-only and queryable."""
    now = datetime.now(UTC)
    run_id = "RUN-002"

    trade1 = Trade(
        trade_id="TRD-01",
        order_id="ORD-01",
        symbol="BANKNIFTY",
        side=OrderSide.BUY,
        qty=15,
        fill_price=51000.0,
        slippage=5.0,
        stt=0.0,
        charges=45.2,
        timestamp=now,
    )
    trade2 = Trade(
        trade_id="TRD-02",
        order_id="ORD-02",
        symbol="BANKNIFTY",
        side=OrderSide.SELL,
        qty=15,
        fill_price=51200.0,
        slippage=5.0,
        stt=10.2,
        charges=48.5,
        timestamp=now,
    )

    repo.save_trade(trade1, run_id=run_id)
    repo.save_trade(trade2, run_id=run_id)

    trades = repo.get_trades(run_id=run_id)
    assert len(trades) == 2
    assert trades[0].trade_id == "TRD-01"
    assert trades[1].trade_id == "TRD-02"
    assert trades[0].qty == 15
    assert trades[1].stt == 10.2


def test_position_upsert_and_balance_snapshots(repo: LedgerRepository) -> None:
    """Verify position upsert and account balance snapshot retrieval."""
    now = datetime.now(UTC)
    run_id = "RUN-003"

    pos = Position(
        symbol="FINNIFTY",
        qty=40,
        buy_avg_price=22000.0,
        sell_avg_price=0.0,
        realized_pnl=0.0,
        unrealized_pnl=1500.0,
        updated_at=now,
    )
    repo.save_position(pos, run_id=run_id)

    positions = repo.get_positions(run_id=run_id)
    assert len(positions) == 1
    assert positions[0].symbol == "FINNIFTY"
    assert positions[0].qty == 40
    assert positions[0].unrealized_pnl == 1500.0

    # Save balance snapshots
    bal1 = AccountBalance(
        total_capital=1000000.0,
        available_margin=850000.0,
        used_margin=150000.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
    )
    bal2 = AccountBalance(
        total_capital=1001500.0,
        available_margin=848500.0,
        used_margin=153000.0,
        realized_pnl=500.0,
        unrealized_pnl=1000.0,
    )
    repo.save_balance(bal1, run_id=run_id)
    repo.save_balance(bal2, run_id=run_id)

    latest_bal = repo.get_latest_balance(run_id=run_id)
    assert latest_bal is not None
    assert latest_bal.total_capital == 1001500.0
    assert latest_bal.realized_pnl == 500.0
