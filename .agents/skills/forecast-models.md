---
name: Forecast Engine Models
description: Probabilistic foundation models and time-series forecasting abstraction.
---

# Purpose
Encapsulate time-series foundation models (e.g., Kronos, Chronos) behind a uniform interface, providing probabilistic market trajectory estimates without coupling core logic to specific ML implementations[cite: 1, 2].

# Responsibilities
- Ingest normalized sequences of historical `Bar` data[cite: 2].
- Compute probabilistic forecasts over specified candle horizons[cite: 1, 2].
- Return standardized `ForecastResult` structures containing predicted levels and confidence bands[cite: 2].

# Rules
- Every model adapter must implement the standard interface (`aditrader.ai.base.ForecastEngine`):
  `forecast(history: list[Bar], horizon_bars: int = 5) -> ForecastResult`[cite: 1, 2].
- `is_available() -> bool` must never raise network or runtime exceptions; it returns `False` if backend or compute resources are offline or unconfigured[cite: 2].
- Strict Point-in-Time Anti-Lookahead: `ForecastResult.cutoff_timestamp` must reflect the latest closed bar; all forecast horizon timestamps must be timezone-aware (UTC), strictly monotonically increasing, and strictly in the future ($t > cutoff\_timestamp$)[cite: 2].
- Model internals (tokenizers, context lengths, GPU configurations) must remain strictly encapsulated inside their respective adapter classes[cite: 1, 2].
- Forecasts must always be treated as probabilities, never as deterministic trading commands[cite: 1].
- All AI-generated outputs are advisory and must carry a valid `ProvenanceRecord` with a 64-character SHA-256 hexadecimal `input_hash` (ADR 012)[cite: 1].
- All suggested strategies must pass through the Validation Engine and Risk Engine before execution[cite: 1].

# Forbidden
- Never generate direct trading orders or signals inside the forecasting adapter[cite: 1, 2].
- Never import UI components, paper-broker modules, or database sessions into model adapters[cite: 1, 2].
- Never refer to model predictions as "certain" or "guaranteed" in system logs or reports[cite: 1].
- Never pass `ForecastResult` to `BacktestRunner` without verified point-in-time closure[cite: 2].

# Output Requirements
- Must output a validated `ForecastResult` object conforming to `aditrader.ai.models.ForecastResult` (ADR 012)[cite: 2]:
  - `cutoff_timestamp`: Timezone-aware UTC timestamp of last closed bar (`datetime`)[cite: 2]
  - `horizon_bars`: Number of predicted steps (`int > 0`)[cite: 2]
  - `timestamps`: Timezone-aware UTC future horizon timestamps, strictly monotonically increasing (`list[datetime]` strictly $> cutoff\_timestamp$)[cite: 2]
  - `predicted_close`: Array of expected close prices (`list[float]`)[cite: 2]
  - `predicted_high`: Array of upper confidence boundary prices (`list[float]`)[cite: 2]
  - `predicted_low`: Array of lower confidence boundary prices (`list[float]`)[cite: 2]
  - `confidence_spread`: Uncertainty spread metric (`float >= 0.0`)[cite: 2]
  - `provenance`: Mandatory `ProvenanceRecord` with 64-character hex SHA-256 `input_hash` (ADR 012)
  - Enforces `predicted_low[i] <= predicted_close[i] <= predicted_high[i]` for all points.
