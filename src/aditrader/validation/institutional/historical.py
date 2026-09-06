"""Historical statistical validation engine for linear assets (Equities & Futures)."""

from typing import Any, Literal

from aditrader.backtesting.runner import BacktestResult
from aditrader.data.instruments.specs import is_futures_symbol
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.validation.models import (
    GateSeverity,
    SampleSizeStatus,
    ValidationGateResult,
    ValidationResult,
    ValidationScope,
    ValidationStatus,
)
from aditrader.validation.policies import ValidationPolicy, create_institutional_policy


class HistoricalStatisticalValidator:
    """Institutional gatekeeper evaluating historical backtest performance metrics."""

    @classmethod
    def validate(
        cls,
        strategy: StrategyDSL,
        result: BacktestResult,
        policy: ValidationPolicy | None = None,
        *,
        oos_result: BacktestResult | None = None,
        walk_forward_results: list[BacktestResult] | None = None,
    ) -> ValidationResult:
        """Evaluate backtest results against institutional policy rules.

        Important Guardrail:
        Strictly applies to linear assets (Equities/Futures). Multi-leg option strategies
        cannot produce valid historical candle backtests and must be rejected here.
        """
        active_policy = policy or create_institutional_policy()

        # Guard: Reject multi-leg option strategies from historical validation
        if strategy.legs:
            raise ValueError(
                f"Historical statistical validation is strictly prohibited for options strategy '{strategy.name}'. "
                "Historical backtesting on option legs is unavailable. "
                "Use OptionsTheoreticalValidator for theoretical payoff and risk evaluation."
            )

        gate_results: list[ValidationGateResult] = []
        warnings: list[str] = []
        suggestions: list[str] = []

        perf = result.performance
        timeframe = strategy.timeframe

        # ----------------------------------------------------------------------
        # 1. Sample Size Significance Gate
        # ----------------------------------------------------------------------
        min_trades = active_policy.sample_size_config.get_min_trades(timeframe)
        trades_count = perf.total_trades

        if trades_count < min_trades:
            sample_size_status = SampleSizeStatus.INSUFFICIENT_SAMPLE
            severity = (
                GateSeverity.HARD_FLOOR
                if active_policy.reject_on_insufficient_sample
                else GateSeverity.WARNING
            )
            gate_results.append(
                ValidationGateResult(
                    gate_name="SAMPLE_SIZE_SIGNIFICANCE",
                    passed=False,
                    severity=severity,
                    detail=(
                        f"Observed trade count ({trades_count}) is below minimum required "
                        f"({min_trades}) for '{timeframe}' timeframe. Results lack statistical power."
                    ),
                    observed_value=trades_count,
                    threshold_value=min_trades,
                )
            )
            warnings.append(
                f"Sample size ({trades_count} trades) is statistically insufficient for {timeframe}. Minimum target: {min_trades}."
            )
            suggestions.append(
                f"Extend historical test duration to accumulate at least {min_trades} completed roundtrip trades."
            )
        else:
            sample_size_status = SampleSizeStatus.SUFFICIENT_SAMPLE
            gate_results.append(
                ValidationGateResult(
                    gate_name="SAMPLE_SIZE_SIGNIFICANCE",
                    passed=True,
                    severity=GateSeverity.THRESHOLD,
                    detail=f"Sample size ({trades_count} trades) satisfies minimum target ({min_trades}).",
                    observed_value=trades_count,
                    threshold_value=min_trades,
                )
            )

        # ----------------------------------------------------------------------
        # 2. Mathematical Expectancy Hard Safety Floor (E > 0)
        # ----------------------------------------------------------------------
        expectancy = perf.expectancy
        if expectancy <= 0.0:
            gate_results.append(
                ValidationGateResult(
                    gate_name="POSITIVE_EXPECTANCY_FLOOR",
                    passed=False,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=(
                        f"Mathematical expectancy ({expectancy:.2f}) is non-positive. "
                        "By the Law of Large Numbers, the strategy has negative drift after friction."
                    ),
                    observed_value=expectancy,
                    threshold_value=0.0,
                )
            )
            suggestions.append(
                "Improve win-rate or average win/loss payoff ratio to achieve positive expectancy."
            )
        else:
            gate_results.append(
                ValidationGateResult(
                    gate_name="POSITIVE_EXPECTANCY_FLOOR",
                    passed=True,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=f"Mathematical expectancy is positive ({expectancy:.2f} per trade).",
                    observed_value=expectancy,
                    threshold_value=0.0,
                )
            )

        # ----------------------------------------------------------------------
        # 3. Profit Factor Gate
        # ----------------------------------------------------------------------
        pf = perf.profit_factor
        if pf is None:
            if perf.gross_loss == 0.0 and perf.gross_profit > 0.0:
                warnings.append("Profit factor is undefined (zero gross losses recorded).")
                gate_results.append(
                    ValidationGateResult(
                        gate_name="PROFIT_FACTOR_TARGET",
                        passed=True,
                        severity=GateSeverity.THRESHOLD,
                        detail="Zero gross losses; profit factor is mathematically undefined.",
                        observed_value=None,
                        threshold_value=active_policy.min_profit_factor,
                    )
                )
            else:
                severity = (
                    GateSeverity.HARD_FLOOR
                    if active_policy.require_positive_profit_factor
                    else GateSeverity.WARNING
                )
                gate_results.append(
                    ValidationGateResult(
                        gate_name="PROFIT_FACTOR_TARGET",
                        passed=not active_policy.require_positive_profit_factor,
                        severity=severity,
                        detail="Profit factor could not be calculated.",
                    )
                )
        elif pf < 1.0:
            severity = (
                GateSeverity.HARD_FLOOR
                if active_policy.require_positive_profit_factor
                else GateSeverity.WARNING
            )
            gate_results.append(
                ValidationGateResult(
                    gate_name="PROFIT_FACTOR_FLOOR",
                    passed=not active_policy.require_positive_profit_factor,
                    severity=severity,
                    detail=(
                        f"Gross losses exceed gross profits (PF: {pf:.2f} < 1.0)."
                        if active_policy.require_positive_profit_factor
                        else f"Gross losses exceed gross profits (PF: {pf:.2f} < 1.0), tolerated under {active_policy.policy_name} mode."
                    ),
                    observed_value=pf,
                    threshold_value=1.0,
                )
            )
        elif pf < active_policy.min_profit_factor:
            gate_results.append(
                ValidationGateResult(
                    gate_name="PROFIT_FACTOR_TARGET",
                    passed=False,
                    severity=GateSeverity.THRESHOLD,
                    detail=(
                        f"Profit factor ({pf:.2f}) is below policy threshold "
                        f"({active_policy.min_profit_factor:.2f})."
                    ),
                    observed_value=pf,
                    threshold_value=active_policy.min_profit_factor,
                )
            )
            suggestions.append(
                f"Tighten stop-loss exits to increase Profit Factor above {active_policy.min_profit_factor:.2f}."
            )
        else:
            gate_results.append(
                ValidationGateResult(
                    gate_name="PROFIT_FACTOR_TARGET",
                    passed=True,
                    severity=GateSeverity.THRESHOLD,
                    detail=f"Profit factor ({pf:.2f}) satisfies target ({active_policy.min_profit_factor:.2f}).",
                    observed_value=pf,
                    threshold_value=active_policy.min_profit_factor,
                )
            )

        # ----------------------------------------------------------------------
        # 4. Maximum Drawdown Gate
        # ----------------------------------------------------------------------
        max_dd = perf.max_drawdown_pct
        if max_dd > active_policy.max_drawdown_pct:
            gate_results.append(
                ValidationGateResult(
                    gate_name="MAX_DRAWDOWN_TOLERANCE",
                    passed=False,
                    severity=GateSeverity.THRESHOLD,
                    detail=(
                        f"Maximum peak-to-trough drawdown ({max_dd * 100:.2f}%) exceeds "
                        f"allowable limit ({active_policy.max_drawdown_pct * 100:.1f}%)."
                    ),
                    observed_value=round(max_dd, 4),
                    threshold_value=active_policy.max_drawdown_pct,
                )
            )
            suggestions.append(
                "Incorporate volatility-adjusted position sizing or tighter ATR stops."
            )
        else:
            gate_results.append(
                ValidationGateResult(
                    gate_name="MAX_DRAWDOWN_TOLERANCE",
                    passed=True,
                    severity=GateSeverity.THRESHOLD,
                    detail=f"Max drawdown ({max_dd * 100:.2f}%) is within limit ({active_policy.max_drawdown_pct * 100:.1f}%).",
                    observed_value=round(max_dd, 4),
                    threshold_value=active_policy.max_drawdown_pct,
                )
            )

        # ----------------------------------------------------------------------
        # 5. Risk-Adjusted Return Gates (Sharpe, Sortino, SQN)
        # ----------------------------------------------------------------------
        if active_policy.min_sharpe_ratio is not None:
            sharpe = perf.sharpe_ratio
            if sharpe is None or sharpe < active_policy.min_sharpe_ratio:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="SHARPE_RATIO_TARGET",
                        passed=False,
                        severity=GateSeverity.THRESHOLD,
                        detail=(
                            f"Annualized Sharpe ratio ({'None' if sharpe is None else f'{sharpe:.2f}'}) "
                            f"is below target ({active_policy.min_sharpe_ratio:.2f})."
                        ),
                        observed_value=round(sharpe, 2) if sharpe is not None else None,
                        threshold_value=active_policy.min_sharpe_ratio,
                    )
                )
            else:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="SHARPE_RATIO_TARGET",
                        passed=True,
                        severity=GateSeverity.THRESHOLD,
                        detail=f"Annualized Sharpe ratio ({sharpe:.2f}) meets target.",
                        observed_value=round(sharpe, 2),
                        threshold_value=active_policy.min_sharpe_ratio,
                    )
                )

        if active_policy.min_sortino_ratio is not None:
            sortino = perf.sortino_ratio
            if sortino is None or sortino < active_policy.min_sortino_ratio:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="SORTINO_RATIO_TARGET",
                        passed=False,
                        severity=GateSeverity.THRESHOLD,
                        detail=(
                            f"Annualized Sortino ratio ({'None' if sortino is None else f'{sortino:.2f}'}) "
                            f"is below target ({active_policy.min_sortino_ratio:.2f})."
                        ),
                        observed_value=round(sortino, 2) if sortino is not None else None,
                        threshold_value=active_policy.min_sortino_ratio,
                    )
                )
            else:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="SORTINO_RATIO_TARGET",
                        passed=True,
                        severity=GateSeverity.THRESHOLD,
                        detail=f"Annualized Sortino ratio ({sortino:.2f}) meets target.",
                        observed_value=round(sortino, 2),
                        threshold_value=active_policy.min_sortino_ratio,
                    )
                )

        if active_policy.min_sqn is not None:
            sqn = perf.sqn
            if sqn is None or sqn < active_policy.min_sqn:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="SQN_SCORE_TARGET",
                        passed=False,
                        severity=GateSeverity.THRESHOLD,
                        detail=(
                            f"System Quality Number ({'None' if sqn is None else f'{sqn:.2f}'}) "
                            f"is below target ({active_policy.min_sqn:.2f})."
                        ),
                        observed_value=round(sqn, 2) if sqn is not None else None,
                        threshold_value=active_policy.min_sqn,
                    )
                )
            else:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="SQN_SCORE_TARGET",
                        passed=True,
                        severity=GateSeverity.THRESHOLD,
                        detail=f"System Quality Number ({sqn:.2f}) meets target.",
                        observed_value=round(sqn, 2),
                        threshold_value=active_policy.min_sqn,
                    )
                )

        # ----------------------------------------------------------------------
        # 6. Out-of-Sample (OOS) Robustness Gate (Optional)
        # ----------------------------------------------------------------------
        if oos_result is not None and active_policy.min_oos_sharpe_retention_ratio is not None:
            # Enforce genuine temporal separation (Finding 8)
            has_is_ts = bool(result.equity_timestamps)
            has_oos_ts = bool(oos_result.equity_timestamps)
            if has_is_ts and has_oos_ts:
                is_max_ts = max(result.equity_timestamps)
                oos_min_ts = min(oos_result.equity_timestamps)
                if oos_min_ts < is_max_ts:
                    gate_results.append(
                        ValidationGateResult(
                            gate_name="OOS_TEMPORAL_SEPARATION",
                            passed=False,
                            severity=GateSeverity.HARD_FLOOR,
                            detail=(
                                f"Data leakage detected! OOS start timestamp ({oos_min_ts.isoformat()}) "
                                f"precedes IS end timestamp ({is_max_ts.isoformat()}). "
                                "OOS dataset must be strictly disjoint and subsequent to in-sample dataset."
                            ),
                            observed_value=oos_min_ts.isoformat(),
                            threshold_value=is_max_ts.isoformat(),
                        )
                    )
                    warnings.append("OOS backtest period overlaps with in-sample training window.")
                else:
                    gate_results.append(
                        ValidationGateResult(
                            gate_name="OOS_TEMPORAL_SEPARATION",
                            passed=True,
                            severity=GateSeverity.HARD_FLOOR,
                            detail="OOS period is strictly temporally separated from in-sample dataset.",
                            observed_value=oos_min_ts.isoformat(),
                            threshold_value=is_max_ts.isoformat(),
                        )
                    )

            is_sharpe = perf.sharpe_ratio or 0.0
            oos_sharpe = oos_result.performance.sharpe_ratio or 0.0
            retention = (oos_sharpe / is_sharpe) if is_sharpe > 0.0 else 0.0

            if retention < active_policy.min_oos_sharpe_retention_ratio:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="OOS_SHARPE_RETENTION",
                        passed=False,
                        severity=GateSeverity.THRESHOLD,
                        detail=(
                            f"OOS Sharpe retention ({retention:.2f}) fell below policy threshold "
                            f"({active_policy.min_oos_sharpe_retention_ratio:.2f}). Indicates overfitting."
                        ),
                        observed_value=round(retention, 2),
                        threshold_value=active_policy.min_oos_sharpe_retention_ratio,
                    )
                )
                suggestions.append("Reduce parameter complexity or indicator degrees of freedom.")
            else:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="OOS_SHARPE_RETENTION",
                        passed=True,
                        severity=GateSeverity.THRESHOLD,
                        detail=f"OOS Sharpe retention ({retention:.2f}) satisfies threshold.",
                        observed_value=round(retention, 2),
                        threshold_value=active_policy.min_oos_sharpe_retention_ratio,
                    )
                )

        # ----------------------------------------------------------------------
        # 7. Walk-Forward Window Consistency Gate (Optional)
        # ----------------------------------------------------------------------
        if (
            walk_forward_results
            and active_policy.min_walk_forward_profitable_window_pct is not None
        ):
            n_windows = len(walk_forward_results)
            profitable_windows = sum(
                1 for w in walk_forward_results if w.performance.net_profit > 0.0
            )
            profit_win_pct = profitable_windows / n_windows if n_windows > 0 else 0.0

            if profit_win_pct < active_policy.min_walk_forward_profitable_window_pct:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="WALK_FORWARD_CONSISTENCY",
                        passed=False,
                        severity=GateSeverity.THRESHOLD,
                        detail=(
                            f"Walk-forward profitable window ratio ({profit_win_pct * 100:.1f}%) "
                            f"is below threshold ({active_policy.min_walk_forward_profitable_window_pct * 100:.1f}%)."
                        ),
                        observed_value=round(profit_win_pct, 2),
                        threshold_value=active_policy.min_walk_forward_profitable_window_pct,
                    )
                )
            else:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="WALK_FORWARD_CONSISTENCY",
                        passed=True,
                        severity=GateSeverity.THRESHOLD,
                        detail=f"Walk-forward consistency ({profit_win_pct * 100:.1f}%) is robust.",
                        observed_value=round(profit_win_pct, 2),
                        threshold_value=active_policy.min_walk_forward_profitable_window_pct,
                    )
                )

        # ----------------------------------------------------------------------
        # 8. Score Calculation & Final Status Determination
        # ----------------------------------------------------------------------
        score = cls._calculate_validation_score(perf, active_policy, sample_size_status)

        failed_gates = [g.gate_name for g in gate_results if not g.passed]
        hard_floor_failed = any(
            not g.passed and g.severity == GateSeverity.HARD_FLOOR for g in gate_results
        )
        threshold_failed = any(
            not g.passed and g.severity == GateSeverity.THRESHOLD for g in gate_results
        )

        if hard_floor_failed:
            status = ValidationStatus.REJECTED
            score = min(score, 25.0)
        elif sample_size_status == SampleSizeStatus.INSUFFICIENT_SAMPLE:
            if active_policy.reject_on_insufficient_sample:
                status = ValidationStatus.REJECTED
                score = min(score, 45.0)
            else:
                status = ValidationStatus.NOT_RECOMMENDED
                score = min(score, 60.0)
        elif threshold_failed:
            if active_policy.reject_on_threshold_breach:
                status = ValidationStatus.REJECTED
            else:
                status = ValidationStatus.NOT_RECOMMENDED
        else:
            status = ValidationStatus.APPROVED

        asset_class: Literal["EQUITY", "FUTURES", "OPTIONS"] = (
            "FUTURES" if is_futures_symbol(strategy.underlying) else "EQUITY"
        )

        return ValidationResult(
            strategy_name=strategy.name,
            schema_version=strategy.schema_version,
            underlying=strategy.underlying,
            asset_class=asset_class,
            validation_scope=ValidationScope.HISTORICAL,
            status=status,
            validation_score=round(score, 1),
            sample_size_status=sample_size_status,
            historical_vs_theoretical="HISTORICAL",
            metrics={
                "total_trades": perf.total_trades,
                "win_rate": perf.win_rate,
                "net_profit": perf.net_profit,
                "expectancy": perf.expectancy,
                "profit_factor": perf.profit_factor,
                "max_drawdown_pct": perf.max_drawdown_pct,
                "sharpe_ratio": perf.sharpe_ratio,
                "sortino_ratio": perf.sortino_ratio,
                "sqn": perf.sqn,
            },
            failed_gates=failed_gates,
            gate_results=gate_results,
            warnings=warnings,
            suggested_improvements=suggestions,
            policy_name=active_policy.policy_name,
        )

    @classmethod
    def _calculate_validation_score(
        cls,
        perf: Any,
        policy: ValidationPolicy,
        sample_status: SampleSizeStatus,
    ) -> float:
        """Calculate normalized 0-100 composite validation score."""
        score = 0.0

        # Expectancy contribution (0 to 25 pts)
        if perf.expectancy > 0.0:
            score += 25.0

        # Profit Factor contribution (0 to 20 pts)
        if perf.profit_factor is not None and perf.profit_factor > 1.0:
            pf_ratio = min(1.0, perf.profit_factor / max(1.0, policy.min_profit_factor))
            score += pf_ratio * 20.0

        # Drawdown contribution (0 to 20 pts)
        if perf.max_drawdown_pct < policy.max_drawdown_pct:
            dd_ratio = max(0.0, 1.0 - (perf.max_drawdown_pct / policy.max_drawdown_pct))
            score += dd_ratio * 20.0

        # Sharpe contribution (0 to 20 pts)
        if perf.sharpe_ratio is not None and perf.sharpe_ratio > 0.0:
            target_sharpe = policy.min_sharpe_ratio or 1.0
            sharpe_ratio = min(1.0, perf.sharpe_ratio / target_sharpe)
            score += sharpe_ratio * 20.0

        # Sample size contribution (0 to 15 pts)
        if sample_status == SampleSizeStatus.SUFFICIENT_SAMPLE:
            score += 15.0

        return max(0.0, min(100.0, score))
