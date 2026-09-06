"""Create core domain ledger tables.

Revision ID: 0002_core_tables
Revises: 0001_baseline
Create Date: 2026-09-06 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_core_tables"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Orders table
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("signal_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("filled_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("rejection_reason", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_run_id", "orders", ["run_id"])
    op.create_index("ix_orders_order_id", "orders", ["order_id"])
    op.create_index("ix_orders_run_symbol", "orders", ["run_id", "symbol"])

    # 2. Trades table (append-only ledger)
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("fill_price", sa.Float(), nullable=False),
        sa.Column("slippage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("stt", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("charges", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id"),
    )
    op.create_index("ix_trades_run_id", "trades", ["run_id"])
    op.create_index("ix_trades_order_id", "trades", ["order_id"])
    op.create_index("ix_trades_run_symbol_ts", "trades", ["run_id", "symbol", "timestamp"])

    # 3. Positions table
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("buy_avg_price", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("sell_avg_price", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_positions_run_id", "positions", ["run_id"])
    op.create_index("ix_positions_run_symbol", "positions", ["run_id", "symbol"], unique=True)

    # 4. Account balances snapshot table
    op.create_table(
        "account_balances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("total_capital", sa.Float(), nullable=False),
        sa.Column("available_margin", sa.Float(), nullable=False),
        sa.Column("used_margin", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_balances_run_id", "account_balances", ["run_id"])


def downgrade() -> None:
    op.drop_table("account_balances")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("orders")
