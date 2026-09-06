# Present Stage & Execution State

**Last Updated**: 2026-09-06 18:10 IST  
**Current Phase**: Phase 5.6 — COMPLETE & AUDITED ✅ | Preparing Phase 6 (Validation Engine & Institutional Mode)  
**Last Verified By**: AGY CLI Phase 5.6 Research Integrity Suite (Ruff, Mypy Strict, Pytest 150/150)  

---

## Repository State

- **Branch**: `main`
- **Working Tree**: Core domain entities, order state machine, paper broker with net equity accounting, local SQLite ledger persistence, market data feeds, Kotak Neo adapter, Parquet cache, Black-Scholes Greeks engine, numerical IV solver, dynamic option chain ladders, multi-leg payoff engine, versioned JSON AST DSL, static indicators, category condition evaluators, deterministic strategy compiler, Strategy DNA profiler, institutional templates, version-controlled strategy registry, deterministic backtesting engine with options air-gap guards and volume participation constraints, walk-forward analysis & OOS splitters, hardened pre-trade risk engine with lot-aware position limits and session-boundary resets, finite performance analytics with strict timeframe resolution, and options backtesting boundary placeholders implemented and verified.

---

## Active Implementation Rules

Until Phase 6 sign-off:
- **Do not implement live broker order routing** (strictly air-gapped; read-only market data feeds only).
- **Do not execute raw dynamic code** (`eval()`, `exec()`, or dynamic python code generation).
- **Do not implement validation policy rules or institutional rejection filters** (Phase 6).
- **Do not integrate AI forecasting or vision modules** (Phases 6 & 7).
- **Do not construct Plotly Dash dashboards or interactive CLI handlers** (Phase 8).
- **Do not modify architecture or contracts** without proposing an ADR update in `DECISIONS.md`.
- **Maintain strict Python 3.11 target compatibility** across all typing, syntax, and libraries.

---

## Architecture Status

- **Documentation**: `██████████` 100%
- **Implementation**: `███████░░░` 68% (Phases 0, 1, 2, 3, 4, 5, 5.5, and 5.6 Complete)

---

## Next Milestone

### Phase 6: Strategy Validation Engine & Institutional Mode
**Definition of Done**:
- Implement institutional mode validation rules:
  - Positive mathematical expectancy gate ($E > 0$).
  - Drawdown tolerance limits (Max Drawdown $\le 15\%$).
  - Sample size significance checks ($N \ge 30$ trades).
  - Unhedged tail risk / naked short gamma explosion veto.
- Reject strategies failing validation; tag approved strategies for paper trading.
- Generate structured validation dossiers with diagnostic logs.

---

## Current Decisions Active

- Strict paper-trading isolation: order placement logic is barred from broker adapters (ADR 002).
- Declarative JSON DSL trees for all strategies; raw Python code generation is prohibited (ADR 001, ADR 007).
- Mandatory Institutional Validation gate: unhedged gamma risk or negative expectancy triggers a veto (ADR 004).
- All AI model outputs (Kronos, Gemini Vision) remain purely advisory and cannot place trades (ADR 005).
- Plotly Dash multi-page architecture chosen for quantitative research over client-side frameworks (ADR 003).
- SQLite WAL mode and in-memory ring buffer for low-latency concurrency (ADR 008).
- Dynamic contract expiry discovery from broker scrip master (ADR 009).
- Simulation integrity, portfolio net equity accounting & timeframe annualization (ADR 010).
- Research integrity hardening: options air-gap, volume realism, session risk & finite metrics (ADR 011).

---

## Completed

### Phase 5.6: Research Integrity Hardening & Adversarial Defenses
**Status**: COMPLETE & AUDITED ✅
- **Options Simulation Air-Gap (`backtesting.runner`, `backtesting.options`)**: `BacktestRunner` inspects `strategy.dsl.legs` and raises `UnsupportedStrategyError` when strategies define option legs. Eliminates deceptive proxy execution of multi-leg derivatives on spot/futures candle series. Regression-verified with Iron Condor and Long Straddle templates.
- **Liquidity & Volume Participation Constraints (`backtesting.runner`)**: Added `max_volume_participation_pct` (e.g., 10% of candle volume) and `volume_limit_action` (`REJECT` vs. `PARTIAL_FILL`) to `BacktestConfig`. Prevents unrealistic fills during thin liquidity bars.
- **Intraday Session Boundary & Circuit Breaker Reset (`core.risk.engine`, `backtesting.runner`)**: `BacktestRunner` tracks date transitions and executes `risk_engine.on_session_start(timestamp, current_equity)` to reset session starting/peak equity and clear intraday drawdown halts without erasing cumulative portfolio equity history.
- **Terminal Open-Position Accounting (`backtesting.runner`)**: Added `terminal_positions`, mark-to-market `terminal_unrealized_pnl`, and conservative `liquidated_ending_equity` (evaluating full slippage and statutory exit charges) to `BacktestResult`. Avoids injecting artificial exit trades into roundtrip trade performance statistics.
- **Finite Statistical Metrics & Timeframe Strictness (`backtesting.analytics.metrics`)**: Replaced `float('inf')` with `None` for zero downside volatility (Sortino), zero gross losses (Profit Factor), zero return variance or sample size $N < 2$ (Sharpe/SQN). Extended `resolve_periods_per_year` to support second-level intervals (`1s`, `30s`) and strict error checking mode (`strict=True`).
- **Derivative Contract Lot Semantics (`core.risk.engine`)**: Enhanced `RiskEngine.validate_order` Gate 4 with `resolve_lots(symbol, qty, default_lot_size)`, accurately converting contract quantities into integer lot counts (e.g. NIFTY 25 shares/lot, RELIANCE 250 shares/lot) against `max_concurrent_lots`.
- **Automated Verification**:
  - `ruff check .` and `ruff format --check .` passing with 0 warnings/errors (Python 3.11 target).
  - `mypy src tests` passing in strict mode across 102 source files with 0 errors (Python 3.11 target).
  - `pytest` suite passing 150/150 unit and integration tests (100% pass rate in 2.17s) with 87% overall coverage.


### Phase 5.5: Simulation Integrity Hardening & Post-Red-Team Remediation
**Status**: COMPLETE & AUDITED ✅
- **Portfolio Equity Net Accounting (`core.broker`)**: Locked `PaperBroker.get_account_balance()` where equity strictly equals `cash_balance + sum(pos.qty * ltp)`. Long positions contribute positive holdings value; short positions contribute negative liability offset by short cash turnover. Eliminates phantom capital and double counting of gains. Verified with 5 explicit regression scenarios.
- **Risk Engine Position Reversal Hardening (`core.risk.engine`)**: Differentiated pure closing orders (`qty <= abs(existing_qty)`) from reversals (`qty > abs(existing_qty)`). Reversal excess is partitioned as new exposure, properly releasing margin from closed positions and enforcing circuit breaker halts, margin utilization ceiling, and lot limit gates.
- **Dynamic Timeframe Frequency Scaling (`backtesting.analytics.metrics`)**: Implemented `resolve_periods_per_year` mapping timeframes to annual periods based on the 375-minute regular NSE session (1m: 94,500, 5m: 18,900, 15m: 6,300, 1h: 1,575, 1d: 252). `BacktestConfig.periods_per_year` defaults to `None`, dynamically scaling Sharpe and Sortino ratios based on the strategy's declared timeframe.
- **Options Backtesting Boundary Placeholder (`backtesting.options`)**: Documented the underlying candle execution boundary and provided `OptionsBacktestRunner` and `OptionsBacktestConfig` placeholders raising `NotImplementedError` until dedicated option-chain feeds and synthetic IV surface modeling arrive in Phase 7/8.
- **Automated Verification**:
  - `ruff check .` and `ruff format --check .` passing with 0 warnings/errors (Python 3.11 target).
  - `mypy src tests` passing in strict mode across all source files with 0 errors (Python 3.11 target).
  - `pytest` suite passing 136/136 unit and integration tests (100% pass rate).

### Phase 5: Backtesting Engine & Anti-Overfitting Controls
**Status**: COMPLETE & AUDITED ✅
- **Deterministic Backtest Orchestrator (`backtesting.runner`)**: `BacktestRunner`, `BacktestConfig`, and `BacktestResult` connecting `DataFeed` / `list[Bar]` $\to$ `ExecutableStrategy` $\to$ `RiskEngine` $\to$ `PaperBroker`. Enforces strict point-in-time isolation with default anti-lookahead execution timing (signal generated at Bar $T$ close, filled at Bar $T+1$ open with slippage) and optional configurable same-bar execution. Accurately tracks signals, orders, fills, and mark-to-market equity curves with FIFO roundtrip PnL matching.
- **Pre-Trade Risk Engine (`core.risk`)**: `RiskEngine`, `RiskLimits`, `RiskCheckResult`, and `RiskRejectionReason` providing an independent pre-trade barrier. Enforces 85% margin utilization ceiling, intraday 5% portfolio drawdown circuit breaker (with exemptions for position-reducing/closing orders), unhedged expiry-day gamma protection, and concurrent position limits.
- **Anti-Overfitting Data Splitters (`backtesting.splitters`)**: Chronological train/test splitters (`split_train_test`, `split_out_of_sample`) and Walk-Forward Analysis (`generate_walk_forward_windows`) supporting both rolling and expanding/anchored windows, guaranteeing strictly non-overlapping timestamp windows (`train[-1].timestamp < test[0].timestamp`).
- **Institutional Performance Analytics (`backtesting.analytics.metrics` & `analytics.metrics`)**: Closed-form quantitative metric calculators for mathematical expectancy ($E$), profit factor ($PF$), maximum peak-to-trough drawdown (amount and percentage), annualized Sharpe ratio, Sortino ratio, and System Quality Number (SQN), producing comprehensive `PerformanceReport` summaries.
- **Automated Verification**:
  - `ruff check .` and `ruff format --check .` passing with 0 warnings/errors (Python 3.11 target).
  - `mypy src tests` passing in strict mode across 101 source files with 0 errors (Python 3.11 target).
  - `pytest` suite passing 126/126 unit and integration tests (100% pass rate in 1.45s).

### Phase 4: Versioned Strategy DSL & Compiler Engine
**Status**: COMPLETE & AUDITED ✅
- **Versioned JSON AST Schema (`strategy.builder.schema`)**: Pydantic v2 frozen schema pinned to `schema_version: "1.0"` (ADR 001). Supported comparison operators (`GREATER_THAN`, `LESS_THAN`, `EQUALS`, `WITHIN_RANGE`, `CROSSES_ABOVE`, `CROSSES_BELOW`, `MATCHES_REGIME`), composite combinators (`AND`, `OR`, `NOT`), condition categories (`indicator`, `time`, `greeks`, `premium`, `open_interest`, `market_structure`, `regime`), and option leg definitions.
- **Pure Indicator Library (`strategy.compiler.indicators`)**: Statically registered, pure-function technical indicators (`SMA`, `EMA`, `RSI`, `ATR`, `BollingerBands`, `Supertrend`) with zero dynamic code execution (ADR 007) and strict numerical accuracy.
- **Static AST Evaluators (`strategy.compiler.evaluators`)**: Multi-category condition evaluators evaluating bar history, technical crossover events, time-of-day windows, option Greek sensitivities, premium decay percentages, and open interest / PCR without script interpretation.
- **Deterministic Strategy State Machine (`strategy.compiler.engine`)**: `ExecutableStrategy` implementing stateless `on_bar(history: list[Bar]) -> Signal | None` contract, emitting standard `Signal` directives with zero order routing capabilities (ADR 002).
- **Strategy DNA Profiling (`strategy.library.dna`)**: Multi-dimensional vector profiler calculating Directionality (strike-weighted delta proxy), Theta Exposure, Vega Risk, Gamma Risk (uncovered short option detection), Margin Efficiency, Style, and Target Regime.
- **Institutional Option Templates (`strategy.library.templates`)**: Built-in production templates for Nifty Weekly Iron Condor, Nifty Long Straddle, and Nifty Bull Call Spread.
- **Version-Controlled Catalog (`strategy.library.registry`)**: Thread-safe `StrategyRegistry` with strict version immutability (overwriting existing versions raises `StrategyVersionExistsError`), ID and Name lookups, and multi-criteria DNA filtering.
- **Automated Verification**:
  - `ruff check .` passing with 0 warnings/errors (Python 3.11 target).
  - `mypy src tests` passing in strict mode across 89 source files with 0 errors (Python 3.11 target).
  - `pytest` suite passing 102/102 unit tests (100% pass rate in 0.99s).

### Phase 3: Options Derivatives & Volatility Engine
**Status**: COMPLETE ✅
- **Closed-Form Black-Scholes Greeks Engine**: `options.greeks` calculating Delta, Gamma, Theta (1-calendar-day and 1-trading-day), Vega (per 1% vol), and Rho (per 1% rate) with verified parity and expiration boundary handling.
- **Robust Numerical IV Solver**: `options.iv` implementing hybrid Newton-Raphson (using analytical Vega derivative) and Bisection fallback spanning [0.1%, 500%] volatility with explicit tolerances (`IV_SOLVER_CONVERGENCE_TOLERANCE = 1e-5`, `IV_PRICE_TOLERANCE = 0.01 INR`), enforcing European exercise convention and no-arbitrage bounds.
- **Dynamic Strike Ladder & Expiry Discovery**: `options.chain` (`OptionChainEngine`) mapping scrip master contracts (`ContractMetadata`) into structured `ChainRow` ladders, resolving At-The-Money (ATM) strikes dynamically, preserving exchange lot sizes, and evaluating live Greeks per strike.
- **Pure Multi-Leg Payoff Engine**: `options.payoff` evaluating at-expiry P&L curves, multi-DTE mark-to-market curves, exact breakevens via linear root interpolation (`PAYOFF_INTERPOLATION_TOLERANCE = 0.01 INR`), max profit, max loss, and net debit/credit.
- **Analytical Benchmark Verification**: Unit tests verify Black-Scholes prices and Greeks against published analytical benchmark figures (Hull textbook standards) within `1e-4` precision.
- **Automated Verification**:
  - `ruff check .` passing with 0 warnings/errors (Python 3.11 target).
  - `mypy src tests` passing in strict mode across 75 source files with 0 errors (Python 3.11 target).
  - `pytest` suite passing 75/75 unit tests (100% pass rate in 0.96s).

### Phase 2: Market Data Layer & Ingestion Pipeline
**Status**: COMPLETE ✅
- **Strict Exchange Timestamping (`Asia/Kolkata`)**: `data.session` module normalizing naive/aware datetimes, validating NSE regular hours (09:15–15:30 IST), pre-open, post-market, weekends, and standard NSE holidays.
- **Deterministic Historical CSV Replay**: `data.feeds.csv_feed` (`CSVDataFeed` and `data.csv_feed` alias) reading point-in-time CSV files, enforcing chronological ordering, deduplicating identical timestamps, and optional market hours filtering.
- **Deterministic Synthetic Data Generator**: `data.feeds.synthetic_feed` (`SyntheticDataFeed`) with seeded random walk generation for offline deterministic testing, bounded OHLCV candles, and intermediate tick generation.
- **Abstract Broker Adapter Interface**: `data.adapters.base` (`AbstractBrokerAdapter` and `ContractMetadata`) enforcing read-only boundary and security veto against real order routing (ADR 002).
- **Concrete Kotak Neo Adapter**: `data.adapters.kotak_neo` (`KotakNeoAdapter`) providing authentication, scrip master CSV row parsing into `ContractMetadata`, tick subscription management, and offline/mock test mode.
- **Tick Aggregator & Ring Buffer**: `data.feeds.aggregator` with thread-safe `RingBuffer[T]` (ADR 008) avoiding unbounded memory growth and `TickAggregator` rolling up streaming ticks into immutable 1m/5m `Bar` events.
- **Local Columnar Cache**: `data.cache` (`LocalDataCache`) providing high-throughput local Parquet serialization and deserialization for bars and ticks with timestamp window filtering.
- **Streamer Orchestrator**: `data.feeds.streamer` (`DataFeedStreamer`) providing a unified consumer interface driving runner loops identically across live feeds and historical files.
- **Automated Verification**:
  - `ruff check .` passing with 0 warnings/errors (Python 3.11 target).
  - `mypy src tests` passing in strict mode across 65 source files with 0 errors (Python 3.11 target).
  - `pytest` suite passing 55/55 unit tests (100% pass rate).

### Phase 1: Core Domain Entities & Order State Machine (Audited)
**Status**: COMPLETE & AUDITED ✅
- **Immutable Domain Entities**: `Tick`, `Bar`, `Signal`, `Order`, `Trade`, `Position`, `AccountBalance` implemented with frozen Pydantic models, runtime invariant validations, and price envelope checks.
- **Formal Order State Machine**: `OrderStateMachine` implementing strictly allowed lifecycle transitions (`CREATED` $\to$ `SUBMITTED` $\to$ `FILLED` | `PARTIALLY_FILLED` | `CANCELLED` | `REJECTED`), blocking illegal backwards/terminal transitions with `InvalidOrderStateTransitionError`.
- **Cost & Slippage Calculators**: `CostCalculator` calculating statutory Indian equity/derivative taxes (STT, Exchange turnover charges, GST, SEBI turnover fees, Stamp duty) and `SlippageModel` (linear basis points + half-spread modeling).
- **Core PaperBroker Engine**: `PaperBroker` managing virtual cash balances, dynamic margin allocations with an 85% safety ceiling, position lot tracking, realized P&L, MTM unrealized P&L, limit order matching, and signal ingestion.
- **Audited Position Accounting**: Verified with dedicated unit tests:
  - Partial fills and progressive multi-fill execution on single orders.
  - Partial position reduction preserving entry price of remaining lots.
  - Position reversals (Long to Short flipping) with correct entry price resets and P&L attribution.
  - Strict separation of realized P&L vs MTM unrealized P&L across all states.
- **Architectural Boundary Verification**:
  - Confirmed 0 imports in `core/` from `data/`, `ai/`, `ui/`, or broker SDKs.
  - Confirmed air-gapped execution: `PaperBroker` has zero network or routing capabilities.
- **Bidirectional Migration Verification**:
  - `alembic upgrade head` $\to$ `alembic downgrade -1` $\to$ `alembic upgrade head` verified clean.
- **Local Ledger Persistence**: SQLAlchemy ORM models (`OrderRecord`, `TradeRecord`, `PositionRecord`, `AccountBalanceRecord`) managed through `LedgerRepository` using SQLite in WAL mode (`PRAGMA journal_mode=WAL`).
- **Automated Verification**:
  - `ruff check .` passing with 0 warnings/errors (Python 3.11 target).
  - `mypy src tests` passing in strict mode across 48 source files with 0 errors (Python 3.11 target).
  - `pytest` suite passing 30/30 unit tests (100% pass rate).

### Phase 0: Repository Baseline, Tooling & Infrastructure Strategy
**Status**: COMPLETE ✅
- Git repository initialized and virtual environment configured (`python 3.14`).
- `pyproject.toml` created with pinned dependencies, strict `mypy`, `ruff`, and `pytest`.
- 4-layer directory skeleton scaffolded strictly adhering to `ARCHITECTURE.md`.
- `docker-compose.yml` configured for optional PostgreSQL and Redis services.
- Database connectivity initialized with Alembic baseline migration (`0001_baseline.py` head verified).
- Baseline `pytest` suite executed with 6/6 tests passing (0 failures).
- `ruff check .` passing with 0 errors.
- `mypy src tests` passing with 0 errors (strict mode).
- Centralized `Settings` configuration model with `.env.example` template.

### Documentation Foundation
**Status**: COMPLETE ✅
- `AGENTS.md`: Agent directives, reading order, and absolute guardrails.
- `ARCHITECTURE.md`: Subsystem boundaries, decoupling contracts, and data-flow diagrams.
- `SPEC.md`: Data models, CLI signatures, and 10-phase functional requirements.
- `DESIGN_LANGUAGE.md`: Plotly Dash visual layout, typography, theme, and callbacks.
- `DECISIONS.md`: ADRs 001 through 009 capturing all system trade-offs.
- `ROADMAP.md`: Sequenced execution phases from Phase 0 to Phase 9.

### Agent Skills (.agents/skills/)
**Status**: COMPLETE ✅ (26/26 defined)
- Core: `architecture`, `coding-standards`, `testing`, `database-design`, `api-design`, `security`.
- Market & Data: `indian-market-rules`, `market-regimes`, `data-pipeline`, `broker-adapters`.
- Trading Engines: `options-engine`, `risk-engine`, `backtesting-engine`, `paper-broker`.
- Strategy & Validation: `strategy-builder`, `strategy-compiler`, `strategy-suggestor`, `strategy-library`, `validation-engine`.
- AI Subsystems: `ai-prompting`, `ai-agent-orchestration`, `forecast-models`, `gemini-vision`.
- Analytics & UI: `performance-metrics`, `research-workspace`, `dashboard-ui`.

---

## Current Work

**Status**: PHASE 5 COMPLETE & AUDITED ✅ — AWAITING USER SIGN-OFF TO BEGIN PHASE 6

Pending Action Items:
1. Commit and push Phase 5 implementation (`feat(phase-5): implement backtesting engine and anti-overfitting controls`).
2. Await explicit user sign-off to proceed with Phase 6 (Strategy Validation Engine & Institutional Mode).

---

## Not Implemented Yet (Do NOT Hallucinate)

The following components do **NOT** exist in code:
- No validation rules, expectancy filters, or institutional veto gates (`validation/`)
- No AI forecasting models, vision parsers, or reviewer modules (`ai/`)
- No Plotly Dash web interface or CLI entry points (`ui/`, `cli/`)
