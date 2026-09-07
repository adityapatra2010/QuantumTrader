"""Safe YAML loader for declarative StrategyDSL AST specifications.

Per ADR 001 and ADR 007:
- Uses yaml.safe_load strictly (no dynamic object instantiation).
- Enforces top-level schema_version == "1.0".
"""

from pathlib import Path
from typing import Any

import yaml

from aditrader.strategy.builder.schema import StrategyDSL


class YAMLStrategyLoader:
    """Loads and validates StrategyDSL definitions from YAML text or files."""

    @classmethod
    def load_from_str(cls, yaml_content: str) -> StrategyDSL:
        """Parse and validate YAML string into StrategyDSL."""
        try:
            raw_data: Any = yaml.safe_load(yaml_content)
        except Exception as exc:
            raise ValueError(f"Failed to parse YAML content: {exc}") from exc

        if not isinstance(raw_data, dict):
            raise ValueError(f"YAML root must be a mapping/dict, got {type(raw_data).__name__}")

        schema_ver = str(raw_data.get("schema_version", ""))
        if schema_ver != "1.0":
            raise ValueError(f"Unsupported schema_version '{schema_ver}'. Only '1.0' is supported.")

        return StrategyDSL.model_validate(raw_data)

    @classmethod
    def load_from_file(cls, file_path: str | Path) -> StrategyDSL:
        """Read and validate a .yaml or .yml strategy specification file."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Strategy YAML file not found: {path}")

        content = path.read_text(encoding="utf-8")
        return cls.load_from_str(content)
