name: Options Engine
description: Chain processing, Greeks computation, and payoff modeling.

# Goal
Provide accurate quantitative analysis for single and multi-leg derivatives structures[cite: 2].

# Core Modules
- `chain.py`: Map option chains into standardized `ChainRow` records (`strike`, `expiry`, call/put `ltp`, `oi`, `iv`, `greeks`)[cite: 2].
- `greeks.py`: Use broker quote values when verified; otherwise compute Delta, Gamma, Theta, and Vega via Black-Scholes using spot, strike, risk-free rate, and time-to-expiry[cite: 2].
- `payoff.py`: Pure function processing `list[OptionLeg]` + underlying price range $\to$ `list[PayoffPoint]`[cite: 2].

# Calculations
- Derive breakevens, max profit, and max loss dynamically from the computed payoff curve[cite: 2].
- Calculate mark-to-market P&L curves across multiple days to expiration (DTE)[cite: 2].
