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

    # 1. Parse explicit premium_bands if provided
    raw_bands = mapped.get("premium_bands", mapped.get("bands", []))
    parsed_bands: list[dict[str, float]] = []
    if isinstance(raw_bands, list):
        for b in raw_bands:
            if isinstance(b, dict) and "min_ltp" in b and "max_ltp" in b:
                parsed_bands.append(
                    {
                        "min_ltp": float(b["min_ltp"]),
                        "max_ltp": float(b["max_ltp"]),
                    }
                )

    levels_raw = mapped.get("levels", [])
    parsed_levels: list[float] = []
    for lvl in levels_raw:
        if isinstance(lvl, dict) and "premium" in lvl:
            parsed_levels.append(float(lvl["premium"]))
        elif isinstance(lvl, (int, float)):
            parsed_levels.append(float(lvl))

    if parsed_levels:
        mapped["premium_levels"] = parsed_levels
        # If explicit bands were not supplied, synthesize standard bands [L, L + 9.5] per specification
        if not parsed_bands:
            for lvl in parsed_levels:
                parsed_bands.append({"min_ltp": float(lvl), "max_ltp": float(lvl) + 9.5})

    if parsed_bands:
        mapped["premium_bands"] = parsed_bands

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
            short_qty = int(short_block.get("quantity", short_block.get("lots", 1)))
            short_sel = short_block.get("selector", mapped.get("entry", {}).get("selector", {}))

            target_p = short_block.get("target_ltp", short_sel.get("target_ltp"))
            min_p = short_block.get("min_ltp", short_sel.get("min_ltp"))
            max_p = short_block.get("max_ltp", short_sel.get("max_ltp"))

            if target_p is None and parsed_levels:
                target_p = parsed_levels[0]

            # If range bounds not directly given in short block, use first band if available
            if min_p is None and max_p is None and parsed_bands:
                min_p = parsed_bands[0]["min_ltp"]
                max_p = parsed_bands[0]["max_ltp"]

            sel_type = short_sel.get("type")
            if sel_type is None:
                sel_type = (
                    "premium_range"
                    if (min_p is not None and max_p is not None)
                    else "premium_target"
                )

            sel_dict: dict[str, Any] = {
                "type": sel_type,
                "option_type": short_block.get("option_type", short_sel.get("option_type", "CE")),
                "underlying": mapped.get("underlying", "NIFTY"),
            }
            if min_p is not None:
                sel_dict["min_ltp"] = float(min_p)
            if max_p is not None:
                sel_dict["max_ltp"] = float(max_p)
            if target_p is not None:
                sel_dict["target_ltp"] = float(target_p)
            elif min_p is not None and max_p is not None:
                sel_dict["target_ltp"] = (float(min_p) + float(max_p)) / 2.0
            else:
                sel_dict["target_ltp"] = 50.0

            sel_dict["tolerance"] = float(short_sel.get("tolerance", 5.0))

            legs_list.append(
                {
                    "contract_type": sel_dict["option_type"],
                    "side": short_action,
                    "lots": short_qty,
                    "contract_selector": sel_dict,
                    "trailing_stop": trailing_stop_dict,
                }
            )

        if "hedge" in mapped:
            hedge_block = mapped["hedge"]
            hedge_action = str(hedge_block.get("action", "BUY")).upper()
            hedge_qty = int(hedge_block.get("quantity", hedge_block.get("lots", 4)))
            h_sel = hedge_block.get("selector", {})
            h_target = float(hedge_block.get("target_ltp", h_sel.get("target_ltp", 5.0)))
            h_tol = float(hedge_block.get("tolerance", h_sel.get("tolerance", 2.0)))
            h_opt = hedge_block.get("option_type", h_sel.get("option_type", "CE"))

            legs_list.append(
                {
                    "contract_type": h_opt,
                    "side": hedge_action,
                    "lots": hedge_qty,
                    "contract_selector": {
                        "type": "premium_target",
                        "target_ltp": h_target,
                        "tolerance": h_tol,
                        "option_type": h_opt,
                        "underlying": mapped.get("underlying", "NIFTY"),
                    },
                    "trailing_stop": None,  # Hedge never inherits trailing stop
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
    for k in ("levels", "short", "hedge", "stop", "entry", "bands"):
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

        # If declarative options structure is detected, map it into canonical StrategyDSL
        if any(k in raw_data for k in ("short", "hedge", "levels", "bands", "premium_bands")):
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
