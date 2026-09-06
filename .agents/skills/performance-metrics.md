name: Performance Metrics
description: Mathematical formulas for evaluating strategy performance and risk.

# Goal
Ensure uniform computation of all statistical metrics across CLI reports, backtests, and live paper runs[cite: 1, 2].

# Standard Formulas
- **Mathematical Expectancy**:
  $$E = (\text{Win Rate} \times \text{Average Win}) - (\text{Loss Rate} \times \text{Average Loss})$$
- **Profit Factor**:
  $$PF = \frac{\sum \text{Gross Profits}}{\sum \text{Gross Losses}}$$
- **Sharpe Ratio**:
  $$\text{Sharpe} = \frac{R_p - R_f}{\sigma_p}$$
- **Sortino Ratio**:
  $$\text{Sortino} = \frac{R_p - R_f}{\sigma_d}$$
  (where $\sigma_d$ is the standard deviation of downside returns)
- **Maximum Drawdown (MDD)**: Peak-to-trough equity decline represented as a percentage[cite: 1].
- **Kelly Fraction**: Optimal capital allocation formula derived from win rate and payoff ratio[cite: 1].
- **System Quality Number (SQN)**:
  $$\text{SQN} = \sqrt{N} \times \frac{\text{Mean PnL}}{\text{Standard Deviation of PnL}}$$
