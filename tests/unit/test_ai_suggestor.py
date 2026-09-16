"""Unit tests for Strategy Suggestor subsystem."""

import pytest

from aditrader.ai.errors import AIMalformedOutputError
from aditrader.ai.models import AISourceType, BiasCfg, SuggestionResult
from aditrader.ai.suggestor.engine import RuleBasedSuggestor
from aditrader.validation.models import ValidationStatus
from aditrader.validation.service import StrategyValidationService


def test_suggestor_low_volatility_selling_bias() -> None:
    """Low IV regime with 60% selling bias yields Iron Condor."""
    suggestor = RuleBasedSuggestor()
    result = suggestor.suggest(regime="Low IV Sideways")

    assert isinstance(result, SuggestionResult)
    assert result.strategy_dsl.name == "Nifty Weekly Iron Condor"
    assert result.bias_applied.sell_pct == 0.60
    assert result.bias_applied.buy_pct == 0.40
    assert result.is_validated is False
    assert result.validation_result is None
    assert result.provenance.source_type == AISourceType.STRATEGY_SUGGESTION
    assert len(result.provenance.input_hash) == 64


def test_suggestor_low_volatility_buying_bias() -> None:
    """Low IV regime with high buying bias (80% buy) yields Long Straddle."""
    suggestor = RuleBasedSuggestor()
    result = suggestor.suggest(
        regime="Low Volatility Range",
        bias=BiasCfg(sell_pct=0.20, buy_pct=0.80),
    )

    assert result.strategy_dsl.name == "Nifty Long Straddle"
    assert result.bias_applied.buy_pct == 0.80


def test_suggestor_bullish_trending_selling_bias() -> None:
    """Bullish regime with default 60% selling bias proposes Bull Put Credit Spread."""
    suggestor = RuleBasedSuggestor()
    result = suggestor.suggest(regime="Bullish Momentum Rally")

    assert result.strategy_dsl.name == "Nifty Bull Put Spread"
    assert "Bull Put Spread" in result.rationale
    assert result.strategy_dsl.legs[0].side.value == "SELL"


def test_suggestor_bullish_trending_buying_bias() -> None:
    """Bullish regime with buying bias proposes Bull Call Debit Spread."""
    suggestor = RuleBasedSuggestor()
    result = suggestor.suggest(
        regime="Bullish Momentum Rally",
        bias=BiasCfg(sell_pct=0.30, buy_pct=0.70),
    )

    assert result.strategy_dsl.name == "Nifty Bull Call Spread"
    assert "Bull Call Spread" in result.rationale
    assert result.strategy_dsl.legs[0].side.value == "BUY"


def test_suggestor_bearish_trending_selling_bias() -> None:
    """Bearish regime with default 60% selling bias proposes Bear Call Credit Spread."""
    suggestor = RuleBasedSuggestor()
    result = suggestor.suggest(regime="Bearish Market Drop")

    assert result.strategy_dsl.name == "Nifty Bear Call Spread"
    assert "Bear Call Spread" in result.rationale
    assert result.strategy_dsl.legs[0].side.value == "SELL"


def test_suggestor_bearish_trending_buying_bias() -> None:
    """Bearish regime with buying bias proposes Bear Put Debit Spread."""
    suggestor = RuleBasedSuggestor()
    result = suggestor.suggest(
        regime="Bearish Market Drop",
        bias=BiasCfg(sell_pct=0.30, buy_pct=0.70),
    )

    assert result.strategy_dsl.name == "Nifty Bear Put Spread"
    assert len(result.strategy_dsl.legs) == 2
    assert result.strategy_dsl.legs[0].contract_type == "PE"


def test_suggestor_empty_regime_rejection() -> None:
    """Empty regime string raises AIMalformedOutputError."""
    suggestor = RuleBasedSuggestor()
    with pytest.raises(AIMalformedOutputError, match="regime string cannot be empty"):
        suggestor.suggest(regime="   ")


def test_suggest_and_validate_workflow() -> None:
    """suggest_and_validate links suggestion with authoritative deterministic validation."""
    suggestor = RuleBasedSuggestor()
    validator = StrategyValidationService()

    result = suggestor.suggest_and_validate(
        regime="Low IV Sideways",
        validator=validator,
    )

    assert result.validation_result is not None
    assert result.validation_result.status == ValidationStatus.APPROVED
    assert result.is_validated is True
