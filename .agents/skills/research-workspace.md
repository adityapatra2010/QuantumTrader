name: Research Workspace
description: Automated strategy dossier generation and research logging.

# Goal
Generate detailed, auditable analytical reports for any strategy run or backtested model[cite: 1].

# Dossier Structure & Evidence Categorization (ADR 012)
Every quantitative research dossier conforms to `aditrader.ai.models.ResearchDossier` and comprises ordered `DossierSection` entries categorized by evidence type:
- `DETERMINISTIC`: Verified backtest analytics, Black-Scholes Greeks, payoff surfaces, and ledger records[cite: 1].
- `STRUCTURAL`: Declarative AST strategy DSL rules, condition trees, and option leg definitions[cite: 1].
- `METADATA`: Timestamps, git commit hashes, run identifiers, and policy parameters[cite: 1].
- `AI_ADVISORY`: Probabilistic forecasts, multimodal chart extractions, qualitative critiques, and educational breakdowns. Must carry a mandatory `ProvenanceRecord` (ADR 012)[cite: 1].

# Report Sections
- **Executive Overview**: Underlying asset, strategy classification, execution timeframes, and validation score (`STRUCTURAL` / `DETERMINISTIC`)[cite: 1].
- **Mechanism Breakdown**: Plain-language explanation of entry rules, exit rules, and edge conditions (`STRUCTURAL`)[cite: 1].
- **Risk Metrics**: Maximum drawdown, historical expectancy, Profit Factor, Sharpe, and Probability of Profit (`DETERMINISTIC`)[cite: 1].
- **Sensitivities**: Parameter variation grids, strike offset sensitivity, and IV shift impact (`DETERMINISTIC`)[cite: 1].
- **Trade Distribution**: Return dispersion, average holding duration, MAE, and MFE (`DETERMINISTIC`)[cite: 1].
- **AI Assessment & Critique**: Model-generated critiques outlining potential weaknesses, market regime conflicts, and optimization suggestions (`AI_ADVISORY` with `ProvenanceRecord`)[cite: 1].
- **Institutional Compliance Disclaimer**: Mandatory disclaimer explicitly noting AI sections are advisory hypotheses and do not constitute empirical historical proof or financial advice[cite: 1].

