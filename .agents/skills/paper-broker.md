name: Paper Broker Semantics
description: Realistic fill simulation, accounting, and order lifecycle management.

# Goal
Simulate trade execution against market data feeds with realistic market friction, maintaining a single source of truth for portfolio records[cite: 2].

# Simulation Mechanics
- Ingest `Signal` objects and match them against the latest LTP tick[cite: 2].
- Apply configurable slippage penalties (e.g., bid-ask spread crossing) and regulatory transaction costs.
- Track margin requirements and reject trades if simulated account margin utilization exceeds configured thresholds[cite: 1, 2].
- Update `Trade`, `Position`, and `PnL` states atomically[cite: 2].

# Persistence
- Persist fills and ledger balances to local storage (SQLite/Parquet)[cite: 2].
- Both the Dash UI and CLI commands must read exclusively from this local store to prevent metric discrepancies[cite: 2].
