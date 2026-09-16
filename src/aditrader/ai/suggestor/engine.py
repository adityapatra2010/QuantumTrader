"""Rule-based and LLM-ready Strategy Suggestor implementation.

Per ADR 005, ADR 012, and Phase 7 directives:
- Translates identified market regimes, volatility profiles, and bias configurations into strategy proposals.
- Enforces configurable 60% selling / 40% buying bias prior (BiasCfg).
- Strictly non-authoritative: is_validated is False until evaluated by StrategyValidationService.
- Carries full ProvenanceRecord with SHA-256 input digest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from aditrader.ai.base import StrategySuggestor
from aditrader.ai.errors import AIMalformedOutputError
from aditrader.ai.models import (
    AISourceType,
    BiasCfg,
    ForecastResult,
    ProvenanceRecord,
    SuggestionResult,
    VisionResult,
)
from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.strategy.library.templates import (
    create_nifty_bull_call_spread_dsl,
    create_nifty_ce_premium_ladder_dsl,
    create_nifty_iron_condor_dsl,
    create_nifty_long_straddle_dsl,
)
from aditrader.validation.models import ValidationStatus
from aditrader.validation.service import StrategyValidationService


def create_nifty_bear_put_spread_dsl() -> StrategyDSL:
    """Construct Nifty Bear Put Spread declarative DSL."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Bear Put Spread",
        underlying="NIFTY",
        timeframe="5m",
        target_regime="Bearish Trend",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.LESS_THAN,
                    threshold=45.0,
                )
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.OR,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.GREATER_THAN,
                    threshold=65.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.BUY,
                strike_offset=0,  # Buy ATM Put
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.SELL,
                strike_offset=-1,  # Sell OTM Put (-1 strike lower)
                lots=1,
            ),
        ],
    )


def create_nifty_bull_put_spread_dsl() -> StrategyDSL:
    """Construct Nifty Bull Put Credit Spread declarative DSL."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Bull Put Spread",
        underlying="NIFTY",
        timeframe="5m",
        target_regime="Bullish Trend",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.GREATER_THAN,
                    threshold=55.0,
                ),
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.WITHIN_RANGE,
                    range_min="09:20",
                    range_max="14:30",
                ),
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.OR,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.GREATER_THAN,
                    threshold="15:15",
                ),
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.LESS_THAN,
                    threshold=45.0,
                ),
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
                strike_offset=-2,
                lots=1,
            ),
        ],
    )


def create_nifty_bear_call_spread_dsl() -> StrategyDSL:
    """Construct Nifty Bear Call Credit Spread declarative DSL."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Bear Call Spread",
        underlying="NIFTY",
        timeframe="5m",
        target_regime="Bearish Trend",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.LESS_THAN,
                    threshold=45.0,
                ),
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.WITHIN_RANGE,
                    range_min="09:20",
                    range_max="14:30",
                ),
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.OR,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.GREATER_THAN,
                    threshold="15:15",
                ),
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.GREATER_THAN,
                    threshold=55.0,
                ),
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.SELL,
                strike_offset=1,
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.BUY,
                strike_offset=2,
                lots=1,
            ),
        ],
    )


class RuleBasedSuggestor(StrategySuggestor):
    """Deterministic, regime-aware options strategy suggestor."""

    def __init__(
        self,
        model_id: str = "rule-suggestor-v1",
        model_version: str = "1.0.0",
        provider: str = "local",
        default_bias: BiasCfg | None = None,
        **_kwargs: Any,
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.provider = provider
        self.default_bias = default_bias or BiasCfg(sell_pct=0.60, buy_pct=0.40)

    def is_available(self) -> bool:
        """Deterministic suggestor is always available offline."""
        return True

    def suggest(
        self,
        regime: str,
        bias: BiasCfg | None = None,
        forecast: ForecastResult | None = None,
        vision: VisionResult | None = None,
    ) -> SuggestionResult:
        """Generate a declarative strategy proposal matching regime, bias, and context."""
        active_bias = bias or self.default_bias
        clean_regime = regime.strip()
        if not clean_regime:
            raise AIMalformedOutputError("Market regime string cannot be empty")

        # Directional sentiment from vision or forecast
        directional_bias = "neutral"
        if vision is not None and not vision.is_empty:
            if vision.trend == "Bullish":
                directional_bias = "bullish"
            elif vision.trend == "Bearish":
                directional_bias = "bearish"
        elif forecast is not None and forecast.predicted_close:
            pct_change = (
                forecast.predicted_close[-1] - forecast.predicted_close[0]
            ) / forecast.predicted_close[0]
            if pct_change > 0.003:
                directional_bias = "bullish"
            elif pct_change < -0.003:
                directional_bias = "bearish"

        regime_lower = clean_regime.lower()

        # Strategy selection decision tree
        if any(
            w in regime_lower for w in ("sideways", "range", "low iv", "low_volatility", "neutral")
        ):
            if active_bias.sell_pct >= 0.50:
                dsl = create_nifty_iron_condor_dsl()
                rationale = (
                    f"Selected Nifty Weekly Iron Condor: Low-volatility sideways regime favored by "
                    f"dominant premium selling bias ({active_bias.sell_pct:.0%}). "
                    "Collects dual CE/PE wing premium with strictly defined risk."
                )
            else:
                dsl = create_nifty_long_straddle_dsl()
                rationale = (
                    f"Selected Nifty Long Straddle: Sideways consolidation with high buying bias "
                    f"({active_bias.buy_pct:.0%}) positioning for anticipated breakout."
                )
        elif any(
            w in regime_lower for w in ("expansion", "high iv", "high_volatility", "breakout")
        ):
            dsl = create_nifty_long_straddle_dsl()
            rationale = (
                "Selected Nifty Long Straddle: High volatility expansion regime favors debit options. "
                "Non-directional long volatility captures large moves in either direction."
            )
        elif (
            any(w in regime_lower for w in ("bull", "up", "rally")) or directional_bias == "bullish"
        ):
            if "ladder" in regime_lower:
                dsl = create_nifty_ce_premium_ladder_dsl()
                rationale = (
                    "Selected NIFTY CE Dynamic Premium-Ladder: Bullish trending market with dynamic "
                    "price-band selection and 4x protective hedge ratio."
                )
            elif active_bias.sell_pct >= 0.50:
                dsl = create_nifty_bull_put_spread_dsl()
                rationale = (
                    f"Selected Nifty Bull Put Spread: Bullish trending structure honoring "
                    f"{active_bias.sell_pct:.0%} premium selling allocation (credit spread with defined lower wing)."
                )
            else:
                dsl = create_nifty_bull_call_spread_dsl()
                rationale = (
                    f"Selected Nifty Bull Call Spread: Bullish trending structure with defined risk. "
                    f"Buying ATM call with debit outlay consistent with {active_bias.buy_pct:.0%} buy allocation."
                )
        elif (
            any(w in regime_lower for w in ("bear", "down", "drop"))
            or directional_bias == "bearish"
        ):
            if active_bias.sell_pct >= 0.50:
                dsl = create_nifty_bear_call_spread_dsl()
                rationale = (
                    f"Selected Nifty Bear Call Spread: Directional bearish structure honoring "
                    f"{active_bias.sell_pct:.0%} premium selling allocation (credit spread with defined upper wing)."
                )
            else:
                dsl = create_nifty_bear_put_spread_dsl()
                rationale = (
                    f"Selected Nifty Bear Put Spread: Directional bearish structure with defined risk. "
                    f"Long ATM put funded in part by selling lower OTM put wing ({active_bias.buy_pct:.0%} buy allocation)."
                )
        else:
            # Default fallback adhering to 60/40 prior
            if active_bias.sell_pct >= 0.50:
                dsl = create_nifty_iron_condor_dsl()
                rationale = (
                    f"Default institutional fallback: Nifty Weekly Iron Condor honoring {active_bias.sell_pct:.0%} "
                    "selling prior in unclassified market environment."
                )
            else:
                dsl = create_nifty_bull_call_spread_dsl()
                rationale = (
                    f"Default institutional fallback: Nifty Bull Call Spread honoring {active_bias.buy_pct:.0%} "
                    "buying prior in unclassified market environment."
                )

        # Compute cryptographic input hash
        hash_payload = {
            "regime": clean_regime,
            "bias": {"sell": active_bias.sell_pct, "buy": active_bias.buy_pct},
            "directional_bias": directional_bias,
            "forecast_hash": forecast.provenance.input_hash if forecast else None,
            "vision_hash": vision.source_image_hash if vision else None,
        }
        input_hash = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        provenance = ProvenanceRecord(
            source_type=AISourceType.STRATEGY_SUGGESTION,
            model_id=self.model_id,
            model_version=self.model_version,
            provider=self.provider,
            generated_at=datetime.now(UTC),
            input_hash=input_hash,
            is_deterministic=True,
            confidence=0.90,
        )

        return SuggestionResult(
            strategy_dsl=dsl,
            provenance=provenance,
            bias_applied=active_bias,
            regime_context=clean_regime,
            rationale=rationale,
            validation_result=None,
            is_validated=False,
        )

    def suggest_and_validate(
        self,
        regime: str,
        validator: StrategyValidationService,
        bias: BiasCfg | None = None,
        forecast: ForecastResult | None = None,
        vision: VisionResult | None = None,
    ) -> SuggestionResult:
        """Propose strategy and run authoritative deterministic validation immediately."""
        suggestion = self.suggest(regime=regime, bias=bias, forecast=forecast, vision=vision)
        val_result = validator.validate(suggestion.strategy_dsl)
        is_approved = val_result.status == ValidationStatus.APPROVED

        return SuggestionResult(
            strategy_dsl=suggestion.strategy_dsl,
            provenance=suggestion.provenance,
            bias_applied=suggestion.bias_applied,
            regime_context=suggestion.regime_context,
            rationale=suggestion.rationale,
            validation_result=val_result,
            is_validated=is_approved,
        )
