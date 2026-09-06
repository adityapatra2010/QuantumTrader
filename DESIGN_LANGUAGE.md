# UI & Design System Specification

## Framework & Structural Principles
- **Framework**: Plotly Dash utilizing `dash.register_page` for native multi-page orchestration[cite: 2].
- **State Architecture**: Read-only consumption of the local SQLite/Parquet run-store[cite: 2]. The UI displays paper-trading state but never executes raw orders directly[cite: 2].
- **Reactivity Pattern**: Targeted component callbacks via `dcc.Interval` polling to update specific tables without triggering full-page rerenders[cite: 2].

---

## Visual Hierarchy & Theme
- **Base Style**: Minimalist technical dark theme (background `#0E1117`, surface `#161B22`, border `#30363D`).
- **Typography**: Monospace fonts (`JetBrains Mono`, `Fira Code`) for metrics, price ladders, and numerical grids; Sans-serif (`Inter`) for labels and navigation.
- **Color Semantics**:
  - Net Green (`#2EA043`): Positive P&L, call indicators, long legs[cite: 2].
  - Net Red (`#DA3633`): Negative P&L, put indicators, short legs[cite: 2].
  - Accent Blue (`#58A6FF`): System indicators, payoff curves, selected strikes.
  - Caution Amber (`#D29922`): Validation warnings, high gamma alerts, margin thresholds[cite: 1].

---

## Page Layout Specifications

### 1. Portfolio & P&L (`/`)
- **Top Bar**: Persistent market session badge (`LIVE MARKET`, `HISTORICAL REPLAY`, `MARKET CLOSED`) and tick heartbeat[cite: 2].
- **Book Overview**: Net Portfolio P&L (MTM and Realized), Total Capital, Margin Utilization gauge[cite: 1, 2].
- **Greeks Aggregate**: Net Portfolio Delta, Gamma, Theta, and Vega summed across active legs[cite: 2].
- **Positions Grid**: Grouped multi-leg structures (e.g., displaying an Iron Condor as a collapsed parent row with an expandable leg detail view)[cite: 2].

### 2. Option Chain (`/chain`)
- **Selector Bar**: Underlying asset picker (NIFTY, BANKNIFTY, FINNIFTY) and contract expiry dropdown[cite: 2].
- **Central Ladder**: Visual anchor at ATM strike, displaying Calls (left) and Puts (right)[cite: 2].
- **Data Columns**: OI, OI Change, IV, Greeks (Delta, Theta), LTP, Bid/Ask[cite: 2].
- **Interaction**: Single-click "Add to Builder" action per strike row[cite: 2].

### 3. Strategy Builder (`/builder`)
- **Leg Manager**: Editable table detailing Leg Type, Expiry, Strike, Side (BUY/SELL), Quantity, and Entry Premium[cite: 2].
- **Interactive Payoff Canvas**: Vector Plotly chart illustrating at-expiry payoff and mark-to-market curve across spot ranges[cite: 2].
- **Risk Metrics Panel**: Breakeven levels, Max Profit, Max Loss, Margin Requirement, and Net Debit/Credit[cite: 2].
- **Action Gate**: Prominent "Validate & Paper Trade" button routing the structure through the Validation Engine[cite: 1, 2].

### 4. Strategy Suggestor (`/suggest`)
- **Regime Banner**: Current classified market state (e.g., `Rangebound / Low IV / Positive Theta`)[cite: 1].
- **Bias Control**: Visual slider adjusting Selling vs. Buying preference (default 60% Selling / 40% Buying)[cite: 1].
- **Suggestion Cards**: 2 to 4 pre-filled option strategies showing Validation Scores, Expected POP, Profit Factor, and Payoff thumbnail[cite: 1, 2].
- **Action**: "Open in Builder" button to populate leg configurations into `/builder`[cite: 2].

### 5. Run History & Research (`/runs`)
- **Session Table**: Historical live and replayed paper trading runs with aggregate P&L, Sharpe, and Drawdown[cite: 1, 2].
- **Dossier Viewer**: Expandable research workspace displaying trade dispersion charts, parameter sensitivity analysis, and AI critique logs[cite: 1].
