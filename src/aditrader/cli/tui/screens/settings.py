"""Settings and system diagnostics screen for the TUI Workstation."""

from __future__ import annotations

from typing import Any

from aditrader.cli.tui.colors import (
    PAIR_ACCENT,
    PAIR_BORDER,
    PAIR_CARD_TITLE,
    PAIR_DEFAULT,
    PAIR_MUTED,
    PAIR_SUCCESS,
    PAIR_WARNING,
    get_attr,
)
from aditrader.cli.tui.screens import draw_box, safe_addstr
from aditrader.cli.tui.state import TUIState
from aditrader.system.operations import SystemOperationsService


class SettingsScreen:
    """Renders doctor diagnostics, database table management, and masked provider configurations."""

    @classmethod
    def render(cls, win: Any, state: TUIState) -> None:
        max_y, max_x = win.getmaxyx()

        if "settings_diag" not in state.cache:
            try:
                state.cache["settings_diag"] = SystemOperationsService.run_diagnostics()
            except Exception as e:
                state.cache["settings_diag"] = {"error": str(e)}

        diag = state.cache.get("settings_diag", {})

        col1_w = min(48, max(36, int(max_x * 0.44)))
        col2_w = max_x - col1_w - 6

        # --- Left Panel: Diagnostics Audit (Doctor) ---
        draw_box(
            win,
            top=1,
            left=2,
            height=max_y - 3,
            width=col1_w,
            title="System Diagnostics & Readiness",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        y = 3
        sys_info = diag.get("system", {})
        safe_addstr(
            win,
            y,
            4,
            f"Python Runtime:   {sys_info.get('python', '3.11+')}",
            get_attr(PAIR_DEFAULT),
        )
        safe_addstr(
            win,
            y + 1,
            4,
            f"Operating System: {sys_info.get('os', 'Linux')} ({sys_info.get('arch', 'x86_64')})",
            get_attr(PAIR_DEFAULT),
        )
        safe_addstr(
            win,
            y + 2,
            4,
            f"Market Timezone:  {sys_info.get('timezone', 'Asia/Kolkata')}",
            get_attr(PAIR_DEFAULT),
        )
        y += 4

        safe_addstr(win, y, 4, "─── Core Subsystems Status ───", get_attr(PAIR_CARD_TITLE))
        y += 1
        db = diag.get("database", {})
        db_st = "[OK] Connected" if db.get("connected") else "[PENDING] Disconnected"
        db_col = PAIR_SUCCESS if db.get("connected") else PAIR_WARNING
        safe_addstr(win, y, 4, f"SQLite Ledger:    {db_st}", get_attr(db_col))
        safe_addstr(
            win,
            y + 1,
            4,
            f"Database Tables:  {len(db.get('tables', []))} tables active",
            get_attr(PAIR_MUTED),
        )
        y += 3

        kotak = diag.get("kotak_neo", {})
        sdk_st = "[OK] Installed" if kotak.get("has_sdk") else "[FALLBACK] Mock"
        sdk_col = PAIR_SUCCESS if kotak.get("has_sdk") else PAIR_MUTED
        safe_addstr(win, y, 4, f"Kotak Neo SDK:    {sdk_st}", get_attr(sdk_col))
        safe_addstr(
            win,
            y + 1,
            4,
            f"Feed Mode:        {kotak.get('feed_status', 'SIMULATED')}",
            get_attr(PAIR_ACCENT),
        )
        y += 3

        safe_addstr(win, y, 4, "─── Administrative Actions ───", get_attr(PAIR_CARD_TITLE))
        y += 1
        safe_addstr(
            win,
            y,
            4,
            "[i]  Initialize / Migrate SQLite Ledger Tables",
            get_attr(PAIR_ACCENT, bold=True),
        )
        safe_addstr(
            win, y + 1, 4, "[d]  Re-run full system diagnostics check", get_attr(PAIR_DEFAULT)
        )
        safe_addstr(win, y + 2, 4, "[r]  Reload settings from environment", get_attr(PAIR_DEFAULT))

        # --- Right Panel: Masked Provider Credentials & Security ---
        draw_box(
            win,
            top=1,
            left=col1_w + 4,
            height=max_y - 3,
            width=col2_w,
            title="Provider Credentials & Security Guardrails",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        ry = 3
        rx = col1_w + 6

        safe_addstr(
            win, ry, rx, "─── Broker Credentials (Strictly Masked) ───", get_attr(PAIR_CARD_TITLE)
        )
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            f"Consumer Key:     {kotak.get('consumer_key_configured') and 'Configured (Masked)' or 'Not configured'}",
            get_attr(PAIR_DEFAULT),
        )
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            f"Registered Mobile:{kotak.get('mobile_masked', 'Not configured')}",
            get_attr(PAIR_DEFAULT),
        )
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            f"Client UCC:       {kotak.get('ucc_masked', 'Not configured')}",
            get_attr(PAIR_DEFAULT),
        )
        ry += 2

        safe_addstr(
            win, ry, rx, "─── AI Research Providers (Advisory Only) ───", get_attr(PAIR_CARD_TITLE)
        )
        ry += 1
        anthropic = diag.get("anthropic", {})
        gemini = diag.get("gemini", {})
        ant_st = (
            "Configured" if anthropic.get("configured") else "Not configured (Local AST fallback)"
        )
        gem_st = "Configured" if gemini.get("configured") else "Not configured (Local OCR fallback)"
        safe_addstr(win, ry, rx, f"Claude / Anthropic: {ant_st}", get_attr(PAIR_DEFAULT))
        ry += 1
        safe_addstr(win, ry, rx, f"Gemini Vision:      {gem_st}", get_attr(PAIR_DEFAULT))
        ry += 2

        safe_addstr(win, ry, rx, "─── Security Invariants (ADR 002) ───", get_attr(PAIR_CARD_TITLE))
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            "• Live Broker Orders:   PHYSICALLY BLOCKED (air-gapped)",
            get_attr(PAIR_SUCCESS, bold=True),
        )
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            "• Dynamic Code Eval:    FORBIDDEN (AST state machines only)",
            get_attr(PAIR_SUCCESS),
        )
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            "• Options Historical:   AIR-GAPPED (Payoff verification only)",
            get_attr(PAIR_SUCCESS),
        )
        ry += 1
        safe_addstr(
            win,
            ry,
            rx,
            "• Session Storage:      Local memory / OS access controlled",
            get_attr(PAIR_MUTED),
        )

        safe_addstr(
            win,
            max_y - 4,
            rx,
            "[i] Init Database    [d] Refresh Diagnostics    [q] Exit TUI",
            get_attr(PAIR_CARD_TITLE),
        )

    @classmethod
    def handle_input(cls, key: int, state: TUIState) -> bool:
        """Handle settings administrative actions."""
        if key in (ord("d"), ord("D"), ord("r"), ord("R")):
            state.cache.pop("settings_diag", None)
            state.set_status("Diagnostics re-run successfully.", level="success")
            return True
        elif key in (ord("i"), ord("I")):
            state.set_status("Initializing SQLite ledger tables...", level="info")
            try:
                res = SystemOperationsService.initialize_database()
                state.cache.pop("settings_diag", None)
                state.set_status(
                    f"Database initialized: {res['message']} ({res['table_count']} tables)",
                    level="success",
                )
            except Exception as e:
                state.set_status(f"Database init failed: {e}", level="error")
            return True
        return False
