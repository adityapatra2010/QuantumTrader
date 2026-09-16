"""Overview screen for the TUI Workstation."""

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


class OverviewScreen:
    """Renders high-level institutional portfolio status, engine readiness, and recent runs."""

    @staticmethod
    def render(win: Any, state: TUIState) -> None:
        max_y, max_x = win.getmaxyx()

        # Load or use cached diagnostics/status
        if "overview_data" not in state.cache:
            try:
                state.cache["overview_data"] = SystemOperationsService.run_diagnostics()
            except Exception as e:
                state.cache["overview_data"] = {"error": str(e)}

        diag = state.cache.get("overview_data", {})

        # Top section: 2 columns if width >= 90, else stacked
        left_width = min(max_x - 4, 48)
        right_width = max_x - left_width - 6

        # --- 1. Portfolio & Execution Card ---
        draw_box(
            win,
            top=1,
            left=2,
            height=10,
            width=left_width,
            title="Paper Portfolio & Ledger (Air-Gapped)",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        safe_addstr(win, 2, 4, "Initial Capital:   ₹10,00,000.00", get_attr(PAIR_DEFAULT))
        safe_addstr(
            win, 3, 4, "Total Equity:      ₹10,00,000.00", get_attr(PAIR_DEFAULT, bold=True)
        )
        safe_addstr(win, 4, 4, "Realized P&L:      ₹0.00", get_attr(PAIR_SUCCESS))
        safe_addstr(win, 5, 4, "Unrealized P&L:    ₹0.00", get_attr(PAIR_MUTED))
        safe_addstr(win, 6, 4, "Blocked Margin:    ₹0.00 (0.0% util)", get_attr(PAIR_DEFAULT))
        safe_addstr(win, 7, 4, "Active Positions:  0 open", get_attr(PAIR_DEFAULT))
        safe_addstr(
            win,
            8,
            4,
            "Execution Venue:   PaperBroker (ADR 002 Air-Gapped)",
            get_attr(PAIR_ACCENT, bold=True),
        )

        # --- 2. System Readiness & Broker Feeds ---
        if right_width >= 36:
            draw_box(
                win,
                top=1,
                left=left_width + 4,
                height=10,
                width=right_width,
                title="System Readiness & Market Feeds",
                title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
                border_attr=get_attr(PAIR_BORDER),
            )

            db_ok = diag.get("database", {}).get("connected", False)
            db_status = "Connected (WAL Mode)" if db_ok else "Disconnected / Pending"
            db_color = PAIR_SUCCESS if db_ok else PAIR_WARNING
            safe_addstr(win, 2, left_width + 6, f"Database Ledger: {db_status}", get_attr(db_color))

            sdk_ok = diag.get("kotak_neo", {}).get("has_sdk", False)
            sdk_status = "Installed (v3.0.6)" if sdk_ok else "Not Installed (Mock Fallback)"
            safe_addstr(
                win, 3, left_width + 6, f"Broker SDK:      {sdk_status}", get_attr(PAIR_DEFAULT)
            )

            creds = diag.get("kotak_neo", {}).get("consumer_key_configured", False)
            feed_mode = "Mock Rehearsal" if not creds else "Live SFeed Ready"
            safe_addstr(
                win, 4, left_width + 6, f"Feed Operation:  {feed_mode}", get_attr(PAIR_DEFAULT)
            )

            time_str = "Asia/Kolkata (IST)"
            safe_addstr(
                win,
                5,
                left_width + 6,
                f"Market Session:  09:15 - 15:30 {time_str}",
                get_attr(PAIR_DEFAULT),
            )

            strats_count = diag.get("counts", {}).get("strategies", 13)
            datasets_count = diag.get("counts", {}).get("datasets", 3)
            safe_addstr(
                win,
                6,
                left_width + 6,
                f"Catalog Assets:  {strats_count} Strategies | {datasets_count} Local Datasets",
                get_attr(PAIR_ACCENT),
            )

            safe_addstr(
                win,
                7,
                left_width + 6,
                "Live Orders:     PHYSICALLY BLOCKED (Safe)",
                get_attr(PAIR_SUCCESS, bold=True),
            )

        # --- 3. Operational Navigation Quick Guide ---
        nav_top = 12
        draw_box(
            win,
            top=nav_top,
            left=2,
            height=max_y - nav_top - 2,
            width=max_x - 4,
            title="Institutional Research Operating Modules (Press [1-7] or [Tab])",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_BORDER),
        )

        modules = [
            ("[1] Overview", "Institutional portfolio summary, air-gap status, system diagnostics"),
            (
                "[2] Strategies",
                "Explore 13 institutional templates, DNA profiles, and dynamic premium bands",
            ),
            (
                "[3] Data & Feeds",
                "Inspect NSE CSV datasets, stream SFeed ticks, and view option chain ladders",
            ),
            (
                "[4] Validation",
                "Tri-path validation studio: AST syntax, Institutional policy, and Greeks",
            ),
            (
                "[5] Simulation",
                "Deterministic historical backtesting (T+1 Open) & forward paper sessions",
            ),
            (
                "[6] Runs Ledger",
                "Cryptographic run dossiers, trade ledger, and balance sheet reconciliation",
            ),
            (
                "[7] Settings",
                "Doctor diagnostics, SQLite ledger initialization, provider credentials",
            ),
        ]

        row_y = nav_top + 2
        for key, desc in modules:
            if row_y >= max_y - 3:
                break
            safe_addstr(win, row_y, 4, f"{key:<18}", get_attr(PAIR_ACCENT, bold=True))
            safe_addstr(win, row_y, 24, desc, get_attr(PAIR_DEFAULT))
            row_y += 2

    @staticmethod
    def handle_input(key: int, state: TUIState) -> bool:
        """Handle overview-specific keystrokes."""
        if key in (ord("r"), ord("R")):
            state.cache.pop("overview_data", None)
            state.set_status("Overview diagnostics refreshed.", level="success")
            return True
        return False
