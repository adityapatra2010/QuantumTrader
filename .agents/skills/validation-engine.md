name: Validation Engine
description: Institutional Mode gatekeeper for algorithmic strategy verification.

# Goal
Enforce objective risk and statistical checks to reject underperforming, overfitted, or dangerous strategies before paper execution[cite: 1].

# Subsystems & Separation of Concerns
The Validation Engine operates as an Application Service and is strictly decoupled from the runtime execution Risk Engine:

1. **`validation/ast/` (Static DSL Validation)**:
   - Validates declarative JSON AST trees prior to strategy compilation (ADR 001, ADR 007).
   - Checks schema versioning (`schema_version: "1.0"`), valid strike offsets relative to ATM, allowed static operators, and option leg balance.
   - Rejects unparseable, malformed, or prohibited condition definitions with syntax errors.

2. **`validation/institutional/` (Statistical Gatekeeping)**:
   - Evaluates completed backtest runs or historical simulation logs against Institutional Mode policies (ADR 004).
   - Rejection Criteria:
     - **Negative Expectancy**: Strategy must demonstrate positive mathematical expectancy ($E > 0$) across historical samples.
     - **Profit Factor**: Must achieve a minimum configured Profit Factor (e.g., $PF \ge 1.3$).
     - **Sample Size**: Must meet minimum sample constraints (e.g., $N \ge 300$ trades).
     - **Tail Risk & Gamma**: Naked option sales or unhedged positions near expiry must be flagged or rejected.
     - **Overfitting**: Flag strategies showing high fragility across market regimes or parameter variations.
     - **Drawdown Limit**: Reject if maximum drawdown exceeds user-configured risk tolerances.

*(Note: Live pre-trade margin checks, order quantity gates, and intraday circuit breakers are handled by the runtime `risk/` engine inside `core/PaperBroker`, not by the Validation Engine).*

# Output Schema
- Produce a `ValidationResult` object containing:
  - `validation_score` (0-100)
  - `status` (`APPROVED` | `NOT_RECOMMENDED` | `REJECTED`)
  - `metrics` (Expectancy, Drawdown, POP, Sharpe, Profit Factor)
  - `rejection_reasons` (list of triggered constraints)
  - `suggested_improvements` (concrete adjustment notes)
