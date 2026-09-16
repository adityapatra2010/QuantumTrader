"""Data and feeds workspace screen for the TUI Workstation."""

from __future__ import annotations

import curses
from pathlib import Path
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
from aditrader.data.feeds.nse_csv import NSECSVInspector
from aditrader.system.operations import SystemOperationsService


class DataScreen:
    """Renders local CSV datasets, pre-replay quality diagnostics, and streaming feed status."""

    @staticmethod
    def _find_datasets(state: TUIState) -> list[dict[str, Any]]:
        if "datasets_list" not in state.cache:
            data_dir = Path("data")
            datasets: list[dict[str, Any]] = []
            if data_dir.exists():
                for p in sorted(data_dir.glob("*.csv")):
                    try:
                        diag = NSECSVInspector.inspect_file(p)
                        datasets.append(
                            {
                                "path": str(p),
                                "filename": p.name,
                                "format": diag.detected_format.value
                                if hasattr(diag.detected_format, "value")
                                else str(diag.detected_format),
                                "is_replayable": diag.is_valid_replayable,
                                "total_records": diag.parsed_bars,
                                "envelope_valid": not any(
                                    "envelope" in w.lower() for w in diag.quality_warnings
                                ),
                                "session_valid": not any(
                                    "session" in w.lower() or "gap" in w.lower()
                                    for w in diag.quality_warnings
                                ),
                                "start_time": diag.start_time or "N/A",
                                "end_time": diag.end_time or "N/A",
                                "raw_diag": diag,
                            }
                        )
                    except Exception:
                        datasets.append(
                            {
                                "path": str(p),
                                "filename": p.name,
                                "format": "UNKNOWN",
                                "is_replayable": False,
                                "total_records": 0,
                                "envelope_valid": False,
                                "session_valid": False,
                                "start_time": "N/A",
                                "end_time": "N/A",
                                "raw_diag": None,
                            }
                        )
            state.cache["datasets_list"] = datasets
        return list(state.cache.get("datasets_list", []))

    @classmethod
    def render(cls, win: Any, state: TUIState) -> None:
        max_y, max_x = win.getmaxyx()
        datasets = cls._find_datasets(state)

        col1_w = min(44, max(32, int(max_x * 0.40)))
        col2_w = max_x - col1_w - 6

        # --- Left Panel: Available Datasets ---
        draw_box(
            win,
            top=1,
            left=2,
            height=max_y - 3,
            width=col1_w,
            title=f"Datasets ({len(datasets)} Files)",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        if not datasets:
            safe_addstr(
                win, 3, 4, "No CSV datasets found in data/ directory.", get_attr(PAIR_WARNING)
            )
        else:
            if state.selected_index >= len(datasets):
                state.selected_index = len(datasets) - 1

            visible_rows = max_y - 6
            start_row = max(
                0, min(state.selected_index - visible_rows // 2, len(datasets) - visible_rows)
            )

            for idx in range(start_row, min(len(datasets), start_row + visible_rows)):
                item = datasets[idx]
                y = 3 + (idx - start_row)
                is_sel = idx == state.selected_index
                name_text = f" {item['filename'][: col1_w - 6]} "
                if is_sel:
                    safe_addstr(
                        win,
                        y,
                        4,
                        f"{name_text:<{col1_w - 5}}",
                        get_attr(PAIR_SELECTED_ROW, bold=True),
                    )
                else:
                    rep_color = PAIR_SUCCESS if item["is_replayable"] else PAIR_MUTED
                    safe_addstr(
                        win, y, 4, f"• {item['filename'][: col1_w - 6]}", get_attr(rep_color)
                    )

        # --- Right Panel: Pre-Replay Quality Diagnostics ---
        draw_box(
            win,
            top=1,
            left=col1_w + 4,
            height=max_y - 3,
            width=col2_w,
            title="Pre-Replay Data Quality & Market Feeds",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        ry = 3
        rx = col1_w + 6

        if datasets and state.selected_index < len(datasets):
            sel = datasets[state.selected_index]
            safe_addstr(
                win,
                ry,
                rx,
                f"File:             {sel['filename']}",
                get_attr(PAIR_DEFAULT, bold=True),
            )
            ry += 1
            safe_addstr(win, ry, rx, f"Detected Schema:  {sel['format']}", get_attr(PAIR_ACCENT))
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                f"Total Candles:    {sel['total_records']:,} bars",
                get_attr(PAIR_DEFAULT),
            )
            ry += 1
            safe_addstr(
                win,
                ry,
                rx,
                f"Temporal Range:   {sel['start_time']} → {sel['end_time']}",
                get_attr(PAIR_DEFAULT),
            )
            ry += 1

            status_str = (
                "VALID FOR REPLAY" if sel["is_replayable"] else "INSPECT ONLY (NOT REPLAYABLE)"
            )
            status_color = PAIR_SUCCESS if sel["is_replayable"] else PAIR_WARNING
            safe_addstr(
                win, ry, rx, f"Replay Status:    {status_str}", get_attr(status_color, bold=True)
            )
            ry += 2

            safe_addstr(
                win, ry, rx, "─── Data Integrity Audit Gates ───", get_attr(PAIR_CARD_TITLE)
            )
            ry += 1
            env_ok = (
                "PASS (Low ≤ Open, Close ≤ High)"
                if sel["envelope_valid"]
                else "FAIL (Envelope Breach)"
            )
            env_col = PAIR_SUCCESS if sel["envelope_valid"] else PAIR_ERROR
            safe_addstr(win, ry, rx, f"Price Envelope:   {env_ok}", get_attr(env_col))
            ry += 1

            sess_ok = (
                "PASS (09:15 - 15:30 IST Mon-Fri)"
                if sel["session_valid"]
                else "WARNING (Gaps / Non-continuous)"
            )
            sess_col = PAIR_SUCCESS if sel["session_valid"] else PAIR_WARNING
            safe_addstr(win, ry, rx, f"NSE Session:      {sess_ok}", get_attr(sess_col))
            ry += 2

        safe_addstr(win, ry, rx, "─── Market Data Feed Utilities ───", get_attr(PAIR_CARD_TITLE))
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            "[t]  Run Kotak Neo streaming tick smoke test (5 ticks)",
            get_attr(PAIR_ACCENT),
        )
        ry += 1
        safe_addstr(
            win, ry, rx, "[o]  Inspect live/mock NIFTY option chain ladder", get_attr(PAIR_ACCENT)
        )
        ry += 1
        safe_addstr(win, ry, rx, "[r]  Refresh dataset catalog from disk", get_attr(PAIR_DEFAULT))

    @classmethod
    def handle_input(cls, key: int, state: TUIState) -> bool:
        """Handle dataset navigation and smoke test triggers."""
        datasets = cls._find_datasets(state)

        if key in (curses.KEY_UP, ord("k")):
            if datasets:
                state.selected_index = max(0, state.selected_index - 1)
            return True
        elif key in (curses.KEY_DOWN, ord("j")):
            if datasets:
                state.selected_index = min(len(datasets) - 1, state.selected_index + 1)
            return True
        elif key in (ord("r"), ord("R")):
            state.cache.pop("datasets_list", None)
            state.set_status("Rescanned datasets from disk.", level="success")
            return True
        elif key in (ord("t"), ord("T")):
            state.set_status("Running safe tick smoke test...", level="info")
            try:
                res = SystemOperationsService.run_feed_smoke_test(
                    symbol="NIFTY", ticks=5, mock=True
                )
                lines = [
                    "=== Kotak Neo Streaming Smoke Test ===",
                    f"Symbol:           {res['symbol']}",
                    f"Mode:             {res['mode']}",
                    f"Ticks Received:   {res['received_ticks']}/{res['requested_ticks']}",
                    f"Average Latency:  {res['avg_latency_ms']} ms",
                    f"Duration:         {res['duration_sec']}s",
                    f"Air-Gap Verified: {res['air_gap_verified']}",
                    "",
                    "--- Sample Ticks Received ---",
                ]
                for t in res.get("ticks", [])[:5]:
                    lines.append(f"• {t['timestamp']} | LTP: ₹{t['ltp']} | Vol: {t['volume']}")
                state.show_dialog("Tick Smoke Test Result", lines)
            except Exception as e:
                state.set_status(f"Smoke test error: {e}", level="error")
            return True
        elif key in (ord("o"), ord("O")):
            state.set_status("Loading option chain ladder...", level="info")
            try:
                res = SystemOperationsService.get_option_chain_snapshot(
                    underlying="NIFTY", count=10, mock=True
                )
                lines = [
                    "=== NIFTY Option Chain Snapshot ===",
                    f"Underlying:   {res['underlying']}",
                    f"Spot Price:   ₹{res['spot_price']}",
                    f"Expiry:       {res['expiry']}",
                    f"Strike Count: {res['strike_count']}",
                    "",
                    f"{'Strike':<10} | {'CE LTP':<9} | {'CE IV':<8} | {'CE Delta':<9} | {'PE LTP':<9} | {'PE Delta':<9}",
                    "-" * 70,
                ]
                for row in res.get("strikes", [])[:15]:
                    ce_p = f"₹{row['ce_ltp']}" if row.get("ce_ltp") else "-"
                    ce_iv = f"{row['ce_iv']:.2%}" if row.get("ce_iv") else "-"
                    ce_d = f"{row['ce_delta']:.2f}" if row.get("ce_delta") else "-"
                    pe_p = f"₹{row['pe_ltp']}" if row.get("pe_ltp") else "-"
                    pe_d = f"{row['pe_delta']:.2f}" if row.get("pe_delta") else "-"
                    lines.append(
                        f"{row['strike']:<10} | {ce_p:<9} | {ce_iv:<8} | {ce_d:<9} | {pe_p:<9} | {pe_d:<9}"
                    )
                state.show_dialog("NIFTY Option Chain Ladder", lines)
            except Exception as e:
                state.set_status(f"Option chain error: {e}", level="error")
            return True
        return False
