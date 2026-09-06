# Implementation Roadmap & Phase Milestones

## Phase 0: Repository Baseline, Tooling & Infrastructure Strategy
- Initialize Git repository and virtual environment (`python >= 3.11`)[cite: 2].
- Setup `pyproject.toml`, `ruff`, `mypy` (strict mode), and `pytest`.
- Provide `docker-compose.yml` for optional PostgreSQL and Redis services alongside default local SQLite/Parquet stores[cite: 2].
- Scaffold directory structure adhering strictly to `ARCHITECTURE.md`[cite: 1].
- Commit `.agents/skills/`, `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `SPEC.md`, and `DESIGN_LANGUAGE.md`[cite: 1, 2].
- Initialize database connectivity and establish Alembic migration baselines[cite: 2].

## Phase 1: Core Domain Entities & Order State Machine
- Implement immutable data contracts: `Bar`, `Signal`, `Position`, `AccountBalance`[cite: 2].
- Build formal Order State Machine:
  `CREATED` $\to$ `SUBMITTED` $\to$ `FILLED` | `PARTIALLY_FILLED` | `CANCELLED` | `REJECTED`
- Build `core/PaperBroker` tracking capital balances, dynamic margin allocations, and realistic fills[cite: 2].
- Implement realistic slippage algorithms, bid-ask spread simulation, and statutory Indian market taxes (STT, GST, Stamp Duty, Exchange Charges)[cite: 2].
- **Acceptance**: Deterministic unit tests verify that order states transition accurately and that commissions and margins are calculated correctly without network dependencies[cite: 2].

## Phase 2: Market Data Layer & Ingestion Pipeline
- Enforce strict exchange timestamping (`Asia/Kolkata`); prohibit system time in historical simulations[cite: 2].
- Implement `data/csv_feed.py` for deterministic point-in-time candle replay[cite: 2].
- Implement `broker-adapters`: Abstract adapter interface for authentication, session lifecycle management, contract metadata discovery, and historical OHLCV fetch (with Kotak Neo as the initial concrete implementation)[cite: 1, 2].
- Build WebSocket tick streamer (`DataFeedStreamer`) aggregating live ticks into 1m/5m immutable `Bar` events[cite: 2].
- Implement session controls: Clean halt/exit outside NSE market hours (09:15–15:30 IST)[cite: 2].
- **Acceptance**: Live WebSocket feeds and CSV historical files drive the runner loop through an identical consumer interface[cite: 2].

## Phase 3: Options Derivatives & Volatility Engine
- Implement `options/chain.py`: Aggregate normalized strike ladders, Open Interest, and expiry dates[cite: 2].
- Implement `options/iv.py`: Numerical Implied Volatility (IV) solver using Newton-Raphson / Brent's method derived from market premiums.
- Implement `options/greeks.py`: Black-Scholes pricing engine computing Delta, Gamma, Theta, and Vega[cite: 2].
- Implement `options/payoff.py`: Pure function computing at-expiry and mark-to-market payoff curves for multi-leg option strategies[cite: 2].
- **Acceptance**: Unit tests confirm IV convergence against market prices and verify Greeks and payoff bounds for Iron Condors and Straddles[cite: 2].

## Phase 4: Versioned Strategy DSL & Compiler Engine
- Define versioned declarative JSON AST schema (`schema_version: "1.0"`)[cite: 1].
- Build `strategy_compiler` to parse condition trees into stateless, executable state machines[cite: 1].
- Implement condition evaluators: Indicators, Time/Session, Greeks, Premium, OI, and Market Structure[cite: 1].
- Build `library/` registry with semantic versioning and Strategy DNA vector profiling[cite: 1, 2].
- **Acceptance**: Compiler transforms a versioned multi-leg DSL JSON document into an executable object without generating dynamic Python code[cite: 1, 2].

## Phase 5: Backtesting Engine & Anti-Overfitting Controls
- Build backtest runner with strict point-in-time isolation (zero future data leakage)[cite: 2].
- Support Walk-Forward Analysis and Out-of-Sample (Train/Test) split harnesses to prevent overfitting[cite: 1].
- Build `risk-engine`: Pre-trade margin gates, unhedged expiry-day gamma protection, and portfolio drawdown circuit breakers[cite: 1].
- Build `performance-metrics`: Calculate mathematical expectancy ($E$), Profit Factor ($PF$), Sharpe, Sortino, SQN, and Max Drawdown[cite: 1].
- **Acceptance**: Backtester simulates 1,000 bars with transaction costs, logging metrics and rejecting orders that breach margin thresholds[cite: 1, 2].

## Phase 6: Validation Engine & Instrument Search Subsystem (COMPLETE & SEALED ✅)
- Built tri-path validation architecture adhering to ADR 010:
  - `validation/ast/`: Static structural validation on JSON AST DSL prior to compilation.
  - `validation/institutional/historical.py`: Historical statistical validation for linear assets (Equities & Futures); requires backtest results; enforces positive mathematical expectancy ($E > 0$), timeframe-aware sample size floors, max drawdown, and temporal OOS disjointness (`min(oos) >= max(is)`). Air-gapped rejection of option strategies.
  - `validation/institutional/options_payoff.py`: Theoretical payoff curve and Greek risk validation for multi-leg option strategies; tagged `THEORETICAL_VALIDATION_ONLY`; slope boundary analysis, algebraic wing checks, unhedged tail risk veto, and deterministic evaluation timestamps.
- Implemented policy-based profiles: `InstitutionalPolicy`, `ModeratePolicy`, `ResearchPolicy`.
- High-Performance Instrument Search & Selection Subsystem: In-memory multi-index, hierarchical derivatives resolution, token lookups with cross-exchange disambiguation, deterministic multi-modal ranking, and zstd Parquet scrip caching.
- Remediated all 10 original adversarial audit findings (naked short put slope boundaries, query tokenizer ticker boundary regex, dynamic contract specs, structured query exclusivity, active vs. expired partition ranking, research policy profit factor gating, explicit futures symbol pattern matching, genuine OOS temporal disjointness, deterministic options evaluation time, cross-exchange token collision protection).
- Second-pass adversarial audit completed with zero Critical and zero High severity findings.
- Documented non-blocking limitations: multi-expiry theoretical options (single-expiry modeling) and missing-contract-spec fallback (lot size 1 for unindexed derivatives).
- Quality Verification: 233/233 unit/integration tests passing (100%), strict `mypy` clean across 120 files, `ruff` clean.
- Next Milestone: Phase 7 (AI Subsystems & Advisory Pipeline).

## Phase 7: AI Subsystems & Advisory Pipeline
- Abstract time-series models behind a vendor-agnostic `ForecastEngine` interface (Kronos, Chronos)[cite: 1, 2].
- Build Gemini Vision chart parser outputting technical patterns and key levels in validated JSON[cite: 1].
- Implement Strategy Suggestor enforcing configurable 60% selling / 40% buying bias[cite: 1].
- Strict Boundary: Treat AI model outputs as advisory only; all suggestions must pass through the Validation and Risk Engines[cite: 1].
- Build automated Research Dossier generator (`research/reports.py`)[cite: 1].
- **Acceptance**: Chart screenshot input produces verified JSON structures, pre-fills an option template, clears validation, and compiles a research dossier[cite: 1, 2].

## Phase 8: Multi-Page Plotly Dash UI & CLI Surface
- Implement Typer/Click CLI: `neopaper <noun> <verb>` command hierarchy[cite: 2].
- Build multi-page Plotly Dash interface (`/`, `/chain`, `/builder`, `/suggest`, `/runs`)[cite: 2].
- Implement targeted DOM updates via `dcc.Interval` against local storage stores[cite: 2].
- Connect interactive Strategy Builder to live payoff visualizers and validation gates[cite: 1, 2].
- **Acceptance**: Users can inspect live chains, stage legs in the Strategy Builder, pass Institutional validation, and trigger paper execution via the UI[cite: 1, 2].

## Phase 9: Production Hardening & Operational Resilience
- Implement structured contextual JSON logging across all engines (Loguru/structlog).
- Add automated daily database backup routines for SQLite/PostgreSQL stores.
- Implement rate-limiting, error circuit breakers, and connection retry wrappers on all network layers[cite: 1].
- Profile memory allocations and latency bottlenecks across tick aggregation and Greeks calculation loops.
- Run complete documentation audit verifying synchronization across all `.agents/skills/`[cite: 1, 2].
- **Acceptance**: System gracefully survives simulated network disconnections, recovers broker WebSocket sessions, and halts trading cleanly upon unhandled errors[cite: 1, 2].
