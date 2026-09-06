# System Architecture

## Architectural Philosophy
The platform is designed as a modular trading operating system rather than a monolithic paper-trading script. Core analytical, validation, and execution layers interact via strictly decoupled interfaces, preventing lock-in to specific brokerage APIs or AI model vendors.

+-----------------------------------------------------------------------+
|                           Presentation Layer                          |
|         Plotly Dash Multi-Page Dashboard     |     Typer/Click CLI    |
+-----------------------------------+-----------------------------------+
|
v
+-----------------------------------------------------------------------+
|                          Application Services                         |
|   Strategy Builder Engine   |   Validation Engine   |   Research WS   |
+-----------------------------------+-----------------------------------+
|
v
+-----------------------------------------------------------------------+
|                          Domain Core & Options                        |
|   Options Engine (Chain/Greeks/Payoffs)    |    Paper Broker Engine   |
+-----------------------------------+-----------------------------------+
|
v
+-----------------------------------------------------------------------+
|                      Infrastructure & Adapters                        |
|   Broker Adapters (Kotak Neo)   |   AI Subsystems (Kronos / Gemini)   |
+-----------------------------------------------------------------------+


---

## Subsystem Breakdown

### 1. Broker Data Layer (`data/`)
- Isolates broker-specific SDKs (e.g., Kotak Neo Python SDK)[cite: 1, 2].
- Responsibilities: Authentication (TOTP + MPIN), streaming live ticks via WebSocket (`KotakDataFeed`), scrip master discovery, and historical OHLCV bar fetch[cite: 2].
- Strict Boundary: Real-order placement functions are entirely excluded; only market data and contract metadata are exposed to upstream modules[cite: 1, 2].

### 2. Core Paper Broker & Execution State (`core/`)
- Simulated broker engine maintaining an append-only, transactional ledger (ADR 002).
- Ingests `Signal` objects and calculates execution fills against the latest market prices with configurable slippage and exchange fees.
- Integrated Runtime Risk Engine (`core/risk/`): Evaluates every order at fill time for pre-trade margin limits (utilization $\le 85\%$), expiry gamma explosion, and triggers immediate emergency halts if intraday drawdown reaches $5\%$.
- Maintains margin requirements, open positions, realized/unrealized P&L, and trade histories.
- Persists data to an isolated local SQLite/Parquet run-store with WAL mode (ADR 008). Both the CLI and Dash dashboard read from this store as the single source of truth.

### 3. Options Derivatives Subsystem (`options/`)
- Pure calculation engine for Indian options contracts.
- `chain.py`: Normalizes options chains into structured records derived dynamically from the broker scrip master (ADR 009).
- `greeks.py`: Evaluates Black-Scholes Greeks (Delta, Gamma, Theta, Vega) using spot price, strike, IV, and time-to-expiry.
- `payoff.py`: Pure function computing expiration and mark-to-market payoff curves for multi-leg strategies without broker side-effects.

### 4. Validation Engine (`validation/`)
- Pre-trade and post-backtest gatekeeper enforcing static schema integrity and quantitative risk controls before any strategy enters the paper broker (ADR 004).
- `validation/ast/`: Static JSON DSL tree validator checking schema versioning, leg balance, valid strike offsets, and operator legality.
- `validation/institutional/`: Statistical gatekeeper evaluating historical backtest runs: `expectancy.py`, `pop.py`, `drawdown.py`, `sharpe.py`, `overfit.py`, `sample_size.py`, `gamma_risk.py`.
- Rejection Authority: Programmatically vetoes strategies failing the active Validation Policy (e.g., negative expectancy, unhedged tail risk, insufficient trade sample size).

### 5. Strategy Builder Engine (`strategy/`)
- Declarative condition compiler operating on structured JSON AST trees (ADR 001, ADR 007).
- Categorized conditions: Indicators, Time/Session, Premium, Open Interest (OI), Greeks, Momentum, Market Structure, AI Vision, and AI Forecast.
- Strictly prohibits dynamic code execution (`eval()`, `exec()`, or runtime Python scripts). All conditions evaluate via statically typed AST operators (`GREATER_THAN`, `LESS_THAN`, `CROSSES_ABOVE`, `CROSSES_BELOW`, `WITHIN_RANGE`, `AND`, `OR`).
- Evaluates condition trees deterministically: `evaluate(context) -> bool` and compiles execution state machines implementing `on_bar(history: list[Bar]) -> Optional[Signal]`.

### 6. Strategy Library & DNA (`library/`)
- Catalog of Built-in, AI-Generated, and User-Defined strategies.
- Strategy DNA profiler: Computes vector metadata (Directionality, Theta Exposure, Vega Risk, Margin Efficiency, Scalp vs. Positional) to match strategies against market regimes.

### 7. AI Subsystem (`ai/`)
- Encapsulates machine learning models behind swappable interfaces:
  - `forecasting/`: Foundation time-series models (Kronos, Chronos) outputting probability distributions.
  - `vision/`: Gemini multimodal models parsing uploaded chart screenshots for key levels and patterns.
  - `reviewer/`: Analytical critique pipeline reviewing strategy robustness.
  - `teacher/`: Plain-language explanation module breaking down payoff mechanics and Greeks.
  - `suggestor/`: Automated options structure generator operating on a configurable premium selling/buying allocation (default 60/40).

### 8. Research Workspace (`research/`)
- Dossier generator producing strategy performance reports, parameter sensitivity grids, and historical regime distributions.

---

## AI Review & Execution Pipeline

```
[User / Chart / AI Suggestor]
|
v
Strategy Draft (JSON DSL)
|
v
Validation Engine (AST & Institutional Mode Filters)
|
|      (If the user still wants to continue)
+-----------------------+-----------------------+
|                                               |
[Rejected]                                      [Approved]
|                                               |
v                                               +------------+------------+
Diagnostics & Failure Dossier                   |                         |
                                                v                         v
                                      AI Reviewer & Teacher      Strategy Compiler
                                      (Dossier & Explanations)            |
                                                                          v
                                                                Paper Broker Execution
                                                                (Runtime Risk Gates Checked)
```
