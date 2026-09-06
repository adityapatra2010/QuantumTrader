name: Strategy Builder
description: Visual condition compiler and strategy tree specification.

# Goal
Compile multi-conditional option and equity strategies into structured, evaluable objects without generating unconstrained code[cite: 1, 2].

# Condition Categories
- `Indicators`: Moving averages, RSI, MACD, Supertrend, Bollinger Bands.
- `Time`: Market entry/exit windows, DTE, session phases.
- `Premium`: Absolute option premiums, premium decay thresholds.
- `Greeks`: Delta limits, net portfolio Theta, Gamma exposure thresholds.
- `OI`: Open Interest concentration, PCR shifts, OI breakouts.
- `Market Structure`: Break of Structure (BOS), Change of Character (CHoCH), Order Blocks.
- `AI Vision / Forecast`: Upstream signals emitted from Gemini Vision or Kronos.

# Allowed Static Operators (Declarative AST)
Conditions are strictly declarative and parsed into an AST. Dynamic Python execution (`eval()`, `exec()`, or custom script runners) is strictly prohibited (ADR 007). Allowed operators:
- Numerical Comparison: `GREATER_THAN`, `LESS_THAN`, `EQUALS`, `WITHIN_RANGE`
- Cross-Over: `CROSSES_ABOVE`, `CROSSES_BELOW`
- Logical Combinators: `AND`, `OR`, `NOT`
- Regime Match: `MATCHES_REGIME`

# Rules
- Compile visual trees into structured JSON documents conforming to `schema_version: "1.0"`, never arbitrary Python files (ADR 001, ADR 007).
- Conditions evaluate deterministically: `evaluate(context) -> bool`.
- Actions emit standard `Signal` or order staging directives and are triggered only when condition trees resolve to true.
- Any new technical indicator logic must be registered as a statically compiled Python class within the indicator library, never evaluated from ad-hoc runtime script strings.
