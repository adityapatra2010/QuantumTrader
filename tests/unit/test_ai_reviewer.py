"""Unit tests for Strategy Reviewer subsystem and ADR 012 contract enforcement."""

import pytest

from aditrader.ai.base import StrategyReviewer
from aditrader.ai.errors import AIMalformedOutputError
from aditrader.ai.models import (
    AISourceType,
    DossierSection,
    DossierSectionSourceType,
    ProvenanceRecord,
)
from aditrader.ai.reviewer.engine import DeterministicAdvisoryReviewer
from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.strategy.library.templates import create_nifty_iron_condor_dsl
from aditrader.validation.models import ValidationResult
from aditrader.validation.service import StrategyValidationService


def test_reviewer_approved_strategy() -> None:
    """Reviewer produces advisory critique for an approved strategy with defined risk."""
    strategy = create_nifty_iron_condor_dsl()
    validator = StrategyValidationService()
    val_res = validator.validate(strategy)

    reviewer = DeterministicAdvisoryReviewer()
    section = reviewer.review(strategy, val_res)

    assert isinstance(section, DossierSection)
    assert section.source_type == DossierSectionSourceType.AI_ADVISORY
    assert section.provenance is not None
    assert section.provenance.source_type == AISourceType.STRATEGY_REVIEW
    assert len(section.provenance.input_hash) == 64

    content = section.content
    assert "Cleared institutional validation gates" in content
    assert "defined-risk geometry" in content
    assert "ADR 012" in content


def test_reviewer_unhedged_risk_and_rejection() -> None:
    """Reviewer highlights unhedged tail exposure and rejection gates."""
    # Naked short Call strategy
    strategy = StrategyDSL(
        schema_version="1.0",
        name="Naked Short Call",
        underlying="NIFTY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.GREATER_THAN,
                    threshold=70.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.SELL,
                strike_offset=1,
                lots=2,
            )
        ],
    )

    validator = StrategyValidationService()
    rejection_result = validator.validate(strategy)

    reviewer = DeterministicAdvisoryReviewer()
    section = reviewer.review(strategy, rejection_result)

    content = section.content
    assert "Unhedged Call Gamma" in content
    assert section.source_type == DossierSectionSourceType.AI_ADVISORY


def test_reviewer_contract_rejects_deterministic_masquerade() -> None:
    """StrategyReviewer base contract raises AIMalformedOutputError if subclass outputs DETERMINISTIC."""

    class BadReviewer(StrategyReviewer):
        def _generate_review(
            self, strategy: StrategyDSL, validation_result: ValidationResult
        ) -> DossierSection:
            return DossierSection(
                title="Deceptive Section",
                source_type=DossierSectionSourceType.DETERMINISTIC,  # Illegal for AI reviewer
                content="Masquerading content",
            )

    strategy = create_nifty_iron_condor_dsl()
    validator = StrategyValidationService()
    val_res = validator.validate(strategy)

    bad_reviewer = BadReviewer()
    with pytest.raises(AIMalformedOutputError, match="must have source_type=AI_ADVISORY"):
        bad_reviewer.review(strategy, val_res)


def test_reviewer_contract_rejects_missing_provenance() -> None:
    """StrategyReviewer base contract raises AIMalformedOutputError if provenance is missing."""

    class MissingProvenanceReviewer(StrategyReviewer):
        def _generate_review(
            self, strategy: StrategyDSL, validation_result: ValidationResult
        ) -> DossierSection:
            sec = DossierSection(
                title="Advisory Section",
                source_type=DossierSectionSourceType.AI_ADVISORY,
                content="Some critique",
                provenance=ProvenanceRecord(
                    source_type=AISourceType.STRATEGY_REVIEW,
                    model_id="m",
                    model_version="1",
                    provider="p",
                    input_hash="a" * 64,
                ),
            )
            # bypass frozen model for test
            object.__setattr__(sec, "provenance", None)
            return sec

    strategy = create_nifty_iron_condor_dsl()
    validator = StrategyValidationService()
    val_res = validator.validate(strategy)

    reviewer = MissingProvenanceReviewer()
    with pytest.raises(AIMalformedOutputError, match="must include a valid ProvenanceRecord"):
        reviewer.review(strategy, val_res)


def test_reviewer_partially_hedged_does_not_claim_fully_covered() -> None:
    """Strategy with covered CE but naked PE must NOT report all legs are covered."""
    strategy = StrategyDSL(
        schema_version="1.0",
        name="Asymmetric Short Strangle Hedged Call Only",
        underlying="NIFTY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.GREATER_THAN,
                    threshold=50.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(contract_type="CE", side=OrderSide.SELL, strike_offset=1, lots=1),
            StrategyLegDefinition(contract_type="CE", side=OrderSide.BUY, strike_offset=2, lots=1),
            StrategyLegDefinition(
                contract_type="PE", side=OrderSide.SELL, strike_offset=-1, lots=1
            ),
            # No PE hedge wing
        ],
    )
    validator = StrategyValidationService()
    val_res = validator.validate(strategy)

    reviewer = DeterministicAdvisoryReviewer()
    section = reviewer.review(strategy, val_res)

    assert "All short option legs are covered" not in section.content
    assert "Unhedged Put Gamma" in section.content
