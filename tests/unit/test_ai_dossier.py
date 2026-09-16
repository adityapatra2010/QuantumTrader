"""Unit tests for Parameter Sensitivity and Research Dossier Compiler."""

from datetime import UTC, datetime, timedelta

from aditrader.ai.dossier import ResearchDossierCompiler
from aditrader.ai.forecasting.mock import HeuristicForecastEngine
from aditrader.ai.models import (
    AISourceType,
    DossierSectionSourceType,
    PatternObservation,
    ProvenanceRecord,
    ResearchDossier,
    VisionResult,
)
from aditrader.ai.sensitivity import ParameterSensitivityEngine
from aditrader.core.models.market_data import Bar
from aditrader.strategy.library.templates import create_nifty_iron_condor_dsl
from aditrader.validation.service import StrategyValidationService


def test_parameter_sensitivity_engine_iv_shifts() -> None:
    """Sensitivity engine computes Black-Scholes Greeks across IV shifts."""
    strategy = create_nifty_iron_condor_dsl()
    engine = ParameterSensitivityEngine()

    result = engine.evaluate_options_iv_sensitivity(
        strategy=strategy,
        spot_price=24000.0,
        baseline_iv=0.15,
        iv_shifts=[-0.04, -0.02, 0.0, 0.02, 0.04],
    )

    assert result.strategy_name == strategy.name
    assert result.parameter_name == "iv_shift_pct"
    assert len(result.grid_points) == 5
    assert result.stability_verdict in ("STABLE", "FRAGILE")

    sec = engine.to_dossier_section(result)
    assert sec.source_type == DossierSectionSourceType.DETERMINISTIC
    assert sec.provenance is None  # Pure deterministic math, not AI
    assert "Parameter Sensitivity Grid" in sec.content


def test_research_dossier_compiler_complete_assembly() -> None:
    """Compiler produces fully categorized research dossier with strict evidence segregation."""
    strategy = create_nifty_iron_condor_dsl()
    validator = StrategyValidationService()
    val_res = validator.validate(strategy)

    compiler = ResearchDossierCompiler()
    dossier = compiler.compile(
        strategy=strategy,
        validation_result=val_res,
    )

    assert isinstance(dossier, ResearchDossier)
    assert dossier.strategy_name == strategy.name
    assert len(dossier.sections) >= 5

    # Check evidence segregation: every AI_ADVISORY section MUST carry a ProvenanceRecord
    for sec in dossier.sections:
        if sec.source_type == DossierSectionSourceType.AI_ADVISORY:
            assert sec.provenance is not None
            assert len(sec.provenance.input_hash) == 64
        elif sec.source_type in (
            DossierSectionSourceType.DETERMINISTIC,
            DossierSectionSourceType.STRUCTURAL,
        ):
            # Deterministic and structural sections do not masquerade as AI
            pass

    md = compiler.to_markdown(dossier)
    assert "# Institutional Quantitative Research Dossier" in md
    assert "Institutional Disclaimer" in md
    assert "[AI_ADVISORY]" in md
    assert "[DETERMINISTIC]" in md


def test_research_dossier_compiler_with_forecast_and_vision() -> None:
    """Compiler seamlessly integrates forecast and vision artifacts as AI_ADVISORY."""
    strategy = create_nifty_iron_condor_dsl()
    compiler = ResearchDossierCompiler()

    # Generate synthetic forecast
    now = datetime(2026, 6, 1, 9, 30, tzinfo=UTC)
    bars = [
        Bar(
            timestamp=now - timedelta(minutes=5 * i),
            open=24000,
            high=24050,
            low=23950,
            close=24010,
            volume=5000,
        )
        for i in range(10, 0, -1)
    ]
    fc_engine = HeuristicForecastEngine()
    fc_res = fc_engine.forecast(bars, horizon_bars=3)

    # Synthetic vision result
    vis_res = VisionResult(
        trend="Bullish",
        support=[23900.0, 24000.0],
        resistance=[24200.0, 24350.0],
        patterns=[PatternObservation(name="Bull Flag", confidence=0.85)],
        reasoning="Strong higher-highs and volume confirmation.",
        source_image_hash="b" * 64,
        provenance=ProvenanceRecord(
            source_type=AISourceType.MULTIMODAL_VISION,
            model_id="gemini-2.0-flash",
            model_version="1.0.0",
            provider="google",
            input_hash="b" * 64,
        ),
    )

    dossier = compiler.compile(
        strategy=strategy,
        forecast_result=fc_res,
        vision_result=vis_res,
    )

    titles = [s.title for s in dossier.sections]
    assert "Probabilistic Market Forecast" in titles
    assert "Multimodal Chart Vision & Structural Extractions" in titles

    md = compiler.to_markdown(dossier)
    assert "gemini-2.0-flash" in md
    assert "Probabilistic Market Forecast" in md
