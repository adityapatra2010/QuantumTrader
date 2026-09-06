"""Transactional ledger repository managing persistence to SQLite/PostgreSQL."""

from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import sessionmaker

from aditrader.core.ledger.schema import (
    AccountBalanceRecord,
    Base,
    OrderRecord,
    PositionRecord,
    TradeRecord,
)
from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType
from aditrader.core.models.execution import AccountBalance, Position, Trade
from aditrader.core.models.order import Order


class LedgerRepository:
    """Repository managing transactional ledger state and audit logs."""

    def __init__(self, database_url: str = "sqlite:///runs/aditrader.db"):
        self.database_url = database_url
        self.engine: Engine = create_engine(database_url)

        # Enforce WAL mode and busy timeout for SQLite connections (ADR 008)
        if "sqlite" in database_url:

            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
                cursor = getattr(dbapi_connection, "cursor", None)
                if cursor and callable(cursor):
                    cur = cursor()
                    cur.execute("PRAGMA journal_mode=WAL;")
                    cur.execute("PRAGMA busy_timeout=5000;")
                    cur.close()

        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_tables(self) -> None:
        """Create tables in database if they do not already exist."""
        Base.metadata.create_all(self.engine)

    def save_order(self, order: Order, run_id: str) -> None:
        """Insert or update order record."""
        with self.SessionLocal() as session:
            stmt = select(OrderRecord).where(
                OrderRecord.run_id == run_id,
                OrderRecord.order_id == order.order_id,
            )
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                existing.status = order.status.value
                existing.filled_qty = order.filled_qty
                existing.average_fill_price = order.average_fill_price
                existing.rejection_reason = order.rejection_reason
                existing.updated_at = order.updated_at
            else:
                record = OrderRecord(
                    run_id=run_id,
                    order_id=order.order_id,
                    signal_id=order.signal_id,
                    symbol=order.symbol,
                    side=order.side.value,
                    order_type=order.order_type.value,
                    qty=order.qty,
                    price=order.price,
                    status=order.status.value,
                    filled_qty=order.filled_qty,
                    average_fill_price=order.average_fill_price,
                    rejection_reason=order.rejection_reason,
                    created_at=order.created_at,
                    updated_at=order.updated_at,
                )
                session.add(record)
            session.commit()

    def save_trade(self, trade: Trade, run_id: str) -> None:
        """Append immutable trade fill to the ledger."""
        with self.SessionLocal() as session:
            record = TradeRecord(
                run_id=run_id,
                trade_id=trade.trade_id,
                order_id=trade.order_id,
                symbol=trade.symbol,
                side=trade.side.value,
                qty=trade.qty,
                fill_price=trade.fill_price,
                slippage=trade.slippage,
                stt=trade.stt,
                charges=trade.charges,
                timestamp=trade.timestamp,
            )
            session.add(record)
            session.commit()

    def save_position(self, position: Position, run_id: str) -> None:
        """Upsert current position for an instrument."""
        with self.SessionLocal() as session:
            stmt = select(PositionRecord).where(
                PositionRecord.run_id == run_id,
                PositionRecord.symbol == position.symbol,
            )
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                existing.qty = position.qty
                existing.buy_avg_price = position.buy_avg_price
                existing.sell_avg_price = position.sell_avg_price
                existing.realized_pnl = position.realized_pnl
                existing.unrealized_pnl = position.unrealized_pnl
                existing.updated_at = position.updated_at
            else:
                record = PositionRecord(
                    run_id=run_id,
                    symbol=position.symbol,
                    qty=position.qty,
                    buy_avg_price=position.buy_avg_price,
                    sell_avg_price=position.sell_avg_price,
                    realized_pnl=position.realized_pnl,
                    unrealized_pnl=position.unrealized_pnl,
                    updated_at=position.updated_at,
                )
                session.add(record)
            session.commit()

    def save_balance(self, balance: AccountBalance, run_id: str) -> None:
        """Append account balance snapshot."""
        with self.SessionLocal() as session:
            record = AccountBalanceRecord(
                run_id=run_id,
                total_capital=balance.total_capital,
                available_margin=balance.available_margin,
                used_margin=balance.used_margin,
                realized_pnl=balance.realized_pnl,
                unrealized_pnl=balance.unrealized_pnl,
                timestamp=datetime.now(UTC),
            )
            session.add(record)
            session.commit()

    def get_orders(self, run_id: str) -> list[Order]:
        """Fetch all orders for a run."""
        with self.SessionLocal() as session:
            stmt = (
                select(OrderRecord)
                .where(OrderRecord.run_id == run_id)
                .order_by(OrderRecord.created_at)
            )
            records = session.execute(stmt).scalars().all()
            return [
                Order(
                    order_id=r.order_id,
                    signal_id=r.signal_id,
                    symbol=r.symbol,
                    side=OrderSide(r.side),
                    order_type=OrderType(r.order_type),
                    qty=r.qty,
                    price=r.price,
                    status=OrderStatus(r.status),
                    filled_qty=r.filled_qty,
                    average_fill_price=r.average_fill_price,
                    rejection_reason=r.rejection_reason,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in records
            ]

    def get_trades(self, run_id: str) -> list[Trade]:
        """Fetch all trades for a run."""
        with self.SessionLocal() as session:
            stmt = (
                select(TradeRecord)
                .where(TradeRecord.run_id == run_id)
                .order_by(TradeRecord.timestamp)
            )
            records = session.execute(stmt).scalars().all()
            return [
                Trade(
                    trade_id=r.trade_id,
                    order_id=r.order_id,
                    symbol=r.symbol,
                    side=OrderSide(r.side),
                    qty=r.qty,
                    fill_price=r.fill_price,
                    slippage=r.slippage,
                    stt=r.stt,
                    charges=r.charges,
                    timestamp=r.timestamp,
                )
                for r in records
            ]

    def get_positions(self, run_id: str) -> list[Position]:
        """Fetch all positions for a run."""
        with self.SessionLocal() as session:
            stmt = select(PositionRecord).where(PositionRecord.run_id == run_id)
            records = session.execute(stmt).scalars().all()
            return [
                Position(
                    symbol=r.symbol,
                    qty=r.qty,
                    buy_avg_price=r.buy_avg_price,
                    sell_avg_price=r.sell_avg_price,
                    realized_pnl=r.realized_pnl,
                    unrealized_pnl=r.unrealized_pnl,
                    updated_at=r.updated_at,
                )
                for r in records
            ]

    def get_latest_balance(self, run_id: str) -> AccountBalance | None:
        """Fetch the most recent balance snapshot for a run."""
        with self.SessionLocal() as session:
            stmt = (
                select(AccountBalanceRecord)
                .where(AccountBalanceRecord.run_id == run_id)
                .order_by(AccountBalanceRecord.timestamp.desc())
                .limit(1)
            )
            record = session.execute(stmt).scalar_one_or_none()
            if not record:
                return None
            return AccountBalance(
                total_capital=record.total_capital,
                available_margin=record.available_margin,
                used_margin=record.used_margin,
                realized_pnl=record.realized_pnl,
                unrealized_pnl=record.unrealized_pnl,
            )
