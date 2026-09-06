name: Dashboard UI
description: Plotly Dash multi-page architecture, callback patterns, design system tokens, and state isolation.

# Goal
Provide high-performance, institutional-grade quantitative research visualization using Plotly Dash without embedding business logic or executing raw trades directly from UI handlers (ADR 003, ADR 008).

# Multi-Page Architecture
- Standardize on Plotly Dash native multi-page routing via `dash.register_page` inside `src/aditrader/ui/pages/`.
- Routes:
  - `/` (`portfolio.py`): Real-time portfolio state, net Greeks, grouped multi-leg positions grid, capital gauges.
  - `/chain` (`options_chain.py`): Interactive strike ladder (Calls/Puts) with ATM anchor, LTP, OI, IV, Delta, Theta.
  - `/builder` (`strategy_builder.py`): Multi-leg staging table, interactive Plotly payoff canvas (expiry + MTM), pre-trade validation gate.
  - `/suggest` (`strategy_suggestor.py`): Regime banner, selling/buying allocation bias slider, pre-filled option template cards.
  - `/runs` (`research_runs.py`): Historical simulation runs, Sharpe/drawdown stats, expandable research dossier viewer.

# Design System Tokens & Theming
Derived from `DESIGN_LANGUAGE.md`:
- **Theme Palette**:
  - Background: `#0E1117` (deep charcoal)
  - Surface / Cards: `#161B22`
  - Borders: `#30363D`
  - Long / Positive / Call: `#2EA043` (Net Green)
  - Short / Negative / Put: `#DA3633` (Net Red)
  - Accent / Payoff Curves: `#58A6FF` (Electric Blue)
  - Alert / High Gamma / Warning: `#D29922` (Caution Amber)
- **Typography**:
  - Monospace (`JetBrains Mono`, `Fira Code`): All numerical values, prices, Greeks, order quantities, and matrix tables.
  - Sans-Serif (`Inter`, system-ui): Labels, navigation, modal text, and headers.

# Reactivity & Partial Updates
- **dcc.Interval Polling**: Use targeted `dcc.Interval` components (e.g., 500ms for live quotes, 2000ms for portfolio summaries) to trigger partial DOM updates without full-page re-renders.
- **Client-Side State Isolation**:
  - UI handlers read strictly from local repositories (in-memory tick ring buffer for live quotes and SQLite WAL store for orders/trades per ADR 008).
  - Never execute Black-Scholes formulas, numerical IV solvers, or order matching inside Dash callbacks.
  - Callbacks delegate all computational requests to domain services (`options/`, `validation/`, `core/PaperBroker`).

# Architectural Boundaries ("Never" Rules for UI)
- **NEVER bypass domain layers**: Callbacks must never query raw database tables or manipulate ledgers directly (must use application services).
- **NEVER execute live broker orders**: UI actions route strictly into `core/PaperBroker` paper execution paths.
- **NEVER mutate global server state**: Callbacks must remain pure with respect to request context, using Dash `dcc.Store` for user session state.
