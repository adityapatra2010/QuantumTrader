name: Market Regimes
description: Regime classification and strategy DNA metadata profiling.

# Goal
Classify the active market environment to match strategies with appropriate risk profiles[cite: 1].

# Regime Categories
- Directional: `Strong Trend`, `Weak Trend`, `Rangebound/Sideways`[cite: 1].
- Volatility: `High IV`, `Low IV`, `IV Compression`, `IV Expansion`[cite: 1].
- Volume: `Range Expansion`, `Range Contraction`, `Volume Climax`[cite: 1].

# Strategy DNA Tags
Every strategy must expose a computed DNA profile for comparison and filtering[cite: 1]:
- `Directionality`: Delta exposure (Bullish, Bearish, Delta-Neutral)[cite: 1].
- `Theta Profile`: Net positive or negative time decay[cite: 1].
- `Vega Risk`: Sensitivity to volatility spikes[cite: 1].
- `Style`: Scalping, Intraday, Positional, Expiry-day trading[cite: 1].
