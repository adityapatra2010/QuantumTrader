"""Provider credential resolution interfaces and secure local storage mechanisms.

Per Security Standards & ADR 012:
- Zero hardcoded credentials or tokens in code, DSLs, or research artifacts.
- Local environment resolution (os.environ) with explicit failure on missing keys.
- Never logs, serializes, or leaks secret values.
"""

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping

from aditrader.ai.errors import AICredentialError


class AICredentialResolver(ABC):
    """Abstract interface for resolving provider API credentials."""

    @abstractmethod
    def get_credential(self, provider: str, key_name: str = "api_key") -> str:
        """Retrieve credential secret for the specified provider.

        Raises:
            AICredentialError: If credential is missing or blank.
        """
        ...

    @abstractmethod
    def has_credential(self, provider: str, key_name: str = "api_key") -> bool:
        """Return True if credential exists and is non-empty."""
        ...


class EnvCredentialResolver(AICredentialResolver):
    """Resolves credentials from system environment variables."""

    def __init__(self, custom_env_map: Mapping[tuple[str, str], str] | None = None) -> None:
        # Optional explicit mapping of (provider, key_name) -> ENV_VAR_NAME
        self._custom_env_map = dict(custom_env_map or {})

    def _resolve_env_var_name(self, provider: str, key_name: str) -> str:
        pair = (provider.lower(), key_name.lower())
        if pair in self._custom_env_map:
            return self._custom_env_map[pair]
        # Standard convention: {PROVIDER}_{KEY} e.g. GOOGLE_API_KEY, KOTAK_API_KEY
        return f"{provider.upper()}_{key_name.upper()}"

    def get_credential(self, provider: str, key_name: str = "api_key") -> str:
        env_var = self._resolve_env_var_name(provider, key_name)
        val = os.environ.get(env_var)
        if not val or not val.strip():
            raise AICredentialError(
                f"Missing required credential '{key_name}' for AI provider '{provider}'. "
                f"Environment variable '{env_var}' is not set or empty."
            )
        return val.strip()

    def has_credential(self, provider: str, key_name: str = "api_key") -> bool:
        env_var = self._resolve_env_var_name(provider, key_name)
        val = os.environ.get(env_var)
        return bool(val and val.strip())


class DictCredentialResolver(AICredentialResolver):
    """In-memory credential resolver for test fixtures and isolated environments."""

    def __init__(self, credentials: Mapping[str, Mapping[str, str]] | None = None) -> None:
        self._creds: dict[str, dict[str, str]] = {}
        if credentials:
            for p, keys in credentials.items():
                self._creds[p.lower()] = {
                    k.lower(): v.strip() for k, v in keys.items() if v.strip()
                }

    def set_credential(self, provider: str, key_name: str, secret: str) -> None:
        """Store or update a credential in memory."""
        p = provider.lower()
        if p not in self._creds:
            self._creds[p] = {}
        self._creds[p][key_name.lower()] = secret.strip()

    def get_credential(self, provider: str, key_name: str = "api_key") -> str:
        p = provider.lower()
        k = key_name.lower()
        if p not in self._creds or k not in self._creds[p] or not self._creds[p][k]:
            raise AICredentialError(
                f"Missing required credential '{key_name}' for AI provider '{provider}'"
            )
        return self._creds[p][k]

    def has_credential(self, provider: str, key_name: str = "api_key") -> bool:
        p = provider.lower()
        k = key_name.lower()
        return bool(p in self._creds and k in self._creds[p] and self._creds[p][k])
