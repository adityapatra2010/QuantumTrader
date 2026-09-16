"""Strategies catalog screen for the TUI Workstation."""

from __future__ import annotations

import curses
import json
from typing import Any

from aditrader.cli.tui.colors import (
    PAIR_ACCENT,
    PAIR_BORDER,
    PAIR_CARD_TITLE,
    PAIR_DEFAULT,
    PAIR_ERROR,
    PAIR_MUTED,
    PAIR_SELECTED_ROW,
    PAIR_SUCCESS,
    PAIR_WARNING,
    get_attr,
)
from aditrader.cli.tui.screens import draw_box, safe_addstr
from aditrader.cli.tui.state import TUIState
from aditrader.strategy.library.registry import StrategyRegistry


class StrategiesScreen:
    """Renders registered institutional strategy templates with full DNA profiling."""

    @staticmethod
    def _load_strategies(state: TUIState) -> list[dict[str, Any]]:
        if "strategies_list" not in state.cache:
            try:
                registry = StrategyRegistry()
                templates = registry.list_all()
                data: list[dict[str, Any]] = []
                for rec in templates:
                    strat_id = rec.id
                    strat_name = rec.name
                    is_opt = bool(rec.dsl_definition.legs)
                    data.append(
                        {
                            "id": strat_id,
                            "name": strat_name,
                            "type": "Options Multi-Leg" if is_opt else "Equity/Futures Linear",
                            "asset_class": "Options" if is_opt else "Equity/Index",
                            "eligibility": "Theoretical Payoff Only (ADR 011)"
                            if is_opt
                            else "Deterministic Historical Replay",
                            "raw_obj": rec.dsl_definition,
                        }
                    )
                state.cache["strategies_list"] = data
            except Exception:
                state.cache["strategies_list"] = []
        return list(state.cache.get("strategies_list", []))

    @classmethod
    def render(cls, win: Any, state: TUIState) -> None:
        max_y, max_x = win.getmaxyx()
        strategies = cls._load_strategies(state)

        if not strategies:
            safe_addstr(win, 2, 4, "No registered strategy templates found.", get_attr(PAIR_ERROR))
            return

        # Clamp selection
        if state.selected_index >= len(strategies):
            state.selected_index = len(strategies) - 1

        # Two-column layout: Left column = table (40% width), Right column = details (60% width)
        col1_w = min(42, max(32, int(max_x * 0.38)))
        col2_w = max_x - col1_w - 6

        # --- Left Panel: Strategy Catalog List ---
        draw_box(
            win,
            top=1,
            left=2,
            height=max_y - 3,
            width=col1_w,
            title=f"Catalog ({len(strategies)} Templates)",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        visible_rows = max_y - 6
        start_row = max(
            0, min(state.selected_index - visible_rows // 2, len(strategies) - visible_rows)
        )

        for idx in range(start_row, min(len(strategies), start_row + visible_rows)):
            item = strategies[idx]
            y = 3 + (idx - start_row)
            is_sel = idx == state.selected_index
            name_text = f" {item['name'][: col1_w - 6]} "
            if is_sel:
                safe_addstr(
                    win, y, 4, f"{name_text:<{col1_w - 5}}", get_attr(PAIR_SELECTED_ROW, bold=True)
                )
            else:
                type_color = PAIR_ACCENT if "Options" in item["type"] else PAIR_DEFAULT
                safe_addstr(win, y, 4, f"• {item['name'][: col1_w - 6]}", get_attr(type_color))

        # --- Right Panel: Selected Strategy DNA & Specification ---
        sel_item = strategies[state.selected_index]
        draw_box(
            win,
            top=1,
            left=col1_w + 4,
            height=max_y - 3,
            width=col2_w,
            title=f"Strategy DNA: {sel_item['name']}",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        ry = 3
        rx = col1_w + 6

        safe_addstr(
            win, ry, rx, f"Strategy ID:      {sel_item['id']}", get_attr(PAIR_DEFAULT, bold=True)
        )
        ry += 1
        safe_addstr(win, ry, rx, f"Structure Type:   {sel_item['type']}", get_attr(PAIR_ACCENT))
        ry += 1

        elig_color = PAIR_WARNING if "Theoretical" in sel_item["eligibility"] else PAIR_SUCCESS
        safe_addstr(
            win,
            ry,
            rx,
            f"Replay Status:    {sel_item['eligibility']}",
            get_attr(elig_color, bold=True),
        )
        ry += 2

        # Check if special NIFTY CE Ladder
        if "ladder" in sel_item["name"].lower():
            safe_addstr(
                win,
                ry,
                rx,
                "─── Dynamic Premium Bands & Ratio Hedge Structure ───",
                get_attr(PAIR_CARD_TITLE),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "Short Leg:        1x dynamic CE inside active premium band (₹50-₹110)",
                get_attr(PAIR_DEFAULT),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "Hedge Wings:      4x CE dynamic wings near target ₹5.00 ± ₹2.00",
                get_attr(PAIR_DEFAULT),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "Trailing Stop:    Contract-bound trailing ratchet stop (e.g. 50→40=>SL 45)",
                get_attr(PAIR_DEFAULT),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "Active Bands:     6 bands: ₹50-₹59.5, ₹60-₹69.5, ₹70-₹79.5,",
                get_attr(PAIR_MUTED),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "                  ₹80-₹89.5, ₹90-₹99.5, ₹100-₹109.5",
                get_attr(PAIR_MUTED),
            )
            ry += 2
        else:
            safe_addstr(
                win, ry, rx, "─── Institutional Strategy DNA Vector ───", get_attr(PAIR_CARD_TITLE)
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "Execution Gate:   Institutional Expectancy (E > 0, PF >= 1.25)",
                get_attr(PAIR_DEFAULT),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "Max Drawdown Cap: 20.0% Portfolio Equity Limit",
                get_attr(PAIR_DEFAULT),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                "Execution Model:  NEXT_BAR_OPEN (Zero Lookahead, Clamped Envelopes)",
                get_attr(PAIR_DEFAULT),
            )
            ry += 2

        safe_addstr(win, ry, rx, "─── Actions Available ───", get_attr(PAIR_CARD_TITLE))
        ry += 1
        safe_addstr(
            win, ry, rx, "[Enter / d]  View JSON AST definition & parameters", get_attr(PAIR_ACCENT)
        )
        ry += 1
        safe_addstr(win, ry, rx, "[v]          Send to Validation Studio", get_attr(PAIR_ACCENT))
        ry += 1
        safe_addstr(win, ry, rx, "[s]          Send to Simulation Workspace", get_attr(PAIR_ACCENT))

    @classmethod
    def handle_input(cls, key: int, state: TUIState) -> bool:
        """Handle strategy navigation keystrokes."""
        strategies = cls._load_strategies(state)
        if not strategies:
            return False

        if key in (curses.KEY_UP, ord("k")):
            state.selected_index = max(0, state.selected_index - 1)
            return True
        elif key in (curses.KEY_DOWN, ord("j")):
            state.selected_index = min(len(strategies) - 1, state.selected_index + 1)
            return True
        elif key in (curses.KEY_ENTER, 10, 13, ord("d"), ord("D")):
            sel = strategies[state.selected_index]
            lines = [
                f"Strategy: {sel['name']}",
                f"ID:       {sel['id']}",
                f"Type:     {sel['type']}",
                f"Status:   {sel['eligibility']}",
                "",
                "--- AST Specification Summary ---",
            ]
            raw = sel.get("raw_obj")
            if raw is not None and hasattr(raw, "model_dump_json"):
                dumped = raw.model_dump_json(indent=2)
                lines.extend(dumped.splitlines())
            elif isinstance(raw, dict):
                lines.extend(json.dumps(raw, indent=2).splitlines())
            state.show_dialog(f"Strategy: {sel['name']}", lines)
            return True
        elif key in (ord("v"), ord("V")):
            # Jump to validation tab with this strategy selected
            state.current_tab = 3
            state.set_status(
                f"Loaded '{strategies[state.selected_index]['name']}' into Validation Studio.",
                level="success",
            )
            return True
        elif key in (ord("s"), ord("S")):
            # Jump to simulation tab
            state.current_tab = 4
            state.set_status(
                f"Loaded '{strategies[state.selected_index]['name']}' into Simulation Workspace.",
                level="success",
            )
            return True
        return False
