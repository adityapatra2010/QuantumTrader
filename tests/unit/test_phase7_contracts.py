"""Unit tests for Phase 7 typed contracts, failure modes, and provenance invariants."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aditrader.ai.base import (
    ForecastEngine,
    StrategyReviewer,
    StrategySuggestor,
    VisionEngine,
)
from aditrader.ai.errors import (
    AIConfigError,
    AIError,
    AILookaheadError,
    AILowConfidenceError,
    AIMalformedOutputError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
)
from aditrader.ai.models import (
    AISourceType,
    BiasCfg,
    DossierSection,
    DossierSectionSourceType,
    ForecastResult,
    PatternObservation,
    ProvenanceRecord,
    ResearchDossier,
    SuggestionResult,
    VisionResult,
)
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.strategy.library.templates import create_nifty_iron_condor_dsl
from aditrader.validation.models import (
    SampleSizeStatus,
    ValidationResult,
    ValidationScope,
    ValidationStatus,
)


def _create_sample_provenance(
    source_type: AISourceType = AISourceType.PROBABILISTIC_FORECAST,
) -> ProvenanceRecord:
    return ProvenanceRecord(
        source_type=source_type,
        model_id="chronos-t5-large",
        model_version="1.0.0",
        provider="local",
        generated_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        input_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        seed=42,
        is_deterministic=True,
        confidence=0.85,
    )


def test_provenance_record_immutability_and_validation() -> None:
    """Verify ProvenanceRecord is immutable and enforces typing constraints."""
    prov = _create_sample_provenance()
    assert prov.source_type == AISourceType.PROBABILISTIC_FORECAST
    assert prov.model_id == "chronos-t5-large"
    assert prov.is_deterministic is True
    assert prov.seed == 42

    with pytest.raises(ValidationError):
        # Immutability check
        setattr(prov, "model_id", "other-model")

    with pytest.raises(ValidationError):
        # Confidence out of bounds
        ProvenanceRecord(
            source_type=AISourceType.MULTIMODAL_VISION,
            model_id="gemini-2.0-flash",
            model_version="v1",
            provider="google",
            input_hash="a" * 64,
            confidence=1.5,
        )


def test_forecast_result_anti_lookahead_and_envelope() -> None:
    """Verify ForecastResult prevents lookahead and enforces price envelopes."""
    cutoff = datetime(2026, 9, 6, 9, 30, tzinfo=UTC)
    t1 = cutoff + timedelta(minutes=5)
    t2 = cutoff + timedelta(minutes=10)

    # Valid forecast
    forecast = ForecastResult(
        cutoff_timestamp=cutoff,
        horizon_bars=2,
        timestamps=[t1, t2],
        predicted_close=[24500.0, 24520.0],
        predicted_high=[24550.0, 24560.0],
        predicted_low=[24480.0, 24490.0],
        confidence_spread=0.02,
        provenance=_create_sample_provenance(AISourceType.PROBABILISTIC_FORECAST),
    )
    assert forecast.horizon_bars == 2

    # Lookahead violation: target timestamp equal or before cutoff
    with pytest.raises(ValueError, match="Lookahead violation"):
        ForecastResult(
            cutoff_timestamp=cutoff,
            horizon_bars=2,
            timestamps=[cutoff, t2],  # Lookahead!
            predicted_close=[24500.0, 24520.0],
            predicted_high=[24550.0, 24560.0],
            predicted_low=[24480.0, 24490.0],
            confidence_spread=0.02,
            provenance=_create_sample_provenance(AISourceType.PROBABILISTIC_FORECAST),
        )

    # Price envelope breach: high < close
    with pytest.raises(ValueError, match="Price envelope breach"):
        ForecastResult(
            cutoff_timestamp=cutoff,
            horizon_bars=2,
            timestamps=[t1, t2],
            predicted_close=[24560.0, 24520.0],  # Close > High!
            predicted_high=[24550.0, 24560.0],
            predicted_low=[24480.0, 24490.0],
            confidence_spread=0.02,
            provenance=_create_sample_provenance(AISourceType.PROBABILISTIC_FORECAST),
        )

    # Length mismatch
    with pytest.raises(ValueError, match="must match horizon_bars"):
        ForecastResult(
            cutoff_timestamp=cutoff,
            horizon_bars=3,  # Mismatch: 3 bars declared, 2 provided
            timestamps=[t1, t2],
            predicted_close=[24500.0, 24520.0],
            predicted_high=[24550.0, 24560.0],
            predicted_low=[24480.0, 24490.0],
            confidence_spread=0.02,
            provenance=_create_sample_provenance(AISourceType.PROBABILISTIC_FORECAST),
        )


def test_vision_result_validation() -> None:
    """Verify VisionResult requires positive price coordinates and valid structure."""
    prov = _create_sample_provenance(AISourceType.MULTIMODAL_VISION)
    vision = VisionResult(
        trend="Bullish",
        support=[24300.0, 24250.0],
        resistance=[24600.0, 24700.0],
        patterns=[PatternObservation(name="Bull Flag", confidence=0.82)],
        reasoning="Strong ascending trendline with volume consolidation.",
        source_image_hash="a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
        is_empty=False,
        provenance=prov,
    )
    assert vision.trend == "Bullish"
    assert len(vision.support) == 2

    # Negative price level rejection
    with pytest.raises(ValueError, match="Support level must be positive"):
        VisionResult(
            trend="Neutral",
            support=[-100.0],
            resistance=[24600.0],
            reasoning="Invalid coordinate",
            source_image_hash="hash",
            provenance=prov,
        )


def test_bias_cfg_validation() -> None:
    """Verify BiasCfg enforces transparent and exact sum-to-one constraint."""
    default_bias = BiasCfg()
    assert default_bias.sell_pct == 0.60
    assert default_bias.buy_pct == 0.40

    custom_bias = BiasCfg(sell_pct=0.75, buy_pct=0.25)
    assert custom_bias.sell_pct == 0.75

    # Invalid sum: 0.60 + 0.50 != 1.0
    with pytest.raises(ValueError, match="must sum to 1.0"):
        BiasCfg(sell_pct=0.60, buy_pct=0.50)

    # Out of range negative
    with pytest.raises(ValidationError):
        BiasCfg(sell_pct=-0.1, buy_pct=1.1)


def test_suggestion_result_validation_gate() -> None:
    """Verify SuggestionResult is_validated flag is strictly tied to APPROVED ValidationResult."""
    dsl = create_nifty_iron_condor_dsl()
    prov = _create_sample_provenance(AISourceType.STRATEGY_SUGGESTION)
    bias = BiasCfg()

    # Valid un-validated proposal
    sugg = SuggestionResult(
        strategy_dsl=dsl,
        provenance=prov,
        bias_applied=bias,
        regime_context="Low IV Sideways consolidation",
        rationale="Delta-neutral defined risk captures theta decay within range.",
        validation_result=None,
        is_validated=False,
    )
    assert sugg.is_validated is False

    # Cannot claim is_validated=True without validation_result
    with pytest.raises(ValueError, match="is_validated can only be True"):
        SuggestionResult(
            strategy_dsl=dsl,
            provenance=prov,
            bias_applied=bias,
            regime_context="Context",
            rationale="Rationale",
            validation_result=None,
            is_validated=True,  # Illegal!
        )

    # Cannot claim is_validated=True if status is REJECTED
    rejected_val = ValidationResult(
        strategy_name=dsl.name,
        underlying=dsl.underlying,
        asset_class="OPTIONS",
        validation_scope=ValidationScope.THEORETICAL,
        status=ValidationStatus.REJECTED,
        validation_score=10.0,
        sample_size_status=SampleSizeStatus.NOT_APPLICABLE,
        historical_vs_theoretical="THEORETICAL",
    )
    with pytest.raises(ValueError, match="is_validated can only be True"):
        SuggestionResult(
            strategy_dsl=dsl,
            provenance=prov,
            bias_applied=bias,
            regime_context="Context",
            rationale="Rationale",
            validation_result=rejected_val,
            is_validated=True,  # Illegal!
        )

    # Valid is_validated=True when status is APPROVED
    approved_val = ValidationResult(
        strategy_name=dsl.name,
        underlying=dsl.underlying,
        asset_class="OPTIONS",
        validation_scope=ValidationScope.THEORETICAL,
        status=ValidationStatus.APPROVED,
        validation_score=92.0,
        sample_size_status=SampleSizeStatus.NOT_APPLICABLE,
        historical_vs_theoretical="THEORETICAL",
    )
    approved_sugg = SuggestionResult(
        strategy_dsl=dsl,
        provenance=prov,
        bias_applied=bias,
        regime_context="Low IV Sideways consolidation",
        rationale="Delta-neutral defined risk captures theta decay within range.",
        validation_result=approved_val,
        is_validated=True,
    )
    assert approved_sugg.is_validated is True


def test_dossier_section_and_research_dossier() -> None:
    """Verify ResearchDossier and DossierSection enforce provenance on AI_ADVISORY sections."""
    prov = _create_sample_provenance(AISourceType.STRATEGY_REVIEW)

    # Valid deterministic section without provenance
    sec_det = DossierSection(
        title="Historical Metrics",
        source_type=DossierSectionSourceType.DETERMINISTIC,
        content="Sharpe: 1.85, Max DD: 4.2%",
        provenance=None,
    )
    assert sec_det.source_type == DossierSectionSourceType.DETERMINISTIC

    # Valid AI advisory section with provenance
    sec_ai = DossierSection(
        title="Qualitative Risk Review",
        source_type=DossierSectionSourceType.AI_ADVISORY,
        content="Strategy is vulnerable to sudden gamma spikes near expiry.",
        provenance=prov,
    )
    assert sec_ai.provenance is not None

    # AI advisory section missing provenance must fail
    with pytest.raises(ValueError, match="must include a ProvenanceRecord"):
        DossierSection(
            title="Advisory Warning",
            source_type=DossierSectionSourceType.AI_ADVISORY,
            content="Missing provenance record!",
            provenance=None,
        )

    # Create full research dossier
    dossier = ResearchDossier(
        dossier_id="dos-001",
        strategy_name="Nifty Weekly Iron Condor",
        sections=[sec_det, sec_ai],
    )
    assert dossier.dossier_id == "dos-001"
    assert "Advisory Notice" in dossier.disclaimer


def test_error_hierarchy() -> None:
    """Verify AI failure exception hierarchy."""
    assert issubclass(AIUnavailableError, AIError)
    assert issubclass(AITimeoutError, AIError)
    assert issubclass(AIMalformedOutputError, AIError)
    assert issubclass(AIProviderError, AIError)
    assert issubclass(AILowConfidenceError, AIError)
    assert issubclass(AILookaheadError, AIError)
    assert issubclass(AIConfigError, AIError)


def test_abstract_interfaces_cannot_be_instantiated() -> None:
    """Verify abstract interfaces prevent instantiation without implementing contract."""
    with pytest.raises(TypeError):
        ForecastEngine()  # type: ignore[abstract]

    with pytest.raises(TypeError):
        VisionEngine()  # type: ignore[abstract]

    with pytest.raises(TypeError):
        StrategySuggestor()  # type: ignore[abstract]

    with pytest.raises(TypeError):
        StrategyReviewer()  # type: ignore[abstract]


def test_strategy_reviewer_enforces_ai_advisory_source_type() -> None:
    """Mandatory Fix 1 Regression: StrategyReviewer MUST enforce source_type=AI_ADVISORY."""
    dsl = create_nifty_iron_condor_dsl()
    prov = _create_sample_provenance(AISourceType.STRATEGY_REVIEW)
    val_res = ValidationResult(
        strategy_name=dsl.name,
        underlying=dsl.underlying,
        asset_class="OPTIONS",
        validation_scope=ValidationScope.THEORETICAL,
        status=ValidationStatus.APPROVED,
        validation_score=90.0,
        sample_size_status=SampleSizeStatus.NOT_APPLICABLE,
        historical_vs_theoretical="THEORETICAL",
    )

    # Rogue reviewer attempting to return DETERMINISTIC source_type
    class RogueDeterministicReviewer(StrategyReviewer):
        def _generate_review(
            self,
            strategy: StrategyDSL,
            validation_result: ValidationResult,
        ) -> DossierSection:
            return DossierSection(
                title="Fake Verified Metrics",
                source_type=DossierSectionSourceType.DETERMINISTIC,
                content="Claiming backtest Sharpe 5.0",
                provenance=None,
            )

    rogue = RogueDeterministicReviewer()
    with pytest.raises(AIMalformedOutputError, match="must have source_type=AI_ADVISORY"):
        rogue.review(dsl, val_res)

    # Rogue reviewer attempting to return STRUCTURAL source_type
    class RogueStructuralReviewer(StrategyReviewer):
        def _generate_review(
            self,
            strategy: StrategyDSL,
            validation_result: ValidationResult,
        ) -> DossierSection:
            return DossierSection(
                title="Structural Rules",
                source_type=DossierSectionSourceType.STRUCTURAL,
                content="AST rule representation",
                provenance=None,
            )

    rogue_struct = RogueStructuralReviewer()
    with pytest.raises(AIMalformedOutputError, match="must have source_type=AI_ADVISORY"):
        rogue_struct.review(dsl, val_res)

    # Valid compliant reviewer returning AI_ADVISORY with provenance
    class CompliantReviewer(StrategyReviewer):
        def _generate_review(
            self,
            strategy: StrategyDSL,
            validation_result: ValidationResult,
        ) -> DossierSection:
            return DossierSection(
                title="Qualitative Risk Review",
                source_type=DossierSectionSourceType.AI_ADVISORY,
                content="Tail risk is well-hedged by outer protective wings.",
                provenance=prov,
            )

    compliant = CompliantReviewer()
    section = compliant.review(dsl, val_res)
    assert section.source_type == DossierSectionSourceType.AI_ADVISORY
    assert section.provenance is not None


def test_timezone_aware_temporal_contracts() -> None:
    """Mandatory Fix 2 Regression: Datetimes must be timezone-aware; never trigger TypeError."""
    prov = _create_sample_provenance(AISourceType.PROBABILISTIC_FORECAST)
    naive_dt = datetime(2026, 9, 6, 9, 30)  # Naive!
    aware_cutoff = datetime(2026, 9, 6, 9, 30, tzinfo=UTC)
    aware_t1 = aware_cutoff + timedelta(minutes=5)
    aware_t2 = aware_cutoff + timedelta(minutes=10)

    # 1. Naive cutoff + aware forecast timestamps -> ValidationError (not TypeError!)
    with pytest.raises(ValidationError, match="cutoff_timestamp must be a timezone-aware datetime"):
        ForecastResult(
            cutoff_timestamp=naive_dt,
            horizon_bars=2,
            timestamps=[aware_t1, aware_t2],
            predicted_close=[24500.0, 24520.0],
            predicted_high=[24550.0, 24560.0],
            predicted_low=[24480.0, 24490.0],
            confidence_spread=0.02,
            provenance=prov,
        )

    # 2. Aware cutoff + naive forecast timestamps -> ValidationError (not TypeError!)
    naive_t1 = naive_dt + timedelta(minutes=5)
    naive_t2 = naive_dt + timedelta(minutes=10)
    with pytest.raises(
        ValidationError, match="Forecast timestamp\\[0\\] must be a timezone-aware datetime"
    ):
        ForecastResult(
            cutoff_timestamp=aware_cutoff,
            horizon_bars=2,
            timestamps=[naive_t1, naive_t2],
            predicted_close=[24500.0, 24520.0],
            predicted_high=[24550.0, 24560.0],
            predicted_low=[24480.0, 24490.0],
            confidence_spread=0.02,
            provenance=prov,
        )

    # 3. Naive generated_at in ProvenanceRecord -> ValidationError
    with pytest.raises(ValidationError, match="generated_at must be a timezone-aware datetime"):
        ProvenanceRecord(
            source_type=AISourceType.PROBABILISTIC_FORECAST,
            model_id="chronos-t5-large",
            model_version="1.0.0",
            provider="local",
            generated_at=naive_dt,
            input_hash="a" * 64,
        )

    # 4. All-aware valid UTC timestamps -> Succeeds
    forecast = ForecastResult(
        cutoff_timestamp=aware_cutoff,
        horizon_bars=2,
        timestamps=[aware_t1, aware_t2],
        predicted_close=[24500.0, 24520.0],
        predicted_high=[24550.0, 24560.0],
        predicted_low=[24480.0, 24490.0],
        confidence_spread=0.02,
        provenance=prov,
    )
    assert forecast.cutoff_timestamp.tzinfo is not None
    assert forecast.timestamps[0] == aware_t1

    # 5. Non-monotonic forecast timestamps (t2 <= t1) -> ValidationError
    with pytest.raises(ValidationError, match="strictly monotonically increasing"):
        ForecastResult(
            cutoff_timestamp=aware_cutoff,
            horizon_bars=2,
            timestamps=[aware_t2, aware_t1],  # Inverted order!
            predicted_close=[24500.0, 24520.0],
            predicted_high=[24550.0, 24560.0],
            predicted_low=[24480.0, 24490.0],
            confidence_spread=0.02,
            provenance=prov,
        )

    # Duplicate forecast timestamps (t1 == t1) -> ValidationError
    with pytest.raises(ValidationError, match="strictly monotonically increasing"):
        ForecastResult(
            cutoff_timestamp=aware_cutoff,
            horizon_bars=2,
            timestamps=[aware_t1, aware_t1],  # Duplicate!
            predicted_close=[24500.0, 24520.0],
            predicted_high=[24550.0, 24560.0],
            predicted_low=[24480.0, 24490.0],
            confidence_spread=0.02,
            provenance=prov,
        )


def test_cryptographic_input_hash_integrity() -> None:
    """Mandatory Fix 3 Regression: input_hash must be exactly 64 hexadecimal characters."""
    valid_lower = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    valid_upper = "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"

    # 1. Valid lowercase SHA-256 -> passes
    prov_lower = ProvenanceRecord(
        source_type=AISourceType.PROBABILISTIC_FORECAST,
        model_id="model",
        model_version="v1",
        provider="local",
        input_hash=valid_lower,
    )
    assert prov_lower.input_hash == valid_lower

    # 2. Valid uppercase SHA-256 -> passes and normalizes to lowercase
    prov_upper = ProvenanceRecord(
        source_type=AISourceType.PROBABILISTIC_FORECAST,
        model_id="model",
        model_version="v1",
        provider="local",
        input_hash=valid_upper,
    )
    assert prov_upper.input_hash == valid_lower

    # 3. Invalid length: 63 characters -> ValidationError
    with pytest.raises(ValidationError, match="valid 64-character SHA-256"):
        ProvenanceRecord(
            source_type=AISourceType.PROBABILISTIC_FORECAST,
            model_id="model",
            model_version="v1",
            provider="local",
            input_hash="a" * 63,
        )

    # Invalid length: 65 characters -> ValidationError
    with pytest.raises(ValidationError, match="valid 64-character SHA-256"):
        ProvenanceRecord(
            source_type=AISourceType.PROBABILISTIC_FORECAST,
            model_id="model",
            model_version="v1",
            provider="local",
            input_hash="a" * 65,
        )

    # 4. Non-hex characters in 64-char string -> ValidationError
    non_hex_64 = "g" + "0" * 63
    with pytest.raises(ValidationError, match="valid 64-character SHA-256"):
        ProvenanceRecord(
            source_type=AISourceType.PROBABILISTIC_FORECAST,
            model_id="model",
            model_version="v1",
            provider="local",
            input_hash=non_hex_64,
        )

    # 5. Placeholder strings -> ValidationError
    for placeholder in ["placeholder", "N/A", "a", "none", "0x1234"]:
        with pytest.raises(ValidationError, match="valid 64-character SHA-256"):
            ProvenanceRecord(
                source_type=AISourceType.PROBABILISTIC_FORECAST,
                model_id="model",
                model_version="v1",
                provider="local",
                input_hash=placeholder,
            )
