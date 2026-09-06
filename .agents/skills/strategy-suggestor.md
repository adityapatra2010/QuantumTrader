name: Strategy Suggestor
description: Automated option strategy mapping based on market regime and bias.

# Goal
Translate market forecasts and volatility profiles into pre-filled options templates for human review[cite: 1, 2].

# Bias Allocation
- Maintain a configurable balance between premium selling and premium buying strategies[cite: 1].
- Default allocation: **60% Selling / 40% Buying** (adjustable: Aggressive, Balanced, Conservative, Theta Hunter, Momentum)[cite: 1].

# Strategy Matching Logic
- **Low Volatility / Sideways**: Iron Condors, Iron Flies, Short Strangles, Calendar Spreads[cite: 1, 2].
- **Directional / Trending**: Bull Call Spreads, Bear Put Spreads, Ratio Spreads[cite: 1, 2].
- **High Volatility / Expansion**: Long Straddles, Long Strangles, Debit Spreads[cite: 1, 2].

# Operating Rules
- Pre-fill strike offsets from live option chains; never submit orders directly[cite: 2].
- Strategies must clear the Validation Engine before being displayed as suggestions[cite: 1].
