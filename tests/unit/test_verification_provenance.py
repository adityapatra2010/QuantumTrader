"""Deterministic Verification & Calculation Provenance Subsystem Tests.

Covers:
- Deterministic Known-Answer Testing (KAT) analytical vectors
- Market Data Integrity checks (NSE hours, price envelope, duplicate detection)
- Step-by-step Calculation Provenance tracing
- Reproducibility Engine (stored vs fresh recalculation & mismatch detection)
- Balance Sheet Reconciliation identities
- Multi-Pillar Verification Matrix evaluation with fail-closed precedence
- Cryptographic SHA-256 EvidenceBundle tamper digest verification
- REST API endpoints for verification and recalculation
"""

import json
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from aditrader.core.models.enums import OrderSide
from aditrader.core.models.execution import Position, Trade
from aditrader.core.models.market_data import Bar
from aditrader.strategy.library.registry import StrategyRegistry
from aditrader.verification.integrity import DataIntegrityChecker
from aditrader.verification.known_answer import KnownAnswerTestEngine
from aditrader.verification.matrix import VerificationMatrixEvaluator
from aditrader.verification.models import (
    EvidenceBundle,
    OverallVerificationStatus,
    PillarStatus,
    PillarType,
    VerificationMatrix,
    VerificationPillarResult,
)
from aditrader.verification.reconciliation import ReconciliationChecker
from aditrader.verification.reproducer import ReproducibilityEngine
from aditrader.verification.tolerances import (
    TOLERANCE_DIMENSIONLESS,
    TOLERANCE_GREEKS,
    TOLERANCE_MONETARY,
    TOLERANCE_PERCENTAGE,
    is_close_monetary,
    is_close_ratio,
)
from aditrader.verification.trace import ProvenanceTracer
from aditrader.web.server import DashboardServer


def _make_request(
    url: str, method: str = "GET", data: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any], dict[str, str]]:
    req_data = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if req_data else {}
    req = Request(url, data=req_data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            resp_headers = dict(resp.headers)
            return resp.status, resp_body, resp_headers
    except HTTPError as e:
        err_body = json.loads(e.read().decode("utf-8"))
        return e.code, err_body, dict(e.headers)


@pytest.fixture(scope="module")
def web_server() -> Any:
    """Spins up a background DashboardServer on an ephemeral port."""
    server = DashboardServer(host="127.0.0.1", port=0)
    server.start(background=True)
    yield server
    server.stop()


# ==============================================================================
# 1. Tolerances & Precision Standards
# ==============================================================================


def test_tolerances_and_precision_helpers() -> None:
    """Verify monetary paisa rounding and dimensionless ratio tolerances."""
    assert TOLERANCE_MONETARY == 0.01
    assert TOLERANCE_DIMENSIONLESS == 1e-4
    assert TOLERANCE_PERCENTAGE == 1e-4
    assert TOLERANCE_GREEKS == 1e-4

    assert is_close_monetary(100.004, 100.009)
    assert not is_close_monetary(100.00, 100.02)

    assert is_close_ratio(1.50004, 1.50008)
    assert not is_close_ratio(1.500, 1.501)


# ==============================================================================
# 2. Known-Answer Testing (KAT) Suite
# ==============================================================================


def test_known_answer_suite_execution() -> None:
    """Verify all precomputed analytical vectors pass without exception."""
    suite = KnownAnswerTestEngine.run_all()
    assert suite.total_tests == 37
    assert suite.passed_tests == 37
    assert suite.failed_tests == 0
    assert suite.is_clean is True
    assert len(suite.results) == 37

    categories = {r.category for r in suite.results}
    assert "PNL_ACCOUNTING" in categories
    assert "STATUTORY_TAXES" in categories
    assert "LOT_SIZING" in categories
    assert "BLACK_SCHOLES" in categories
    assert "OPTIONS_PAYOFF" in categories
    assert "PERFORMANCE_ANALYTICS" in categories
    assert "STATISTICAL_EDGES" in categories
    assert "DEFENSIVE_GUARDS" in categories

    # Verify defensive guard tests explicitly proved fail-closed detection
    guard_results = [r for r in suite.results if r.category == "DEFENSIVE_GUARDS"]
    assert len(guard_results) >= 2
    for gr in guard_results:
        assert gr.passed is True
        assert gr.observed_output == gr.expected_output


# ==============================================================================
# 3. Market Data Integrity Verification
# ==============================================================================


def test_market_data_integrity_checker() -> None:
    """Verify DataIntegrityChecker identifies session rules, envelopes, and duplicate timestamps."""
    sample_csv = Path("data/nifty_sample.csv")
    if sample_csv.exists():
        report = DataIntegrityChecker.audit_csv_file(sample_csv)
        assert report.total_records > 0
        assert report.envelope_violations_count == 0
        assert report.negative_price_count == 0

    # 1. Valid bars
    b1 = Bar(
        timestamp=datetime(2026, 9, 8, 9, 15, tzinfo=UTC),
        symbol="NIFTY",
        open=24000.0,
        high=24050.0,
        low=23950.0,
        close=24020.0,
        volume=1000,
    )
    b2 = Bar(
        timestamp=datetime(2026, 9, 8, 9, 16, tzinfo=UTC),
        symbol="NIFTY",
        open=24020.0,
        high=24080.0,
        low=24010.0,
        close=24060.0,
        volume=1200,
    )
    valid_rep = DataIntegrityChecker.audit_bars([b1, b2], source_identifier="test_valid")
    assert valid_rep.is_valid is True

    # 2. Duplicate timestamp detection
    dup_rep = DataIntegrityChecker.audit_bars([b1, b1], source_identifier="test_dup")
    assert dup_rep.is_valid is False
    assert dup_rep.duplicates_count == 1


# ==============================================================================
# 4. Calculation Provenance Tracing
# ==============================================================================


def test_provenance_tracer() -> None:
    """Verify step-by-step mathematical calculation provenance generation."""
    prov = ProvenanceTracer.trace_trade(
        trade_id="TR-101",
        symbol="NIFTY",
        side=OrderSide.BUY,
        qty=50,
        entry_price=23950.0,
        exit_price=24000.0,
        entry_timestamp=datetime.now(UTC).isoformat(),
        exit_timestamp=datetime.now(UTC).isoformat(),
        strategy_id="trend_v1",
        strategy_hash="sha256:abc",
    )
    assert prov.target_metric == "NET_REALIZED_PNL"
    assert len(prov.intermediate_steps) >= 5
    assert prov.final_value is not None

    step_names = [s.step_name for s in prov.intermediate_steps]
    assert "GROSS_REALIZED_PNL" in step_names
    assert "ENTRY_STATUTORY_CHARGES" in step_names
    assert "NET_REALIZED_PNL" in step_names

    # Trace aggregate expectancy
    exp_prov = ProvenanceTracer.trace_expectancy(
        trade_pnls=[500.0, -200.0, 300.0, -100.0],
        strategy_id="trend_v1",
        strategy_hash="sha256:abc",
    )
    assert exp_prov.target_metric == "MATHEMATICAL_EXPECTANCY"
    assert len(exp_prov.intermediate_steps) >= 3


# ==============================================================================
# 5. Reproducibility Engine & Mismatch Detection
# ==============================================================================


def test_reproducibility_engine() -> None:
    """Verify fresh vs stored re-evaluation catches mismatches and tolerates numerical precision."""
    # 1. Compare metrics (mathematical_expectancy is INR currency with ₹0.01 / 1 paisa tolerance)
    c_diverged = ReproducibilityEngine.compare_metric("mathematical_expectancy", 120.0, 120.02)
    assert c_diverged.is_reproduced is False  # 0.02 > 0.01
    c_close = ReproducibilityEngine.compare_metric("mathematical_expectancy", 120.0, 120.005)
    assert c_close.is_reproduced is True  # 0.005 <= 0.01

    c_paisa = ReproducibilityEngine.compare_metric("net_profit", 10000.0, 10000.008)
    assert c_paisa.is_reproduced is True

    # 2. Blocked when dataset missing
    blocked = ReproducibilityEngine.audit_metrics_reproducibility(
        strategy_id="strat-1",
        stored_metrics={},
        trade_pnls=[],
        equity_curve=[],
        dataset_available=False,
        dataset_path_str="data/missing.csv",
    )
    assert blocked.overall_reproduced is False
    assert "BLOCKED" in (blocked.reason or "")


# ==============================================================================
# 6. Balance Sheet Reconciliation
# ==============================================================================


def test_reconciliation_checker() -> None:
    """Verify balance sheet equality and trade decomposition."""
    pos = Position(
        symbol="NIFTY",
        qty=50,
        buy_avg_price=24000.0,
        sell_avg_price=0.0,
        realized_pnl=5000.0,
        unrealized_pnl=5000.0,
        updated_at=datetime.now(UTC),
    )
    t1 = Trade(
        trade_id="TR-1",
        order_id="ORD-1",
        symbol="NIFTY",
        side=OrderSide.BUY,
        qty=50,
        fill_price=24000.0,
        timestamp=datetime.now(UTC),
        charges=50.0,
        stt=20.0,
    )

    # 1. Correctly reconciled ledger (charges = 50 + 20 = 70; net profit = 5000 + 5000 - 70 = 9930)
    report = ReconciliationChecker.audit_session(
        starting_capital=1_000_000.0,
        ending_equity=1_009_930.0,
        net_profit=9_930.0,
        positions=[pos],
        trades=[t1],
        realized_roundtrip_pnls=[5000.0],
        unrealized_pnl=5000.0,
    )
    assert report.is_reconciled is True
    assert report.equity_discrepancy == 0.0

    # 2. Sham detection: if caller claims net_profit=10000 without deducting 70 charges, must fail
    bad_report = ReconciliationChecker.audit_session(
        starting_capital=1_000_000.0,
        ending_equity=1_010_000.0,
        net_profit=10_000.0,
        positions=[pos],
        trades=[t1],
        realized_roundtrip_pnls=[5000.0],
        unrealized_pnl=5000.0,
    )
    assert bad_report.is_reconciled is False
    assert "Net profit mismatch" in bad_report.details


# ==============================================================================
# 7. Verification Matrix & Fail-Closed Precedence
# ==============================================================================


def test_verification_matrix_fail_closed_precedence() -> None:
    """Verify strict fail-closed precedence: BLOCKED > FAIL > STALE > INCOMPLETE > PASS."""
    p_pass = VerificationPillarResult(
        pillar_name="P1",
        pillar_type=PillarType.STRUCTURAL,
        status=PillarStatus.PASS,
        details="passed",
    )
    p_fail = VerificationPillarResult(
        pillar_name="P2",
        pillar_type=PillarType.EMPIRICAL_METRICS,
        status=PillarStatus.FAIL,
        details="failed",
    )
    p_incomp = VerificationPillarResult(
        pillar_name="P3",
        pillar_type=PillarType.HISTORICAL_REPLAY,
        status=PillarStatus.INCOMPLETE,
        details="incomplete",
    )
    p_blocked = VerificationPillarResult(
        pillar_name="P4",
        pillar_type=PillarType.DATA_INTEGRITY,
        status=PillarStatus.BLOCKED,
        details="blocked",
    )
    p_opt_na = VerificationPillarResult(
        pillar_name="P_hist",
        pillar_type=PillarType.HISTORICAL_REPLAY,
        status=PillarStatus.NOT_APPLICABLE,
        details="not applicable",
    )

    reg = StrategyRegistry()
    linear_strat = reg.get("tpl-nifty-intraday-trend-v1")
    options_strat = reg.get("tpl-nifty-ce-premium-ladder-v1")
    linear_dsl = linear_strat.dsl_definition
    options_dsl = options_strat.dsl_definition

    # 1. BLOCKED overrides everything
    m1 = VerificationMatrixEvaluator.compute_matrix(
        strategy_id="strat-1",
        strategy_name="Linear",
        strategy_dsl=linear_dsl,
        structural_pillar=p_pass,
        data_integrity_pillar=p_blocked,
        known_answer_pillar=p_pass,
        historical_replay_pillar=p_incomp,
        empirical_metrics_pillar=p_fail,
        options_theoretical_pillar=p_opt_na,
        reconciliation_pillar=p_pass,
    )
    assert m1.overall_status == OverallVerificationStatus.BLOCKED

    # 2. FAIL overrides INCOMPLETE
    m2 = VerificationMatrixEvaluator.compute_matrix(
        strategy_id="strat-1",
        strategy_name="Linear",
        strategy_dsl=linear_dsl,
        structural_pillar=p_pass,
        data_integrity_pillar=p_pass,
        known_answer_pillar=p_pass,
        historical_replay_pillar=p_incomp,
        empirical_metrics_pillar=p_fail,
        options_theoretical_pillar=p_opt_na,
        reconciliation_pillar=p_pass,
    )
    assert m2.overall_status == OverallVerificationStatus.FAIL

    # 3. INCOMPLETE if unrun/incomplete without failures
    m3 = VerificationMatrixEvaluator.compute_matrix(
        strategy_id="strat-1",
        strategy_name="Linear",
        strategy_dsl=linear_dsl,
        structural_pillar=p_pass,
        data_integrity_pillar=p_pass,
        known_answer_pillar=p_pass,
        historical_replay_pillar=p_incomp,
        empirical_metrics_pillar=p_incomp,
        options_theoretical_pillar=p_opt_na,
        reconciliation_pillar=p_pass,
    )
    assert m3.overall_status == OverallVerificationStatus.INCOMPLETE

    # 4. PASS when all required pass
    m4 = VerificationMatrixEvaluator.compute_matrix(
        strategy_id="strat-1",
        strategy_name="Linear",
        strategy_dsl=linear_dsl,
        structural_pillar=p_pass,
        data_integrity_pillar=p_pass,
        known_answer_pillar=p_pass,
        historical_replay_pillar=p_pass,
        empirical_metrics_pillar=p_pass,
        options_theoretical_pillar=p_opt_na,
        reconciliation_pillar=p_pass,
    )
    assert m4.overall_status == OverallVerificationStatus.PASS

    # 5. Options with theoretical pass earns THEORETICAL_PASS
    m5 = VerificationMatrixEvaluator.compute_matrix(
        strategy_id="strat-opt",
        strategy_name="Options Spread",
        strategy_dsl=options_dsl,
        structural_pillar=p_pass,
        data_integrity_pillar=p_opt_na,
        known_answer_pillar=p_pass,
        historical_replay_pillar=p_opt_na,
        empirical_metrics_pillar=p_opt_na,
        options_theoretical_pillar=p_pass,
        reconciliation_pillar=p_opt_na,
    )
    assert m5.overall_status == OverallVerificationStatus.THEORETICAL_PASS


# ==============================================================================
# 8. Evidence Bundle Cryptographic SHA-256 Digest Verification
# ==============================================================================


def test_evidence_bundle_tamper_detection() -> None:
    """Verify canonical tamper hash changes if any critical audit field is altered."""
    p = VerificationPillarResult(
        pillar_name="P",
        pillar_type=PillarType.STRUCTURAL,
        status=PillarStatus.PASS,
        details="passed",
    )
    matrix = VerificationMatrix(
        strategy_name="Test Strategy",
        strategy_hash="sha256:12345",
        overall_status=OverallVerificationStatus.PASS,
        strategy_id="test_strat",
        is_options=False,
        structural=p,
        data_integrity=p,
        known_answer_tests=p,
        historical_replay=p,
        empirical_metrics=p,
        options_theoretical=p,
        reconciliation=p,
    )
    bundle = EvidenceBundle.create(
        bundle_id="EB-TEST-001",
        strategy_id="test_strat",
        strategy_name="Test Strategy",
        strategy_hash="sha256:12345",
        verification_matrix=matrix,
        overall_status=OverallVerificationStatus.PASS,
        kat_passed=37,
        kat_total=37,
    )
    assert bundle.verify_tamper_hash() is True

    # Tamper with the bundle
    tampered_bundle = bundle.model_copy(update={"overall_status": OverallVerificationStatus.FAIL})
    assert tampered_bundle.verify_tamper_hash() is False


# ==============================================================================
# 9. REST API Verification & Recalculation Endpoints
# ==============================================================================


def test_verification_api_endpoints(web_server: DashboardServer) -> None:
    """Verify /api/verify/kat, /api/verify/trace, /api/verify/recalculate, and evidence endpoints."""
    base_url = web_server.url

    # 1. GET /api/verify/kat
    status, kat_rep, _ = _make_request(f"{base_url}/api/verify/kat")
    assert status == HTTPStatus.OK
    assert kat_rep["total_tests"] == 37
    assert kat_rep["is_clean"] is True
    assert len(kat_rep["results"]) == 37

    # 2. GET /api/verify/trace
    status, trace_rep, _ = _make_request(
        f"{base_url}/api/verify/trace?metric=mathematical_expectancy&strategy_id=tpl-nifty-intraday-trend-v1"
    )
    assert status == HTTPStatus.OK
    assert trace_rep["target_metric"] == "MATHEMATICAL_EXPECTANCY"
    assert "intermediate_steps" in trace_rep
    assert len(trace_rep["intermediate_steps"]) > 0

    # 3. POST /api/verify/recalculate
    status, recalc_rep, _ = _make_request(
        f"{base_url}/api/verify/recalculate",
        method="POST",
        data={
            "strategy_id": "tpl-nifty-intraday-trend-v1",
            "dataset_path": "data/nifty_sample.csv",
        },
    )
    assert status == HTTPStatus.OK
    assert "is_reproducible" in recalc_rep
    assert recalc_rep["is_reproducible"] is True
    assert "comparisons" in recalc_rep
    assert "bundle_id" in recalc_rep
    assert "tamper_hash" in recalc_rep
    assert "overall_verification_status" in recalc_rep
