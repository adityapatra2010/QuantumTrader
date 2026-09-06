name: Database Design
description: Persistence schema, migration policies, and data separation standards.

# Goal
Provide an isolated, auditable data persistence tier separating high-throughput market tick data from relational application entities[cite: 1, 2].

# Storage Layer Separation
- **Time-Series / Market Data**: Parquet files partitioned by `date/symbol` under `data/cache/` for tick and OHLCV history; in-memory Polars dataframes for runtime aggregation.
- **Relational Domain Store**: SQLite (local runtime) via SQLAlchemy with Alembic migrations for strategies, test runs, and audit logs.

# Core Tables & Schemas
- `strategies`: Core entity (`id`, `name`, `type`, `creator`, `created_at`, `is_active`).
- `strategy_versions`: Semantic versions (`id`, `strategy_id`, `version`, `dsl_json`, `dna_profile`, `created_at`).
- `validation_results`: Pre-trade and backtest audit results (`id`, `strategy_version_id`, `score`, `status`, `expectancy`, `drawdown`, `reasons_json`).
- `backtest_runs`: Execution metadata (`id`, `strategy_version_id`, `source`, `start_time`, `end_time`, `initial_capital`, `final_equity`).
- `orders`: Order state machine records (`id`, `run_id`, `signal_id`, `symbol`, `side`, `order_type`, `qty`, `price`, `status`, `created_at`, `updated_at`).
- `trades`: Append-only execution fill ledger (`id`, `run_id`, `order_id`, `timestamp`, `symbol`, `side`, `qty`, `fill_price`, `slippage`, `brokerage_stt`).
- `positions`: Portfolio tracking records (`id`, `run_id`, `symbol`, `qty`, `buy_avg_price`, `sell_avg_price`, `realized_pnl`, `unrealized_pnl`, `updated_at`).
- `research_reports`: Compiled analytical dossiers (`id`, `run_id`, `markdown_body`, `metrics_json`, `ai_critique_json`).

# Schema Rules
- **Migrations Only**: Never mutate table structures manually; all structural changes must be committed via versioned Alembic migration scripts.
- **Append-Only Ledgers**: The `trades` table is strictly immutable. Corrections or square-offs must append compensating records; never update or delete executed fills[cite: 2].
- **Index Hygiene**: Require compound indexes on `(symbol, timestamp)` for time-indexed queries and `(strategy_id, version)` for lookup efficiency.
