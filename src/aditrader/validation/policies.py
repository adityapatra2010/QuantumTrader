"""Validation policy configurations and institutional threshold profiles."""

from pydantic import BaseModel, ConfigDict, Field


class TimeframeSampleSizeConfig(BaseModel):
    """Timeframe-aware minimum trade observation requirements."""

    model_config = ConfigDict(frozen=True)

    intraday_min_trades: int = Field(
        default=100, description="Minimum trades for intraday timeframes (<= 15m)"
    )
    hourly_min_trades: int = Field(
        default=50, description="Minimum trades for hourly timeframes (1h to 4h)"
    )
    daily_min_trades: int = Field(
        default=30, description="Minimum trades for daily timeframes (1d)"
    )
    swing_min_trades: int = Field(
        default=20, description="Minimum trades for multi-day/swing timeframes (1w, 1M)"
    )

    def get_min_trades(self, timeframe: str) -> int:
        """Resolve minimum sample size for a given timeframe string."""
        tf = timeframe.lower().strip()
        if tf in ("1s", "5s", "15s", "30s", "1m", "3m", "5m", "10m", "15m", "30m"):
            return self.intraday_min_trades
        if tf in ("1h", "2h", "4h", "60m", "120m", "240m"):
            return self.hourly_min_trades
        if tf in ("1d", "d"):
            return self.daily_min_trades
        if tf in ("1w", "w", "1m_month", "month"):
            return self.swing_min_trades
        return self.daily_min_trades


class ValidationPolicy(BaseModel):
    """Institutional validation policy governing hard floors, thresholds, and warnings."""

    model_config = ConfigDict(frozen=True)

    policy_name: str = Field(description="Policy profile identifier")

    # --------------------------------------------------------------------------
    # A. Hard Safety Floors (Mathematical requirements and existential risk)
    # --------------------------------------------------------------------------
    require_positive_expectancy: bool = Field(
        default=True,
        description="Mathematical floor: expectancy E must be strictly greater than 0.0",
    )
    require_positive_profit_factor: bool = Field(
        default=True,
        description="Profit factor must be at least 1.0 (gross profits exceed gross losses)",
    )
    ban_naked_short_options_near_expiry: bool = Field(
        default=True,
        description="Reject options strategies selling unhedged options near or on expiry",
    )
    require_defined_risk_for_options: bool = Field(
        default=False,
        description="If True, any structure with unbounded theoretical maximum loss is rejected",
    )

    # --------------------------------------------------------------------------
    # B. Configurable Statistical Thresholds (Historical Validation)
    # --------------------------------------------------------------------------
    min_profit_factor: float = Field(
        default=1.30, description="Target minimum profit factor (gross profit / gross loss)"
    )
    max_drawdown_pct: float = Field(
        default=0.15, description="Maximum allowable peak-to-trough portfolio drawdown percentage"
    )
    min_sharpe_ratio: float | None = Field(
        default=1.0, description="Target annualized Sharpe ratio (None to bypass)"
    )
    min_sortino_ratio: float | None = Field(
        default=1.2, description="Target annualized Sortino ratio (None to bypass)"
    )
    min_sqn: float | None = Field(
        default=1.5, description="Target System Quality Number (None to bypass)"
    )
    sample_size_config: TimeframeSampleSizeConfig = Field(
        default_factory=TimeframeSampleSizeConfig,
        description="Timeframe-aware minimum sample size settings",
    )
    min_oos_sharpe_retention_ratio: float | None = Field(
        default=0.50,
        description="Out-of-sample Sharpe retention ratio relative to in-sample (OOS / IS)",
    )
    min_walk_forward_profitable_window_pct: float | None = Field(
        default=0.60,
        description="Minimum fraction of walk-forward test windows that must be profitable",
    )

    # --------------------------------------------------------------------------
    # C. Options Theoretical Thresholds (Theoretical Payoff Validation)
    # --------------------------------------------------------------------------
    max_theoretical_risk_reward_ratio: float | None = Field(
        default=5.0,
        description="Maximum allowable theoretical max_loss / max_profit ratio for defined risk",
    )
    max_unhedged_gamma: float | None = Field(
        default=0.05,
        description="Maximum permitted portfolio unhedged short gamma near expiration",
    )
    min_probability_of_profit: float | None = Field(
        default=0.50,
        description="Target theoretical probability of profit at trade entry",
    )

    # --------------------------------------------------------------------------
    # D. Policy Enforcement Behavior
    # --------------------------------------------------------------------------
    reject_on_insufficient_sample: bool = Field(
        default=True,
        description="If True, insufficient observations triggers REJECTED; else NOT_RECOMMENDED",
    )
    reject_on_threshold_breach: bool = Field(
        default=True,
        description="If True, threshold breaches trigger REJECTED; else NOT_RECOMMENDED",
    )


def create_institutional_policy() -> ValidationPolicy:
    """Institutional Mode: Strict non-negotiable default for capital allocation."""
    return ValidationPolicy(
        policy_name="Institutional",
        require_positive_expectancy=True,
        require_positive_profit_factor=True,
        ban_naked_short_options_near_expiry=True,
        require_defined_risk_for_options=True,
        min_profit_factor=1.30,
        max_drawdown_pct=0.15,
        min_sharpe_ratio=1.0,
        min_sortino_ratio=1.2,
        min_sqn=1.5,
        sample_size_config=TimeframeSampleSizeConfig(
            intraday_min_trades=100,
            hourly_min_trades=50,
            daily_min_trades=30,
            swing_min_trades=20,
        ),
        min_oos_sharpe_retention_ratio=0.50,
        min_walk_forward_profitable_window_pct=0.60,
        max_theoretical_risk_reward_ratio=5.0,
        reject_on_insufficient_sample=True,
        reject_on_threshold_breach=True,
    )


def create_moderate_policy() -> ValidationPolicy:
    """Moderate Mode: Balanced prosumer profile with flexible threshold warnings."""
    return ValidationPolicy(
        policy_name="Moderate",
        require_positive_expectancy=True,
        require_positive_profit_factor=True,
        ban_naked_short_options_near_expiry=True,
        require_defined_risk_for_options=False,
        min_profit_factor=1.15,
        max_drawdown_pct=0.25,
        min_sharpe_ratio=0.5,
        min_sortino_ratio=0.6,
        min_sqn=1.0,
        sample_size_config=TimeframeSampleSizeConfig(
            intraday_min_trades=50,
            hourly_min_trades=30,
            daily_min_trades=20,
            swing_min_trades=15,
        ),
        min_oos_sharpe_retention_ratio=0.35,
        min_walk_forward_profitable_window_pct=0.50,
        max_theoretical_risk_reward_ratio=10.0,
        reject_on_insufficient_sample=False,
        reject_on_threshold_breach=False,
    )


def create_research_policy() -> ValidationPolicy:
    """Research Mode: Sandbox exploratory policy emitting diagnostic warnings without hard vetoes."""
    return ValidationPolicy(
        policy_name="Research",
        require_positive_expectancy=True,
        require_positive_profit_factor=False,
        ban_naked_short_options_near_expiry=False,
        require_defined_risk_for_options=False,
        min_profit_factor=1.0,
        max_drawdown_pct=0.40,
        min_sharpe_ratio=None,
        min_sortino_ratio=None,
        min_sqn=None,
        sample_size_config=TimeframeSampleSizeConfig(
            intraday_min_trades=20,
            hourly_min_trades=15,
            daily_min_trades=10,
            swing_min_trades=5,
        ),
        min_oos_sharpe_retention_ratio=None,
        min_walk_forward_profitable_window_pct=None,
        max_theoretical_risk_reward_ratio=None,
        reject_on_insufficient_sample=False,
        reject_on_threshold_breach=False,
    )
