"""Pluggable trading-strategy framework.

A strategy is a subclass of :class:`~quantbot.strategies.base.BaseStrategy`
registered via :func:`~quantbot.strategies.registry.register_strategy`. The
engine feeds each strategy closed candles through a :class:`StrategyContext` and
collects any :class:`~quantbot.core.models.Signal` it emits; signals are then
combined by the :class:`~quantbot.strategies.aggregator.SignalAggregator` and
validated by the risk engine before any order is placed.

Built-in strategies live in :mod:`quantbot.strategies.builtin`.
"""

from __future__ import annotations
