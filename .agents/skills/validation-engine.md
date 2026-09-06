name: Validation Engine
description: Institutional Mode gatekeeper for algorithmic strategy verification.

# Goal
Enforce objective risk and statistical checks to reject underperforming, overfitted, or dangerous strategies before paper execution[cite: 1].

# Subsystems & Separation of Concerns
The Validation Engine operates as an Application Service and is strictly decoupled from the runtime execution Risk Engine:

1. **`validation/ast/` (Static DSL Structural Validation)**:
   - Validates declarative JSON AST trees prior to compilation (ADR 001, ADR 007).
   - Checks schema versioning (`schema_version: "1.0"`), valid strike offsets relative to ATM, allowed static operators, condition group logic, and option leg balance.
   - Rejects unparseable, malformed, or contradictory strategy definitions.

2. **`validation/institutional/historical.py` (Historical Statistical Gatekeeping for Linear Assets)**:
   - Evaluates completed backtests strictly for **Equities and Futures**. Options strategies are rejected with a hard `ValueError`.
   - Evaluates:
     - **Mathematical Expectancy Floor**: Positive expectancy floor ($E > 0$) as a non-negotiable hard floor.
     - **Timeframe-Aware Sample Size**: Resolves required trades based on timeframe ($N \ge 100$ for intraday, $N \ge 50$ for hourly, $N \ge 30$ for daily, $N \ge 20$ for swing). Marks `SUFFICIENT_SAMPLE` vs. `INSUFFICIENT_SAMPLE`.
     - **Profit Factor & Max Drawdown**: Institutional floors (e.g. $PF \ge 1.3$, Max Drawdown $\le 15\%$).
     - **Risk-Adjusted Metrics**: Sharpe, Sortino, and System Quality Number (SQN).
     - **Overfitting & Stability**: Out-of-sample (OOS) Sharpe retention and Walk-Forward profitable window consistency.

3. **`validation/institutional/options_payoff.py` (Theoretical Payoff & Greek Risk Gatekeeping for Options)**:
   - Evaluates multi-leg options strategies via mathematical payoff surfaces and Greek profiles.
   - Strictly tagged as `THEORETICAL_VALIDATION_ONLY` (`validation_scope=THEORETICAL`).
   - NEVER emits historical statistical metrics (expectancy, Sharpe, win rate) for options.
   - Evaluates:
     - **Defined-Risk Architecture**: Flags or rejects unbounded max loss.
     - **Naked Short Gamma Explosion Veto**: Rejects selling naked short options near expiry.
     - **Theoretical Risk/Reward Ratio**: Verifies acceptable maximum loss per unit max profit.
     - **Breakeven Corridor Check**: Resolves expiry breakevens across spot price spectrum.

# Validation Policies
- **`InstitutionalPolicy`**: Strictest institutional standards ($E > 0$, $PF \ge 1.3$, $DD \le 15\%$, defined risk required, OOS retention $\ge 50\%$).
- **`ModeratePolicy`**: Standard paper trading criteria ($E > 0$, $PF \ge 1.1$, $DD \le 25\%$, OOS retention $\ge 35\%$).
- **`ResearchPolicy`**: Exploratory research setting warnings instead of hard rejections.

# Output Schema
- Produces an immutable `ValidationResult` object containing:
  - `status` (`APPROVED` | `NOT_RECOMMENDED` | `REJECTED`)
  - `validation_scope` (`HISTORICAL` | `THEORETICAL` | `STRUCTURAL`)
  - `sample_size_status` (`SUFFICIENT_SAMPLE` | `INSUFFICIENT_SAMPLE` | `NOT_APPLICABLE`)
  - `historical_vs_theoretical` (`HISTORICAL` | `THEORETICAL`)
  - `validation_score` (0-100)
  - `metrics` (Scope-appropriate metrics)
  - `failed_gates` (list of triggered constraint names)
  - `gate_results` (detailed per-gate breakdown with observed vs threshold values)
  - `warnings` and `suggested_improvements`
