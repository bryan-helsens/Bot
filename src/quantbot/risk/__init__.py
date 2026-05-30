"""Risk-management layer — the non-bypassable gate before any order is placed.

Every order proposal flows through :class:`~quantbot.risk.engine.RiskEngine`,
which sizes the position, validates it against exposure/loss/drawdown limits,
applies correlation and circuit-breaker controls, and either approves, adjusts or
rejects it. Strategies and the AI module only *suggest*; the risk engine decides.
"""

from __future__ import annotations
