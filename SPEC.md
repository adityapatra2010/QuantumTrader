# System Specification & Execution Roadmap

## Core Operational Concepts
- **Live Paper-Trading ("Backtest" Primary Mode)**: Kotak Neo WebSocket tick stream feeds the strategy engine; simulated fills are executed by the local Paper Broker[cite: 2].
- **Historical File Replay (Secondary Mode)**: Replays stored CSV/Parquet market data through the identical strategy and broker pipeline for offline testing[cite: 2].
- **Institutional Strict Mode**: The system rejects strategies exhibiting negative expectancy, tail-risk gamma exposure, or insufficient trade sample sizes[cite: 1].

---

## Core Data Schemas

| Model | Attributes | Purpose |
|---|---|---|
| `Tick` | `symbol, ltp, bid, ask, volume, oi, timestamp` | Live WebSocket tick packet |
| `Bar` | `timestamp, open, high, low, close, volume, oi` | Standard aggregated candle representation |
| `Signal` | `timestamp, symbol, direction (BUY/SELL/HOLD), confidence, metadata` | Strategy output directive |
| `Order` | `order_id, signal_id, symbol, side, order_type, qty, price, status, created_at, updated_at` | Formal broker order with state machine tracking |
| `Trade` | `trade_id, order_id, symbol, side, qty, fill_price, slippage, stt, charges, timestamp` | Executed fill ledger record |
| `Position` | `symbol, qty, buy_avg_price, sell_avg_price, realized_pnl, unrealized_pnl, updated_at` | Net portfolio position record |
| `AccountBalance` | `total_capital, available_margin, used_margin, realized_pnl, unrealized_pnl` | Real-time capital and margin state |
| `OptionLeg` | `underlying, expiry, strike, option_type (CE/PE), side (BUY/SELL), qty, entry_price` | Single options contract component |
| `OptionStrategy` | `id, name, legs: list[OptionLeg], dna_tags, created_at` | Composite multi-leg option structure |
| `ChainRow` | `strike, expiry, call: {ltp, oi, iv, greeks}, put: {ltp, oi, iv, greeks}` | Option chain grid row |
| `PayoffPoint` | `underlying_price, pnl_at_expiry, pnl_mark_to_market` | Curve coordinates for payoff visualizer |
| `ValidationResult` | `validation_score (0-100), status (APPROVED/NOT_RECOMMENDED/REJECTED), metrics: dict, rejection_reasons: list[str], suggested_improvements: list[str]` | Pre-trade risk audit output |
| `ForecastResult` | `timestamps[], predicted_close[], predicted_high[], predicted_low[], confidence_spread` | Probabilistic time-series output |

---

## Architecture Subsystem Clarification: Validation vs. Risk

To prevent boundary ambiguity, the system establishes a strict boundary between pre-trade verification and real-time execution risk gates:

1. **`validation/` (Application Services Layer)**:
   - `validation/ast/`: Static verification of declarative JSON DSL trees prior to compilation (schema conformance, valid strike offsets, allowed operators, leg balance).
   - `validation/institutional/`: Statistical gatekeeping on historical backtest runs or forward simulated sessions (verifies mathematical expectancy $E > 0$, Profit Factor $PF \ge 1.3$, sample size $N \ge 300$, maximum drawdown limits).
2. **`risk/` (Domain Core / Execution Layer)**:
   - Real-time, inline execution gates inside `core/PaperBroker` evaluating every simulated order at fill-time.
   - Modules enforce: pre-trade margin utilization threshold ($\le 85\%$), gamma explosion checks near expiry ($DTE \le 1$), unhedged naked short wing bans, and intraday circuit breakers ($5\%$ portfolio drawdown triggering emergency halt).

---

## CLI Command Interface

The CLI executable entry point is `aditrader` (with `neopaper` retained as an alias):

| Command | Action |
|---|---|
| `aditrader backtest run --symbol <S> [--source live\|file]` | Start paper-trading session using live feed or CSV replay |
| `aditrader options chain --symbol <S> --expiry <D>` | Display live options chain with computed Greeks |
| `aditrader strategy validate --file <PATH>` | Run strategy through AST and Institutional Mode filters |
| `aditrader suggest --symbol <S> [--bias 60:40]` | Generate options structures based on current regime |
| `aditrader research generate --run-id <ID>` | Build comprehensive Markdown/HTML research dossier |
| `aditrader dashboard` | Launch the Plotly Dash multi-page server |

---

## Phase Roadmap

### Phase 0: Repository Baseline, Tooling & Infrastructure Strategy
- Initialize Git repository and virtual environment (`python >= 3.11`).
- Setup `pyproject.toml`, `ruff`, `mypy` (strict mode), and `pytest`.
- Provide `docker-compose.yml` for optional PostgreSQL and Redis services alongside default local SQLite/Parquet stores.
- Scaffold directory structure adhering strictly to `ARCHITECTURE.md`.
- Commit `.agents/skills/`, `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `SPEC.md`, and `DESIGN_LANGUAGE.md`.
- Initialize database connectivity and establish Alembic migration baselines (empty initial migration).
- **Acceptance**: `pytest` baseline run passes with 0 failures, `ruff` and `mypy` pass with 0 errors.

### Phase 1: Core Domain Entities & Order State Machine
- Implement immutable data contracts: `Tick`, `Bar`, `Signal`, `Order`, `Trade`, `Position`, `AccountBalance`.
- Build formal Order State Machine:
  `CREATED` $\to$ `SUBMITTED` $\to$ `FILLED` | `PARTIALLY_FILLED` | `CANCELLED` | `REJECTED`
- Build `core/PaperBroker` tracking capital balances, dynamic margin allocations, and realistic fills.
- Implement realistic slippage algorithms, bid-ask spread simulation, and statutory Indian market taxes (STT, GST, Stamp Duty, Exchange Charges).
- **Acceptance**: Deterministic unit tests verify that order states transition accurately and that commissions and margins are calculated correctly without network dependencies.

### Phase 2: Market Data Layer & Ingestion Pipeline
- Enforce strict exchange timestamping (`Asia/Kolkata`); prohibit system time in historical simulations.
- Implement `data/csv_feed.py` for deterministic point-in-time candle replay.
- Implement `broker-adapters`: Abstract adapter interface for authentication, session lifecycle management, contract metadata discovery, and historical OHLCV fetch (with Kotak Neo as the initial concrete implementation).
- Build WebSocket tick streamer (`DataFeedStreamer`) aggregating live ticks into 1m/5m immutable `Bar` events with thread-safe ring buffering.
- Implement session controls: Clean halt/exit outside NSE market hours (09:15–15:30 IST).
- **Acceptance**: Live WebSocket feeds and CSV historical files drive the runner loop through an identical consumer interface.

### Phase 3: Options Derivatives & Volatility Engine
- Implement `options/chain.py`: Aggregate normalized strike ladders, Open Interest, and expiry dates dynamically from scrip master.
- Implement `options/iv.py`: Numerical Implied Volatility (IV) solver using Newton-Raphson / Brent's method derived from market premiums.
- Implement `options/greeks.py`: Black-Scholes pricing engine computing Delta, Gamma, Theta, and Vega.
- Implement `options/payoff.py`: Pure function computing at-expiry and mark-to-market payoff curves for multi-leg option strategies.
- **Acceptance**: Unit tests confirm IV convergence against market prices and verify Greeks and payoff bounds for Iron Condors and Straddles.

### Phase 4: Versioned Strategy DSL & Compiler Engine
- Define versioned declarative JSON AST schema (`schema_version: "1.0"`).
- Build `strategy_compiler` to parse condition trees into stateless, executable state machines (`on_bar(history: list[Bar]) -> Optional[Signal]`).
- Implement condition evaluators: Indicators, Time/Session, Greeks, Premium, OI, and Market Structure (strictly using declarative AST operators; dynamic code execution prohibited per ADR 007).
- Build `library/` registry with semantic versioning and Strategy DNA vector profiling.
- **Acceptance**: Compiler transforms a versioned multi-leg DSL JSON document into an executable object without generating dynamic Python code.

### Phase 5: Backtesting Engine & Anti-Overfitting Controls
- Build backtest runner with strict point-in-time isolation (zero future data leakage).
- Support Walk-Forward Analysis and Out-of-Sample (Train/Test) split harnesses to prevent overfitting.
- Build `risk-engine`: Pre-trade margin gates, unhedged expiry-day gamma protection, and portfolio drawdown circuit breakers.
- Build `performance-metrics`: Calculate mathematical expectancy ($E$), Profit Factor ($PF$), Sharpe, Sortino, SQN, and Max Drawdown.
- **Acceptance**: Backtester simulates 1,000 bars with transaction costs, logging metrics and rejecting orders that breach margin thresholds.

### Phase 6: Validation Engine (Policy-Based "Institutional Mode")
- Build `validation/` rule modules:
  - `validation/ast/`: Static schema and leg structure checks.
  - `validation/institutional/`: `expectancy.py`, `pop.py`, `drawdown.py`, `sample_size.py`, `gamma_risk.py`.
- Implement policy-based validation profiles (`Institutional` as default, `Moderate`, `Beginner`).
- Programmatic Veto: Automatically reject strategies failing positive expectancy, drawdown tolerances, or minimum sample sizes.
- **Acceptance**: Test suite verifies that negative expectancy strategies or unhedged short options near expiry are programmatically rejected.

### Phase 7: AI Subsystems & Advisory Pipeline
- Abstract time-series models behind a vendor-agnostic `ForecastEngine` interface (Kronos, Chronos).
- Build Gemini Vision chart parser outputting technical patterns and key levels in validated JSON.
- Implement Strategy Suggestor enforcing configurable 60% selling / 40% buying bias.
- Strict Boundary: Treat AI model outputs as advisory only; all suggestions must pass through the Validation and Risk Engines.
- Build automated Research Dossier generator (`research/reports.py`).
- **Acceptance**: Chart screenshot input produces verified JSON structures, pre-fills an option template, clears validation, and compiles a research dossier.

### Phase 8: Multi-Page Plotly Dash UI & CLI Surface
- Implement Click/Typer CLI: `aditrader <noun> <verb>` command hierarchy.
- Build multi-page Plotly Dash interface (`/`, `/chain`, `/builder`, `/suggest`, `/runs`) utilizing `dash.register_page`.
- Implement targeted DOM updates via `dcc.Interval` reading from in-memory cache and SQLite WAL store (ADR 008).
- Connect interactive Strategy Builder to live payoff visualizers and validation gates.
- **Acceptance**: Users can inspect live chains, stage legs in the Strategy Builder, pass Institutional validation, and trigger paper execution via the UI.

### Phase 9: Production Hardening & Operational Resilience
- Implement structured contextual JSON logging across all engines (Loguru/structlog).
- Add automated daily database backup routines for SQLite/PostgreSQL stores.
- Implement rate-limiting, error circuit breakers, and connection retry wrappers on all network layers.
- Profile memory allocations and latency bottlenecks across tick aggregation and Greeks calculation loops.
- Run complete documentation audit verifying synchronization across all `.agents/skills/`.
- **Acceptance**: System gracefully survives simulated network disconnections, recovers broker WebSocket sessions, and halts trading cleanly upon unhandled errors.
