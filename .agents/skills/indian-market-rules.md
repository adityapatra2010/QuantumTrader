name: Indian Market Rules
description: Regulatory specifications, market sessions, exchange taxation, and derivatives contracts for NSE.

# Goal
Enforce exact NSE (National Stock Exchange of India) operational mechanics, timing constraints, and statutory costs across all trading engines[cite: 2].

# Trading Sessions (IST)
- **Pre-Open**: 09:00 to 09:08 (Order collection), 09:08 to 09:15 (Order matching).
- **Regular Trading Hours**: 09:15 to 15:30[cite: 2].
- **Post-Market / Closing Run**: 15:40 to 16:00.
- **Session Rules**: Reject order creation outside 09:15–15:30 IST[cite: 2]. The system must report `MARKET_CLOSED` and refuse live paper simulation runs when offline[cite: 2].

# Derivatives Contract Specs
- **Index Lot Sizes**: Ensure order sizes are multiples of official NSE lot sizes (e.g., NIFTY: 25 / 50 per regulatory revisions, BANKNIFTY: 15 / 30).
- **Strike Step Size**: NIFTY: 50 points; BANKNIFTY: 100 points; FINNIFTY: 50 points.
- **Expiries**: Derive contract expirations dynamically from official NSE scrip master records per ADR 009 (accounting for underlying-specific cycles: NIFTY Thursdays, FINNIFTY Tuesdays, etc., and SEBI regulatory circulars).

# F&O Transaction Costs (for Net P&L Realism)
- **Securities Transaction Tax (STT)**:
  - Options (Sell side on premium): 0.1%
  - Futures (Sell side): 0.02%
  - Exercised Options: 0.125% of intrinsic value
- **Exchange Turnover Charges**: NSE charges applied per ₹1 crore of turnover.
- **GST**: 18% on brokerage, exchange turnover charges, and SEBI turnover fees.
- **Stamp Duty**: 0.003% on buy side for equity derivatives.
