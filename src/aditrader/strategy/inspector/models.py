"""Pydantic data models for strategy discovery, inspection, and compatibility auditing."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyFormat(StrEnum):
    """Classification of recognized external and native strategy formats."""

    JSON_DSL = "JSON_DSL"
    YAML_DSL = "YAML_DSL"
    PINE_SCRIPT = "PINE_SCRIPT"
    EASYLANGUAGE = "EASYLANGUAGE"
    AMIBROKER_AFL = "AMIBROKER_AFL"
    THINKSCRIPT = "THINKSCRIPT"
    METATRADER_MQL4 = "METATRADER_MQL4"
    METATRADER_MQL5 = "METATRADER_MQL5"
    NINJATRADER = "NINJATRADER"
    QUANTCONNECT_LEAN = "QUANTCONNECT_LEAN"
    PYTHON_BACKTRADER = "PYTHON_BACKTRADER"
    PYTHON_VECTORBT = "PYTHON_VECTORBT"
    PYTHON_FREQTRADE = "PYTHON_FREQTRADE"
    PYTHON_GENERIC = "PYTHON_GENERIC"
    UNKNOWN = "UNKNOWN"


class StrategyScriptType(StrEnum):
    """Classification between actionable execution strategy and display indicator."""

    STRATEGY = "STRATEGY"
    INDICATOR = "INDICATOR"
    UNKNOWN = "UNKNOWN"


class TranslationStatus(StrEnum):
    """Compatibility classification of strategy representation."""

    SUPPORTED = "SUPPORTED"
    TRANSLATABLE = "TRANSLATABLE"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INSPECT_ONLY = "INSPECT_ONLY"
    UNSUPPORTED = "UNSUPPORTED"
    REJECTED_LOOKAHEAD = "REJECTED_LOOKAHEAD"


class FidelityLevel(StrEnum):
    """Semantic integrity fidelity rating for translated strategy rules."""

    EXACT = "EXACT"
    EQUIVALENT = "EQUIVALENT"
    APPROXIMATED = "APPROXIMATED"
    UNSUPPORTED = "UNSUPPORTED"
    VISUAL_ONLY = "VISUAL_ONLY"


class ConstructFidelity(BaseModel):
    """Classification of an individual script construct and its semantic mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Construct or feature name")
    category: str = Field(
        ...,
        description="Construct category (e.g. entry, exit, timing, state, calculation, visual, directive)",
    )
    fidelity: FidelityLevel = Field(..., description="Fidelity level classification")
    details: str = Field(..., description="Explanation of mapping, approximation, or limitation")
    translatable: bool = Field(
        default=False, description="Whether construct is directly translatable to StrategyDSL"
    )


class PortabilityAssessment(BaseModel):
    """Assessment of assumptions when porting strategies across instruments or asset classes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_instrument_hint: str | None = Field(
        default=None, description="Inferred original benchmark/instrument (e.g. 'XAUUSD')"
    )
    target_instrument_hint: str | None = Field(
        default=None, description="Declared target asset or market (e.g. 'MCX Gold (India)')"
    )
    assumptions_preserved: list[str] = Field(
        default_factory=list, description="Mathematical/technical assumptions that remain valid"
    )
    assumptions_changed: list[str] = Field(
        default_factory=list,
        description="Contract/operational assumptions that differ significantly",
    )
    assumptions_unknown: list[str] = Field(
        default_factory=list, description="Unverifiable assumptions requiring user confirmation"
    )
    unsafe_mappings: list[str] = Field(
        default_factory=list,
        description="Critical risks (e.g. capital adequacy, session hours, margin)",
    )
    portability_verdict: str = Field(..., description="Overall verdict on portability safety")


class StrategyInspectionReport(BaseModel):
    """Immutable diagnostic report evaluating strategy compatibility, AST syntax, and safety."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str = Field(..., description="Path to inspected strategy file")
    file_size_bytes: int = Field(..., ge=0, description="Size of file on disk in bytes")
    detected_format: StrategyFormat = Field(..., description="Detected format category")
    language: str = Field(..., description="Underlying language/framework name")
    version_detected: str | None = Field(
        default=None, description="Language or schema version (e.g. v5, 1.0)"
    )
    script_type: StrategyScriptType = Field(
        default=StrategyScriptType.UNKNOWN, description="STRATEGY vs INDICATOR"
    )
    strategy_name: str | None = Field(default=None, description="Extracted strategy title")
    underlying_detected: str | None = Field(
        default=None, description="Target asset symbol if specified in code"
    )
    timeframe_detected: str | None = Field(
        default=None, description="Target bar timeframe if specified in code"
    )
    supported_constructs: list[str] = Field(
        default_factory=list, description="List of recognized constructs compatible with AST"
    )
    unsupported_constructs: list[str] = Field(
        default_factory=list, description="List of features requiring external/imperative runtimes"
    )
    has_lookahead_risk: bool = Field(
        default=False, description="True if repainting or lookahead_on is detected"
    )
    has_intrabar_risk: bool = Field(
        default=False, description="True if script assumes tick-level intrabar order fills"
    )
    has_options_legs: bool = Field(
        default=False, description="True if strategy defines multi-leg options structures"
    )
    translation_status: TranslationStatus = Field(
        default=TranslationStatus.UNSUPPORTED, description="Translational compatibility status"
    )
    fidelity_level: FidelityLevel = Field(
        default=FidelityLevel.UNSUPPORTED, description="Semantic mapping accuracy rating"
    )
    validation_ready: bool = Field(
        default=False, description="True if strategy passes static AST schema validation"
    )
    simulation_ready: bool = Field(
        default=False, description="True if strategy can be replayed in deterministic backtest"
    )
    forward_test_ready: bool = Field(
        default=False,
        description="True if strategy can be run in live/rehearsal paper forward test",
    )
    rejection_reasons: list[str] = Field(
        default_factory=list, description="Actionable explanations for why file was rejected"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Diagnostic warnings found during inspection"
    )

    # Detailed semantic diagnostics
    detected_constructs: list[ConstructFidelity] = Field(
        default_factory=list, description="Granular construct classifications"
    )
    entry_mechanisms: list[str] = Field(
        default_factory=list, description="Order entry triggers and mechanisms"
    )
    exit_mechanisms: list[str] = Field(
        default_factory=list, description="Order exit triggers and mechanisms"
    )
    persistent_state_vars: list[str] = Field(
        default_factory=list, description="Detected mutable persistent state variables (var/varip)"
    )
    time_conditions: list[str] = Field(
        default_factory=list, description="Detected time or session conditions"
    )
    indicators_used: list[str] = Field(
        default_factory=list, description="Technical indicators referenced in code"
    )
    custom_calculations: list[str] = Field(
        default_factory=list,
        description="Detected custom arithmetic formulas or synthetic calculations",
    )
    position_semantics: str | None = Field(
        default=None, description="Actual order position semantics (e.g. Long underlying)"
    )
    option_leg_semantics: str | None = Field(
        default=None, description="Option-leg structure analysis (actual vs simulated)"
    )
    naming_behavior_mismatch: str | None = Field(
        default=None, description="Discrepancy between title/naming and actual executed code"
    )
    custom_pnl_detected: bool = Field(
        default=False, description="True if script calculates synthetic arithmetic P&L"
    )
    custom_pnl_details: dict[str, Any] | None = Field(
        default=None, description="Detailed diagnostic breakdown of custom P&L calculation"
    )
    order_behavior_notes: list[str] = Field(
        default_factory=list, description="Semantic differences vs PaperBroker execution"
    )
    visual_only_constructs: list[str] = Field(
        default_factory=list, description="Detected visualization directives (plot, fill, etc.)"
    )
    portability_assessment: PortabilityAssessment | None = Field(
        default=None,
        description="Instrument-portability audit assessing asset-class assumption mismatches",
    )
