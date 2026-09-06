name: Risk Engine
description: Real-time pre-trade risk controls, margin constraints, and exposure gates.

# Goal
Act as a real-time execution safety barrier inside `core/risk/` evaluated by `core/PaperBroker` at order-fill time. Halts orders, cancels resting orders, and restricts strategy execution based on portfolio margin, capital limits, and tail risk, strictly decoupled from static pre-trade validation.

# Pre-Trade Execution Checks
- **Margin Threshold Gate**: If simulated margin utilization exceeds 85% of total account capital, reject the order immediately.
- **Unhedged Tail Risk**:
  - Outright short naked calls or puts without defined-risk protective wings are prohibited on expiry day.
  - Reject single-leg short options where the calculated loss curve is theoretically unbounded[cite: 1].
- **Gamma Explosion Check**: Reject short premium entries if DTE $\le 1$ and underlying implied volatility is expanding rapidly[cite: 1].
- **Risk-Reward Gate**: Reject any order structure with an inverse risk-to-reward ratio worse than 10:1 unless explicit historical edge criteria are met[cite: 1].

# Live Monitoring Controls
- **Circuit Breaker**: If intraday portfolio drawdown reaches 5% of starting capital, immediately trigger `EMERGENCY_HALT`: cancel all resting simulated orders and square off open positions.
- **Position Limits**: Enforce maximum concurrent active lots per underlying (e.g., maximum 20 lots total across NIFTY structures).
