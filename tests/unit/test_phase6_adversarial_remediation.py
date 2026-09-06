"""Adversarial regression tests verifying remediations for Findings 1 through 10.

Ensures that:
1. Naked short puts are classified as undefined risk and rejected by institutional gates.
2. Stock symbols containing 3-letter month substrings (MARUTI, SUNPHARMA) are not swallowed as expiry hints.
3. Strike intervals and lot sizes dynamically resolve from contract metadata and authoritative specs.
4. Fallback matching does not ignore explicit query constraints (e.g. wrong option type or non-existent strike).
5. Instrument ranking deterministically orders active contracts ahead of expired ones.
6. ResearchPolicy tolerates profit factor < 1.0 without triggering an unconditional hard floor.
7. Equities with 'FUT' substrings (e.g. FUTURECONSUMER) are correctly classified as EQUITY.
8. Out-of-sample (OOS) validation verifies temporal disjointness and rejects lookahead data leakage.
9. Theoretical options payoff validation supports deterministic evaluation timestamps.
10. Ambiguous token IDs across exchanges require explicit exchange disambiguation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from aditrader.backtesting.analytics.metrics import PerformanceReport
from aditrader.backtesting.runner import BacktestResult
from aditrader.core.models.enums import OrderSide
from aditrader.data.adapters.base import ContractMetadata
from aditrader.data.instruments.index import InstrumentIndex
from aditrader.data.instruments.matcher import parse_query, score_contract
from aditrader.data.instruments.models import MatchQuality
from aditrader.data.instruments.specs import is_futures_symbol, resolve_contract_specs
from aditrader.options.models import OptionLeg, OptionStrategy
from aditrader.options.payoff import calculate_strategy_payoff
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.validation.ast.validator import ASTValidator
from aditrader.validation.institutional.historical import HistoricalStatisticalValidator
from aditrader.validation.institutional.options_payoff import OptionsTheoreticalValidator
from aditrader.validation.models import GateSeverity, ValidationStatus
from aditrader.validation.policies import (
    create_institutional_policy,
    create_research_policy,
)

# ==============================================================================
# Helper Factories
# ==============================================================================


def _build_naked_short_put(underlying: str = "NIFTY") -> StrategyDSL:
    return StrategyDSL(
        schema_version="1.0",
        name="Naked Short Put",
        underlying=underlying,
        timeframe="15m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.LESS_THAN,
                    threshold=30.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.SELL,
                strike_offset=-1,
                lots=1,
            )
        ],
    )


def _build_bull_put_spread(underlying: str = "NIFTY") -> StrategyDSL:
    return StrategyDSL(
        schema_version="1.0",
        name="Bull Put Spread",
        underlying=underlying,
        timeframe="15m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.LESS_THAN,
                    threshold=30.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.SELL,
                strike_offset=-1,
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.BUY,
                strike_offset=-3,
                lots=1,
            ),
        ],
    )


def _create_mock_backtest_result(
    profit_factor: float,
    timestamps: list[datetime],
    expectancy: float = 120.0,
    sharpe: float = 1.8,
) -> BacktestResult:
    gross_profit = 10000.0 * profit_factor
    gross_loss = 10000.0
    net_profit = gross_profit - gross_loss
    perf = PerformanceReport(
        starting_equity=100000.0,
        ending_equity=100000.0 + net_profit,
        net_profit=net_profit,
        return_pct=net_profit / 100000.0,
        total_trades=50,
        winning_trades=30,
        losing_trades=20,
        win_rate=0.60,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown_amount=5000.0,
        max_drawdown_pct=0.05,
        sharpe_ratio=sharpe,
        sortino_ratio=2.5,
        sqn=3.0,
    )
    return BacktestResult(
        strategy_name="Mock Strategy",
        underlying="RELIANCE",
        bar_count=500,
        equity_curve=[100000.0 + i * 100.0 for i in range(len(timestamps))],
        equity_timestamps=timestamps,
        performance=perf,
    )


# ==============================================================================
# Finding 1 Tests: Naked Short Put Defined Risk Loophole
# ==============================================================================


def test_remediation_finding_1_naked_short_put_rejected_by_institutional_policy() -> None:
    """Naked Short Put must be recognized as having infinite loss and rejected by institutional gates."""
    dsl = _build_naked_short_put()
    res = OptionsTheoreticalValidator.validate(dsl, policy=create_institutional_policy())

    assert res.status == ValidationStatus.REJECTED
    assert "DEFINED_RISK_ARCHITECTURE" in res.failed_gates

    # Verify gate result details
    gate = next(g for g in res.gate_results if g.gate_name == "DEFINED_RISK_ARCHITECTURE")
    assert gate.passed is False
    assert gate.severity == GateSeverity.HARD_FLOOR
    assert gate.observed_value is False


def test_remediation_finding_1_payoff_slope_detects_short_put_infinite_loss() -> None:
    """Payoff curve calculator must identify left-side unbounded loss for short puts."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    short_put = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="PE",
        side=OrderSide.SELL,
        qty=25,
        entry_price=100.0,
        lot_size=25,
    )
    strat = OptionStrategy(id="SP-01", name="Short Put", legs=[short_put])
    price_range = [float(x) for x in range(20000, 26000, 100)]
    _, summary = calculate_strategy_payoff(strat, price_range)

    # Max loss on unhedged short put must expand to infinity
    assert summary.max_loss is None
    assert summary.max_profit == 2500.0


def test_remediation_finding_1_hedged_bull_put_spread_approved() -> None:
    """Hedged Bull Put Spread must pass defined risk validation."""
    dsl = _build_bull_put_spread()
    res = OptionsTheoreticalValidator.validate(dsl, policy=create_institutional_policy())

    assert res.status == ValidationStatus.APPROVED
    assert "DEFINED_RISK_ARCHITECTURE" not in res.failed_gates
    gate = next(g for g in res.gate_results if g.gate_name == "DEFINED_RISK_ARCHITECTURE")
    assert gate.passed is True


# ==============================================================================
# Finding 2 Tests: Ticker Substring Poisoning in Query Parser
# ==============================================================================


@pytest.mark.parametrize(
    "query,expected_underlying",
    [
        ("MARUTI", "MARUTI"),
        ("MARUTI 12000 CE", "MARUTI"),
        ("SUNPHARMA", "SUNPHARMA"),
        ("AUROPHARMA", "AUROPHARMA"),
        ("JUBLPHARMA", "JUBLPHARMA"),
        ("MAYURUNIQ", "MAYURUNIQ"),
        ("DECCANCE", "DECCANCE"),
    ],
)
def test_remediation_finding_2_stock_names_not_swallowed_as_expiry_hints(
    query: str, expected_underlying: str
) -> None:
    """Stock symbols containing 3-letter month substrings must not be parsed as expiry hints."""
    parsed = parse_query(query)
    assert parsed.underlying == expected_underlying
    assert parsed.expiry_hint is None


def test_remediation_finding_2_legitimate_expiry_hints_parsed_correctly() -> None:
    """Valid expiry dates and month codes must continue to parse as expiry hints."""
    p1 = parse_query("NIFTY 26DEC 24000 CE")
    assert p1.underlying == "NIFTY"
    assert p1.expiry_hint == "26DEC"
    assert p1.strike == 24000.0
    assert p1.option_type == "CE"

    p2 = parse_query("BANKNIFTY 24DEC FUT")
    assert p2.underlying == "BANKNIFTY"
    assert p2.expiry_hint == "24DEC"
    assert p2.is_future is True


# ==============================================================================
# Finding 3 Tests: Dynamic Contract Specs Resolution
# ==============================================================================


def test_remediation_finding_3_dynamic_contract_specs() -> None:
    """Strike intervals and lot sizes must adhere to authoritative specs for major assets."""
    step, lot = resolve_contract_specs("NIFTY")
    assert step == 50.0
    assert lot == 25

    step, lot = resolve_contract_specs("BANKNIFTY")
    assert step == 100.0
    assert lot == 15

    step, lot = resolve_contract_specs("MIDCPNIFTY")
    assert step == 25.0
    assert lot == 50

    step, lot = resolve_contract_specs("RELIANCE")
    assert step == 20.0
    assert lot == 250

    step, lot = resolve_contract_specs("TCS")
    assert step == 20.0
    assert lot == 175


def test_remediation_finding_3_options_validator_uses_underlying_specs() -> None:
    """OptionsTheoreticalValidator must use asset-specific strike step and lot size."""
    dsl_bnf = _build_bull_put_spread(underlying="BANKNIFTY")
    res_bnf = OptionsTheoreticalValidator.validate(
        dsl_bnf, spot_price=51000.0, policy=create_institutional_policy()
    )
    # Bank Nifty defined risk spread must be approved
    assert res_bnf.status == ValidationStatus.APPROVED


# ==============================================================================
# Finding 4 Tests: Spurious Derivative Fallback Matching
# ==============================================================================


def test_remediation_finding_4_explicit_option_type_not_ignored() -> None:
    """When query specifies CE, PE contracts must not match as STRUCTURED_DERIVATIVE."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    pe_contract = ContractMetadata(
        symbol="NIFTY24DEC24000PE",
        trading_symbol="NIFTY 26-DEC-2024 PE 24000",
        exchange="NFO",
        instrument_type="OPTIDX",
        lot_size=25,
        tick_size=0.05,
        token="45002",
        strike_price=24000.0,
        expiry_date=exp,
        option_type="PE",
    )
    parsed = parse_query("NIFTY 24000 CE")
    scored = score_contract(pe_contract, "NIFTY 24000 CE", parsed, "NIFTY")

    # If it matches, it must NOT be structured derivative
    if scored is not None:
        assert scored[1] != MatchQuality.STRUCTURED_DERIVATIVE


def test_remediation_finding_4_nonexistent_strike_not_matched_as_structured() -> None:
    """When query specifies a non-existent strike, contracts with other strikes must not match as STRUCTURED_DERIVATIVE."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    ce_contract = ContractMetadata(
        symbol="NIFTY24DEC24000CE",
        trading_symbol="NIFTY 26-DEC-2024 CE 24000",
        exchange="NFO",
        instrument_type="OPTIDX",
        lot_size=25,
        tick_size=0.05,
        token="45001",
        strike_price=24000.0,
        expiry_date=exp,
        option_type="CE",
    )
    parsed = parse_query("NIFTY 99999 CE")
    scored = score_contract(ce_contract, "NIFTY 99999 CE", parsed, "NIFTY")

    if scored is not None:
        assert scored[1] != MatchQuality.STRUCTURED_DERIVATIVE


# ==============================================================================
# Finding 5 Tests: Expired Contract Inversion in Ranking
# ==============================================================================


def test_remediation_finding_5_active_contracts_rank_ahead_of_expired() -> None:
    """Active contracts must rank ahead of expired contracts with equal query scores."""
    exp_past = datetime(2024, 11, 28, 15, 30, tzinfo=UTC)
    exp_active = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)

    c_past = ContractMetadata(
        symbol="NIFTY24NOVFUT",
        trading_symbol="NIFTY 28-NOV-2024 FUT",
        exchange="NFO",
        instrument_type="FUTIDX",
        lot_size=25,
        tick_size=0.05,
        token="45001",
        expiry_date=exp_past,
    )
    c_active = ContractMetadata(
        symbol="NIFTY24DECFUT",
        trading_symbol="NIFTY 26-DEC-2024 FUT",
        exchange="NFO",
        instrument_type="FUTIDX",
        lot_size=25,
        tick_size=0.05,
        token="45002",
        expiry_date=exp_active,
    )

    idx = InstrumentIndex([c_past, c_active])
    # Evaluate at 2024-12-01 (when Nov is expired and Dec is active)
    results = idx.search("NIFTY FUT", evaluation_time=datetime(2024, 12, 1, 10, 0, tzinfo=UTC))

    assert len(results) == 2
    assert results[0].contract.symbol == "NIFTY24DECFUT"
    assert results[1].contract.symbol == "NIFTY24NOVFUT"


# ==============================================================================
# Finding 6 Tests: Research Policy Profit Factor Tolerance
# ==============================================================================


def test_remediation_finding_6_research_policy_tolerates_low_profit_factor() -> None:
    """Under ResearchPolicy, a strategy with profit factor < 1.0 must not be rejected by hard floor."""
    strategy = StrategyDSL(
        schema_version="1.0",
        name="Experimental Scalp",
        underlying="RELIANCE",
        timeframe="15m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.LESS_THAN,
                    threshold=30.0,
                )
            ],
        ),
    )
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    timestamps = [t0 + timedelta(minutes=15 * i) for i in range(50)]
    res = _create_mock_backtest_result(profit_factor=0.85, timestamps=timestamps, expectancy=10.0)

    val_res = HistoricalStatisticalValidator.validate(
        strategy, result=res, policy=create_research_policy()
    )

    # In Research mode, low PF issues a warning rather than a HARD_FLOOR rejection
    assert val_res.status != ValidationStatus.REJECTED
    gate = next(g for g in val_res.gate_results if g.gate_name == "PROFIT_FACTOR_FLOOR")
    assert gate.passed is True
    assert gate.severity == GateSeverity.WARNING


# ==============================================================================
# Finding 7 Tests: Asset Class Resolution with 'FUT' Substring
# ==============================================================================


@pytest.mark.parametrize(
    "symbol,expected_is_future",
    [
        ("FUTURECONSUMER", False),
        ("FUTURA", False),
        ("FUTEX", False),
        ("RELIANCE", False),
        ("NIFTY-FUT", True),
        ("NIFTY.FUT", True),
        ("NIFTY FUT", True),
        ("NIFTY24DECFUT", True),
        ("RELIANCE24NOVFUT", True),
    ],
)
def test_remediation_finding_7_is_futures_symbol(symbol: str, expected_is_future: bool) -> None:
    """Equities with 'FUT' as a substring must not be misclassified as futures."""
    assert is_futures_symbol(symbol) is expected_is_future


def test_remediation_finding_7_ast_validator_asset_class() -> None:
    """ASTValidator must classify FUTURECONSUMER as EQUITY."""
    strategy = StrategyDSL(
        schema_version="1.0",
        name="Future Consumer Trend",
        underlying="FUTURECONSUMER",
        timeframe="1d",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=50.0,
                )
            ],
        ),
    )
    res = ASTValidator.validate(strategy)
    assert res.asset_class == "EQUITY"


# ==============================================================================
# Finding 8 Tests: Out-of-Sample (OOS) Temporal Disjointness Verification
# ==============================================================================


def test_remediation_finding_8_oos_temporal_leakage_veto() -> None:
    """OOS validation must reject backtests that overlap with the in-sample period."""
    strategy = StrategyDSL(
        schema_version="1.0",
        name="Trend Strategy",
        underlying="RELIANCE",
        timeframe="1h",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=50.0,
                )
            ],
        ),
    )
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    is_timestamps = [t0 + timedelta(hours=i) for i in range(100)]
    # Overlapping OOS timestamps (starts at hour 50, before hour 99)
    oos_timestamps_overlapping = [t0 + timedelta(hours=50 + i) for i in range(50)]

    is_res = _create_mock_backtest_result(1.5, is_timestamps, sharpe=2.0)
    oos_res = _create_mock_backtest_result(1.4, oos_timestamps_overlapping, sharpe=1.8)

    val_res = HistoricalStatisticalValidator.validate(
        strategy,
        result=is_res,
        policy=create_institutional_policy(),
        oos_result=oos_res,
    )

    assert val_res.status == ValidationStatus.REJECTED
    assert "OOS_TEMPORAL_SEPARATION" in val_res.failed_gates
    gate = next(g for g in val_res.gate_results if g.gate_name == "OOS_TEMPORAL_SEPARATION")
    assert gate.passed is False
    assert gate.severity == GateSeverity.HARD_FLOOR


def test_remediation_finding_8_oos_clean_separation_approved() -> None:
    """Strictly subsequent OOS backtests must pass the temporal separation gate."""
    strategy = StrategyDSL(
        schema_version="1.0",
        name="Trend Strategy",
        underlying="RELIANCE",
        timeframe="1h",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=50.0,
                )
            ],
        ),
    )
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    is_timestamps = [t0 + timedelta(hours=i) for i in range(100)]
    # Strictly subsequent OOS timestamps (starts at hour 100)
    oos_timestamps_clean = [t0 + timedelta(hours=100 + i) for i in range(50)]

    is_res = _create_mock_backtest_result(1.8, is_timestamps, sharpe=2.0)
    oos_res = _create_mock_backtest_result(1.7, oos_timestamps_clean, sharpe=1.8)

    val_res = HistoricalStatisticalValidator.validate(
        strategy,
        result=is_res,
        policy=create_institutional_policy(),
        oos_result=oos_res,
    )

    assert "OOS_TEMPORAL_SEPARATION" not in val_res.failed_gates
    gate = next(g for g in val_res.gate_results if g.gate_name == "OOS_TEMPORAL_SEPARATION")
    assert gate.passed is True


# ==============================================================================
# Finding 9 Tests: Deterministic Options Payoff Evaluation Timestamp
# ==============================================================================


def test_remediation_finding_9_deterministic_evaluation_time() -> None:
    """Options theoretical validation must produce identical outcomes with a fixed evaluation timestamp."""
    dsl = _build_bull_put_spread()
    eval_time = datetime(2024, 12, 19, 10, 0, tzinfo=UTC)

    res1 = OptionsTheoreticalValidator.validate(dsl, evaluation_time=eval_time)
    res2 = OptionsTheoreticalValidator.validate(dsl, evaluation_time=eval_time)

    assert res1.validation_score == res2.validation_score
    assert res1.metrics == res2.metrics
    assert res1.status == res2.status


# ==============================================================================
# Finding 10 Tests: Ambiguous Token Resolution Across Exchanges
# ==============================================================================


def test_remediation_finding_10_ambiguous_token_requires_exchange() -> None:
    """Colliding tokens across NSE and BSE must raise ValueError if exchange is omitted."""
    c_nse = ContractMetadata(
        symbol="TCS",
        trading_symbol="TCS-EQ",
        exchange="NSE",
        instrument_type="EQ",
        lot_size=1,
        tick_size=0.05,
        token="11536",
    )
    c_bse = ContractMetadata(
        symbol="INFY",
        trading_symbol="INFY-EQ",
        exchange="BSE",
        instrument_type="EQ",
        lot_size=1,
        tick_size=0.05,
        token="11536",
    )

    idx = InstrumentIndex([c_nse, c_bse])

    # Disambiguated by exchange
    assert idx.get_by_token("11536", exchange="NSE") == c_nse
    assert idx.get_by_token("11536", exchange="BSE") == c_bse

    # Ambiguous resolution without exchange must raise ValueError
    with pytest.raises(ValueError, match="Ambiguous token '11536'"):
        idx.get_by_token("11536")
