"""Safe YAML loader for declarative StrategyDSL AST specifications.

Per ADR 001 and ADR 007:
- Uses yaml.safe_load strictly (no dynamic object instantiation).
- Enforces top-level schema_version == "1.0".
"""

from pathlib import Path
from typing import Any

import yaml

from aditrader.strategy.builder.schema import StrategyDSL


def _map_declarative_options_pattern(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Translate high-level declarative options pattern (Phase 5) into canonical StrategyDSL dict."""
    mapped = dict(raw_data)
    mapped["schema_version"] = "1.0"
    if "underlying" not in mapped:
        mapped["underlying"] = "NIFTY"
    if "timeframe" not in mapped:
        mapped["timeframe"] = "5m"

    levels_raw = mapped.get("levels", [])
    parsed_levels: list[float] = []
    for lvl in levels_raw:
        if isinstance(lvl, dict) and "premium" in lvl:
            parsed_levels.append(float(lvl["premium"]))
        elif isinstance(lvl, (int, float)):
            parsed_levels.append(float(lvl))
    if parsed_levels:
        mapped["premium_levels"] = parsed_levels

    if "legs" not in mapped and ("short" in mapped or "hedge" in mapped):
        legs_list: list[dict[str, Any]] = []

        stop_cfg = mapped.get("stop")
        trailing_stop_dict = None
        if isinstance(stop_cfg, dict):
            trailing_stop_dict = {
                "type": "premium_trailing",
                "initial_gap": float(stop_cfg.get("initial_gap", 5.0)),
                "trail_step": float(stop_cfg.get("trail_step", 5.0)),
                "ratchet": bool(stop_cfg.get("ratchet", True)),
            }

        if "short" in mapped:
            short_block = mapped["short"]
            short_action = str(short_block.get("action", "SELL")).upper()
            short_qty = int(short_block.get("quantity", 1))
            short_sel = short_block.get("selector", mapped.get("entry", {}).get("selector", {}))
            target_p = short_sel.get("target_ltp")
            if target_p is None and parsed_levels:
                target_p = parsed_levels[0]
            elif target_p is None:
                target_p = 50.0

            legs_list.append(
                {
                    "contract_type": short_sel.get("option_type", "CE"),
                    "side": short_action,
                    "lots": short_qty,
                    "contract_selector": {
                        "type": short_sel.get("type", "premium_target"),
                        "target_ltp": float(target_p),
                        "tolerance": float(short_sel.get("tolerance", 5.0)),
                        "option_type": short_sel.get("option_type", "CE"),
                    },
                    "trailing_stop": trailing_stop_dict,
                }
            )

        if "hedge" in mapped:
            hedge_block = mapped["hedge"]
            hedge_action = str(hedge_block.get("action", "BUY")).upper()
            hedge_qty = int(hedge_block.get("quantity", 4))
            h_sel = hedge_block.get("selector", {})
            h_target = float(h_sel.get("target_ltp", 5.0))
            legs_list.append(
                {
                    "contract_type": h_sel.get("option_type", "CE"),
                    "side": hedge_action,
                    "lots": hedge_qty,
                    "contract_selector": {
                        "type": h_sel.get("type", "premium_target"),
                        "target_ltp": h_target,
                        "tolerance": float(h_sel.get("tolerance", 1.0)),
                        "option_type": h_sel.get("option_type", "CE"),
                    },
                }
            )

        mapped["legs"] = legs_list

    if "entry_conditions" not in mapped:
        mapped["entry_conditions"] = {
            "operator": "AND",
            "conditions": [
                {
                    "category": "time",
                    "operator": "WITHIN_RANGE",
                    "field": "minute_of_day",
                    "range_min": 555,
                    "range_max": 915,
                }
            ],
        }

    # Clean up declarative shorthand keys that have been mapped into canonical fields
    for k in ("levels", "short", "hedge", "stop", "entry"):
        mapped.pop(k, None)

    return mapped


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

        # If declarative options structure is detected (levels, short, hedge), map it into canonical StrategyDSL
        if "short" in raw_data or "hedge" in raw_data or "levels" in raw_data:
            raw_data = _map_declarative_options_pattern(raw_data)

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
