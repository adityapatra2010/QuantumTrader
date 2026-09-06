name: Backtesting Engine
description: Historical execution simulation, look-ahead bias prevention, and fill realism.

# Goal
Execute strategy logic deterministically against historical data while strictly mirroring live paper-broker execution behavior.

# Pipeline

Historical Candles / Ticks
|
v
Data Feed Generator  <--- Enforce zero look-ahead bias (strict point-in-time data)
|
v
Strategy Runner
|
+---> Emits Signal
|
v
Simulated Paper Broker
|
+---> Applies Slippage, Fees, STT, and Liquidity Limits
+---> Generates Trades & Updates Equity Curve
|
v
Validation Engine  <--- Evaluates historical expectancy, drawdown, sample size

# Execution Rules
- **Zero Future Data Leakage**: At bar index $T$, the strategy has zero access to high, low, close, volume, or open interest of bar $T+k$ ($k \ge 1$). Signal generation must strictly use data closed at or before $T$.
- **Fill Assumptions**: Signal generated on bar $T$ close executes on bar $T+1$ open, or at the next available tick. Never execute a market order at the closing price of the signal-generating bar.
- **Liquidity Simulation**:
  - Restrict execution volume to a maximum of 5% of the candle's total volume for options contracts.
  - Apply bid-ask spread penalties: simulate market orders at the Ask for buys and at the Bid for sells.
- **Expiry & Settlement**:
  - Derive weekly and monthly contract expiration dates dynamically from the broker scrip master metadata (`contract_master`) per ADR 009, never hardcoding days of the week.
  - Square off in-the-money (ITM) options prior to market close on expiration day to simulate mandatory physical settlement prevention.
