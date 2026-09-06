name: Testing Standards
description: Test requirements for calculation accuracy, broker simulation, and data pipelines.

# Goal
Ensure complete offline test coverage for mission-critical quantitative calculations before live feed integration[cite: 2].

# Rules
- `options/greeks.py`: Validate Black-Scholes delta, gamma, theta, and vega against established textbook values using offline fixtures[cite: 2].
- `options/payoff.py`: Verify payoff curves, breakevens, max loss, and max profit for single calls/puts, vertical spreads, and 4-leg iron condors without network access[cite: 2].
- `validation/`: Ensure test cases exist where strategies with negative expectancy, excessive drawdown, or small sample sizes are explicitly rejected[cite: 1].
- `core/PaperBroker`: Test simulated order fills, slippage calculations, and margin tracking using deterministically replayed tick fixtures[cite: 2].
