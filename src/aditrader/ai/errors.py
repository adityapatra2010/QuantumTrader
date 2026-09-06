"""Typed exception hierarchy and failure contracts for AI subsystems.

Per ADR 012:
- AI failures must never fail open or fabricate deterministic evidence.
- Degraded mode operations handle these exceptions cleanly without blocking core workflows.
"""


class AIError(Exception):
    """Base exception for all AI advisory subsystem failures."""


class AIUnavailableError(AIError):
    """Raised when an AI model, provider, or local compute backend is offline or unconfigured."""


class AITimeoutError(AIError):
    """Raised when an AI inference or external API call exceeds the configured deadline."""


class AIMalformedOutputError(AIError):
    """Raised when an AI model output fails schema parsing, boundary assertions, or contract validation."""


class AIProviderError(AIError):
    """Raised when an external model provider returns an error (rate limit, quota, server failure)."""


class AILowConfidenceError(AIError):
    """Raised when model inference confidence falls below acceptable operational thresholds."""


class AILookaheadError(AIError):
    """Raised when an AI forecast or signal violates point-in-time chronological boundaries."""


class AIConfigError(AIError):
    """Raised when an AI provider, model, or subsystem is misconfigured."""


class AICredentialError(AIConfigError):
    """Raised when required credentials or API keys for an AI provider are missing or invalid."""


class AIModelNotFoundError(AIConfigError):
    """Raised when a requested AI model is not registered in the catalog."""


class AIProviderNotFoundError(AIConfigError):
    """Raised when a requested AI provider is not registered in the registry."""


class AIUnsupportedCapabilityError(AIError):
    """Raised when an operation requires an AI model capability not supported by the selected model."""
