"""Terminal User Interface (TUI) for AdiTrader / QuantumValidator.

Zero-dependency terminal workstation built on Python standard library curses.
Provides 100% operational parity with the CLI and Web GUI.
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = ["run_tui"]


def run_tui(args: Any = None) -> int:
    """Launch the interactive curses-based Terminal Workstation."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stderr.write(
            "[ERROR] TUI requires an interactive terminal (TTY).\n"
            "For non-interactive scripting, use canonical CLI subcommands (e.g. 'aditrader doctor', 'aditrader validate').\n"
            "To launch the browser interface, run 'aditrader dashboard'.\n"
        )
        return 1

    try:
        from aditrader.cli.tui.engine import TUIEngine

        engine = TUIEngine()
        return engine.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        sys.stderr.write(f"[ERROR] Terminal Workstation exited abnormally: {exc}\n")
        return 1
