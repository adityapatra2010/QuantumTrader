name: Strategy Suggestor
description: Automated option strategy mapping based on market regime and bias.

# Goal
Translate market forecasts and volatility profiles into pre-filled options templates for human review[cite: 1, 2].

# Bias Allocation
- Explicit, machine-readable `aditrader.ai.models.BiasCfg` configuration model (ADR 012)[cite: 1].
- Default allocation prior: **60% Selling / 40% Buying** (`sell_pct=0.60, buy_pct=0.40`).
- Validates strictly that `sell_pct + buy_pct == 1.0`[cite: 1].

# Strategy Matching Logic
- **Low Volatility / Sideways**: Iron Condors, Iron Flies, Short Strangles, Calendar Spreads[cite: 1, 2].
- **Directional / Trending**: Bull Call Spreads, Bear Put Spreads, Ratio Spreads[cite: 1, 2].
- **High Volatility / Expansion**: Long Straddles, Long Strangles, Debit Spreads[cite: 1, 2].

# Interface & Operating Rules
- Implement `aditrader.ai.base.StrategySuggestor`:
  `suggest(regime: str, bias: BiasCfg, forecast: ForecastResult | None = None, vision: VisionResult | None = None) -> SuggestionResult`[cite: 1, 2].
- Pre-fill strike offsets from option templates; never submit orders directly[cite: 2].
- Mandatory attachment of `ProvenanceRecord` with 64-character SHA-256 `input_hash` (ADR 012).
- Return `SuggestionResult` with `is_validated = False`; strategies must clear `StrategyValidationService` before approval[cite: 1].
- Downstream consumer requirement: Consumers must explicitly verify `validation_result.status == ValidationStatus.APPROVED` before executing or staging; the mere presence of `validation_result` does not denote approval (it may be `REJECTED` or `NOT_RECOMMENDED`)[cite: 1].


