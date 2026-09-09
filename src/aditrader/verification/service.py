"""Unified institutional Verification Service orchestrating all verification pillars."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from aditrader.backtesting.runner import BacktestResult
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.validation.ast.validator import ASTValidator
from aditrader.validation.institutional.historical import HistoricalStatisticalValidator
from aditrader.validation.institutional.options_payoff import OptionsTheoreticalValidator
from aditrader.validation.models import ValidationStatus
from aditrader.validation.policies import ValidationPolicy, create_institutional_policy
from aditrader.verification.integrity import DataIntegrityChecker
from aditrader.verification.known_answer import KATSuiteResult, KnownAnswerTestEngine
from aditrader.verification.matrix import VerificationMatrixEvaluator
from aditrader.verification.models import (
    EvidenceBundle,
    PillarStatus,
    PillarType,
    VerificationMatrix,
    VerificationPillarResult,
)
from aditrader.verification.reconciliation import ReconciliationChecker

logger = logging.getLogger(__name__)


class VerificationService:
    """Unified service orchestrating verification pillars, KATs, and evidence generation."""

    def __init__(self, policy: ValidationPolicy | None = None) -> None:
        self.policy = policy or create_institutional_policy()

    def evaluate_strategy(
        self,
        strategy: StrategyDSL | dict[str, Any],
        *,
        strategy_id: str | None = None,
        backtest_result: BacktestResult | None = None,
        dataset_path: str | Path | None = None,
        spot_price: float = 24000.0,
        dte_days: float = 7.0,
        evaluation_time: Any | None = None,
        hierarchy: Any | None = None,
    ) -> tuple[VerificationMatrix, EvidenceBundle, KATSuiteResult]:
        """Execute full multi-pillar verification and construct an immutable EvidenceBundle."""
        dsl = (
            strategy if isinstance(strategy, StrategyDSL) else StrategyDSL.model_validate(strategy)
        )
        strat_id = strategy_id or getattr(dsl, "id", None) or f"STRAT-{dsl.name.upper()}"
        is_options = bool(dsl.legs)
        bundle_assumptions: dict[str, Any] = {}

        # ----------------------------------------------------------------------
        # Pillar 1: Static AST Structural Validation
        # ----------------------------------------------------------------------
        ast_res = ASTValidator.validate(dsl)
        ast_passed = ast_res.status == ValidationStatus.APPROVED
        structural_pillar = VerificationPillarResult(
            pillar_name="Static AST Structural Validation",
            pillar_type=PillarType.STRUCTURAL,
            status=PillarStatus.PASS if ast_passed else PillarStatus.FAIL,
            score=ast_res.validation_score,
            details=(
                f"AST schema valid (v{dsl.schema_version}): all indicator parameters, "
                "comparison operators, and bounds strictly conform."
                if ast_passed
                else f"AST structural validation failed: {ast_res.failed_gates}"
            ),
            diagnostics=ast_res.failed_gates,
        )

        # ----------------------------------------------------------------------
        # Pillar 2: Deterministic Known-Answer Testing (KAT)
        # ----------------------------------------------------------------------
        kat_suite = KnownAnswerTestEngine.run_all()
        kat_pillar = VerificationPillarResult(
            pillar_name="Known-Answer Mathematical Benchmarks (KAT)",
            pillar_type=PillarType.KNOWN_ANSWER_TESTS,
            status=PillarStatus.PASS if kat_suite.is_clean else PillarStatus.FAIL,
            score=round((kat_suite.passed_tests / max(1, kat_suite.total_tests)) * 100.0, 1),
            details=(
                f"All {kat_suite.passed_tests}/{kat_suite.total_tests} deterministic analytical test vectors passed bit-for-bit."
                if kat_suite.is_clean
                else f"KAT suite failure: {kat_suite.failed_tests}/{kat_suite.total_tests} test vectors diverged."
            ),
            diagnostics=[
                f"{r.vector_id}: {r.description}" for r in kat_suite.results if not r.passed
            ],
        )

        # ----------------------------------------------------------------------
        # Pillar 3 & 4: Data Integrity and Historical Replay
        # ----------------------------------------------------------------------
        dataset_name = None
        dataset_hash = None

        if is_options:
            # Options derivative strategies: replay is air-gapped per ADR 011
            data_integrity_pillar = VerificationPillarResult(
                pillar_name="Market Data Integrity",
                pillar_type=PillarType.DATA_INTEGRITY,
                status=PillarStatus.NOT_APPLICABLE,
                score=100.0,
                details="Options theoretical validation uses Black-Scholes volatility models (dataset N/A).",
            )
            historical_replay_pillar = VerificationPillarResult(
                pillar_name="Historical Replay Execution",
                pillar_type=PillarType.HISTORICAL_REPLAY,
                status=PillarStatus.NOT_APPLICABLE,
                score=100.0,
                details="Options historical replay is air-gapped per ADR 011 until Phase 9 tick chain simulation.",
            )
            empirical_metrics_pillar = VerificationPillarResult(
                pillar_name="Empirical Statistical Metrics",
                pillar_type=PillarType.EMPIRICAL_METRICS,
                status=PillarStatus.NOT_APPLICABLE,
                score=100.0,
                details="Historical statistical expectancy is strictly omitted for options (ADR 011).",
            )
            reconciliation_pillar = VerificationPillarResult(
                pillar_name="Balance Sheet Reconciliation",
                pillar_type=PillarType.RECONCILIATION,
                status=PillarStatus.NOT_APPLICABLE,
                score=100.0,
                details="Balance sheet reconciliation applies to executed simulation ledgers (N/A).",
            )

            # Pillar 5: Theoretical Options Payoff Analysis
            theo_res = OptionsTheoreticalValidator.validate(
                strategy=dsl,
                policy=self.policy,
                spot_price=spot_price,
                dte_days=dte_days,
                evaluation_time=evaluation_time,
                hierarchy=hierarchy,
            )
            theo_passed = theo_res.status == ValidationStatus.APPROVED
            max_p = theo_res.metrics.get("max_profit")
            max_l = theo_res.metrics.get("max_loss")
            p_str = f"₹{max_p:.2f}" if max_p is not None else "Unlimited"
            l_str = f"₹{max_l:.2f}" if max_l is not None else "Unlimited"
            bundle_assumptions["theoretical_metrics"] = {
                "max_profit": max_p,
                "max_loss": max_l,
                "risk_reward_ratio": theo_res.metrics.get("risk_reward_ratio"),
                "is_defined_risk": theo_res.metrics.get("is_defined_risk"),
            }
            options_theoretical_pillar = VerificationPillarResult(
                pillar_name="Options Theoretical Payoff & Greeks",
                pillar_type=PillarType.OPTIONS_THEORETICAL,
                status=PillarStatus.PASS if theo_passed else PillarStatus.FAIL,
                score=theo_res.validation_score,
                details=(
                    f"Theoretical payoff verified: Defined risk={theo_res.metrics.get('is_defined_risk')}, "
                    f"Max Profit={p_str}, Max Loss={l_str}"
                    if theo_passed
                    else f"Theoretical risk gate veto: {theo_res.failed_gates}"
                ),
                diagnostics=theo_res.failed_gates,
            )

        else:
            # Linear Equities or Futures Strategy Path
            options_theoretical_pillar = VerificationPillarResult(
                pillar_name="Options Theoretical Payoff & Greeks",
                pillar_type=PillarType.OPTIONS_THEORETICAL,
                status=PillarStatus.NOT_APPLICABLE,
                score=100.0,
                details="Linear asset (Equity/Futures) does not use non-linear option payoff models.",
            )

            if dataset_path and Path(dataset_path).is_file():
                ds_path = Path(dataset_path)
                dataset_name = ds_path.name
                try:
                    with open(ds_path, "rb") as f:
                        dataset_hash = "sha256:" + hashlib.sha256(f.read()).hexdigest()
                except Exception:
                    dataset_hash = None
                # Audit data integrity
                di_report = DataIntegrityChecker.audit_csv_file(ds_path)
                data_integrity_pillar = VerificationPillarResult(
                    pillar_name="Market Data Integrity",
                    pillar_type=PillarType.DATA_INTEGRITY,
                    status=PillarStatus.PASS if di_report.is_valid else PillarStatus.FAIL,
                    score=100.0 if di_report.is_valid else 0.0,
                    details=di_report.details,
                    diagnostics=di_report.errors[:10],
                )
            else:
                data_integrity_pillar = VerificationPillarResult(
                    pillar_name="Market Data Integrity",
                    pillar_type=PillarType.DATA_INTEGRITY,
                    status=PillarStatus.NOT_RUN,
                    score=0.0,
                    details="No verified CSV dataset was attached to validate data integrity.",
                )

            if backtest_result is not None:
                trade_count = len(backtest_result.trades)
                historical_replay_pillar = VerificationPillarResult(
                    pillar_name="Historical Replay Execution",
                    pillar_type=PillarType.HISTORICAL_REPLAY,
                    status=PillarStatus.PASS,
                    score=100.0,
                    details=(
                        f"Executed deterministic replay on {backtest_result.bar_count} bars; "
                        f"{trade_count} trade execution(s) simulated."
                    ),
                )

                hist_val_res = HistoricalStatisticalValidator.validate(
                    strategy=dsl,
                    result=backtest_result,
                    policy=self.policy,
                )
                emp_passed = hist_val_res.status == ValidationStatus.APPROVED
                perf = backtest_result.performance
                bundle_assumptions["baseline_metrics"] = {
                    "expectancy": perf.expectancy,
                    "mathematical_expectancy": perf.expectancy,
                    "profit_factor": perf.profit_factor,
                    "max_drawdown_pct": perf.max_drawdown_pct,
                    "max_drawdown_amount": perf.max_drawdown_amount,
                    "sharpe_ratio": perf.sharpe_ratio,
                    "sortino_ratio": perf.sortino_ratio,
                    "sqn": perf.sqn,
                    "win_rate": perf.win_rate,
                    "net_profit": perf.net_profit,
                }
                empirical_metrics_pillar = VerificationPillarResult(
                    pillar_name="Empirical Statistical Metrics",
                    pillar_type=PillarType.EMPIRICAL_METRICS,
                    status=PillarStatus.PASS if emp_passed else PillarStatus.FAIL,
                    score=hist_val_res.validation_score,
                    details=(
                        f"Expectancy=₹{perf.expectancy:.2f}, PF={perf.profit_factor or 0.0:.2f}, "
                        f"Max DD={perf.max_drawdown_pct * 100:.2f}%, Win Rate={perf.win_rate * 100:.1f}%"
                        if emp_passed
                        else f"Statistical gate rejection: {hist_val_res.failed_gates}"
                    ),
                    diagnostics=hist_val_res.failed_gates,
                )

                # Reconciliation
                recon_rep = ReconciliationChecker.audit_session(
                    starting_capital=perf.starting_equity,
                    ending_equity=perf.ending_equity,
                    net_profit=perf.net_profit,
                    positions=backtest_result.terminal_positions,
                    trades=backtest_result.trades,
                    unrealized_pnl=backtest_result.terminal_unrealized_pnl,
                )
                reconciliation_pillar = VerificationPillarResult(
                    pillar_name="Balance Sheet Reconciliation",
                    pillar_type=PillarType.RECONCILIATION,
                    status=PillarStatus.PASS if recon_rep.is_reconciled else PillarStatus.FAIL,
                    score=100.0 if recon_rep.is_reconciled else 0.0,
                    details=recon_rep.details,
                    diagnostics=[] if recon_rep.is_reconciled else [recon_rep.details],
                )
            else:
                historical_replay_pillar = VerificationPillarResult(
                    pillar_name="Historical Replay Execution",
                    pillar_type=PillarType.HISTORICAL_REPLAY,
                    status=PillarStatus.NOT_RUN,
                    score=0.0,
                    details="Historical replay has not been run. Requires CSV dataset.",
                )
                empirical_metrics_pillar = VerificationPillarResult(
                    pillar_name="Empirical Statistical Metrics",
                    pillar_type=PillarType.EMPIRICAL_METRICS,
                    status=PillarStatus.NOT_RUN,
                    score=0.0,
                    details="No empirical backtest result available to verify statistical expectancy.",
                )
                reconciliation_pillar = VerificationPillarResult(
                    pillar_name="Balance Sheet Reconciliation",
                    pillar_type=PillarType.RECONCILIATION,
                    status=PillarStatus.NOT_RUN,
                    score=0.0,
                    details="No transaction ledger available to reconcile balance sheet.",
                )

        # ----------------------------------------------------------------------
        # Synthesize Verification Matrix
        # ----------------------------------------------------------------------
        matrix = VerificationMatrixEvaluator.compute_matrix(
            strategy_id=strat_id,
            strategy_name=dsl.name,
            strategy_dsl=dsl,
            structural_pillar=structural_pillar,
            data_integrity_pillar=data_integrity_pillar,
            known_answer_pillar=kat_pillar,
            historical_replay_pillar=historical_replay_pillar,
            empirical_metrics_pillar=empirical_metrics_pillar,
            options_theoretical_pillar=options_theoretical_pillar,
            reconciliation_pillar=reconciliation_pillar,
        )

        ledger_hash: str | None = None
        event_stream_hash: str | None = None
        if backtest_result is not None:
            ledger_hash = getattr(backtest_result, "trade_ledger_merkle_root", None) or getattr(
                backtest_result, "ledger_hash", None
            )
            event_stream_hash = getattr(
                backtest_result, "event_stream_merkle_root", None
            ) or getattr(backtest_result, "event_stream_hash", None)

        bundle = EvidenceBundle.create(
            bundle_id=f"EV-{uuid4().hex[:12].upper()}",
            strategy_id=strat_id,
            strategy_name=dsl.name,
            strategy_hash=matrix.strategy_hash,
            dataset_name=dataset_name,
            dataset_hash=dataset_hash,
            verification_matrix=matrix,
            overall_status=matrix.overall_status,
            kat_passed=kat_suite.passed_tests,
            kat_total=kat_suite.total_tests,
            engine_version="1.0.0",
            assumptions=bundle_assumptions,
            ledger_hash=ledger_hash,
            event_stream_hash=event_stream_hash,
        )

        return matrix, bundle, kat_suite
