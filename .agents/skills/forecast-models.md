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
- Every model adapter must implement the standard interface:
  `forecast(history: list[Bar]) -> ForecastResult`[cite: 1, 2].
- Model internals (tokenizers, context lengths, GPU configurations) must remain strictly encapsulated inside their respective adapter classes[cite: 1, 2].
- Forecasts must always be treated as probabilities, never as deterministic trading commands[cite: 1].
- All AI-generated outputs are advisory and must pass through the Validation Engine and Risk Engine before execution[cite: 1].

# Forbidden
- Never generate direct trading orders or signals inside the forecasting adapter[cite: 1, 2].
- Never import UI components, paper-broker modules, or database sessions into model adapters[cite: 1, 2].
- Never refer to model predictions as "certain" or "guaranteed" in system logs or reports[cite: 1].

# Output Requirements
- Must output a validated `ForecastResult` object[cite: 2]:
  - `timestamps`: Horizon timestamps (`list[datetime]`)[cite: 2]
  - `predicted_close`: Array of median expected close prices (`list[float]`)[cite: 2]
  - `predicted_high`: Array of upper confidence boundary prices (`list[float]`)[cite: 2]
  - `predicted_low`: Array of lower confidence boundary prices (`list[float]`)[cite: 2]
  - `confidence_spread`: Normalized uncertainty metric (`float`)[cite: 2]
