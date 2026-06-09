"""Persist and restore engine state across restarts.

Writes the :class:`PortfolioManager` state (cash, realised PnL, open positions,
equity curve) to a JSON file atomically, so a crash or planned restart resumes
seamlessly instead of starting from scratch. Used by the live/paper runtime; the
backtester does not persist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from quantbot.core.logging import get_logger
from quantbot.portfolio.manager import PortfolioManager

_log = get_logger(__name__)


def save_state(portfolio: PortfolioManager, path: str) -> bool:
    """Atomically write *portfolio* state to *path*. Returns success."""
    if not path:
        return False
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(portfolio.export_state()), encoding="utf-8")
        os.replace(tmp, target)  # atomic on POSIX
        return True
    except Exception as exc:  # noqa: BLE001 - persistence must never crash the engine
        _log.warning("state_save_failed", path=path, error=str(exc))
        return False


def load_state(portfolio: PortfolioManager, path: str) -> bool:
    """Restore *portfolio* state from *path* if it exists. Returns whether loaded."""
    if not path:
        return False
    target = Path(path)
    if not target.exists():
        return False
    try:
        state: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        portfolio.import_state(state)
        return True
    except Exception as exc:  # noqa: BLE001 - corrupt state must not block startup
        _log.warning("state_load_failed", path=path, error=str(exc))
        return False


__all__ = ["load_state", "save_state"]
