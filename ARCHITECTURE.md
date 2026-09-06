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
|                         Advisory Services Layer                       |
|   AI Subsystems: Suggestor | Vision | Reviewer | Teacher | Forecast   |
|   (Strictly non-authoritative proposals carrying ProvenanceRecord)    |
+-----------------------------------+-----------------------------------+
|
v
+-----------------------------------------------------------------------+
|                          Application Services                         |
|   Strategy Validation Engine (Authoritative Veto) | Backtest Runner   |
|   Strategy Registry | Research Dossier Generator | Instrument Search  |
+-----------------------------------+-----------------------------------+
|
v
+-----------------------------------------------------------------------+
|                          Domain Core & Options                        |
|   Options Engine (Chain/Greeks/Payoffs)    |    Paper Broker Engine   |
|   Strategy Compiler | Strategy DNA         |    Runtime Risk Engine   |
+-----------------------------------+-----------------------------------+
|
v
+-----------------------------------------------------------------------+
|                      Infrastructure & Adapters                        |
|   Broker Adapters (Kotak Neo)      |   Local SQLite Ledger (WAL)      |
|   Parquet Scrip/Bar Cache          |   In-Memory Ring Buffers         |
|   External Model API Adapters (Kronos / Gemini SDKs - pure connectors)|
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

### 7. AI Advisory Services Layer (`ai/`)
- Pure advisory layer producing non-authoritative proposals (`SuggestionResult`, `VisionResult`, `ForecastResult`).
- Encapsulates machine learning models behind swappable, abstract interfaces (`base.py`):
  - `forecasting/`: Probabilistic time-series trajectory forecasting (`ForecastEngine`) with strict anti-lookahead validation.
  - `vision/`: Multimodal chart screenshot extraction (`VisionEngine`) detecting observable support/resistance and patterns.
  - `suggestor/`: Automated options structure generator (`StrategySuggestor`) operating on transparent, configurable premium selling/buying allocation (`BiasCfg`, default 60/40).
  - `reviewer/`: Analytical critique pipeline (`StrategyReviewer`) reviewing strategy robustness and explaining failure modes.
  - `teacher/`: Plain-language explanation module breaking down payoff mechanics and Greeks without offering speculative financial advice.
- Strict Architectural Guardrails:
  - Every AI output must carry an immutable `ProvenanceRecord` with a 64-char SHA-256 `input_hash` (ADR 012).
  - Zero authority to bypass, soften, or alter deterministic validation gates (`StrategyValidationService`).
  - Zero live broker order placement or execution capabilities.
  - Complete degraded-mode operation when AI providers are unavailable (ADR 012).

### 8. Research Workspace (`research/`)
- Dossier generator producing comprehensive quantitative strategy dossiers (`ResearchDossier`).
- Strict evidence segregation: distinguishes `DETERMINISTIC` backtest metrics and payoff math from `AI_ADVISORY` model outputs (ADR 012).
- Mandates institutional compliance disclaimers on all advisory content.

---

## AI Review & Execution Pipeline

```
[Uploaded Chart Image]            [Historical Bars]              [Market Regime]
         │                               │                              │
         ▼                               ▼                              ▼
    VisionEngine                  ForecastEngine                 Regime Classifier
    (Observable                     (Probabilistic                     │
     Patterns)                       Trajectory)                       │
         │                               │                             │
         ▼                               ▼                             │
    VisionResult                  ForecastResult                       │
         └───────────────┬───────────────┘                             │
                         │                                             │
                         ▼                                             ▼
                 StrategySuggestor ◄───────────────────────────────────┘
                 (Configurable BiasCfg e.g. 60/40)
                         │
                         ▼
                  SuggestionResult
                  (Declarative StrategyDSL + ProvenanceRecord)
                         │
                         ▼
         Authoritative Strategy Validation Service
         (AST Structural Gate + Institutional Statistical Gate / Options Payoff)
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
   [REJECTED]                        [APPROVED]
        │                                 │
        ▼                                 ▼
   Diagnostics Dossier             Research Dossier Generator
   (Failure Analysis)              (DossierSection: DETERMINISTIC vs. AI_ADVISORY)
                                          │
                                          ▼
                                   Human Reviewer
                                   (User must explicitly review and trigger)
                                          │
                                          ▼
                                 Paper Broker Execution
                                 (Runtime Risk Engine Pre-Trade Gates Checked)
```

