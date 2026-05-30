"""Built-in trading strategies.

Importing this package registers every bundled strategy with the global
:class:`~quantbot.strategies.registry.StrategyRegistry` via the
``@register_strategy`` decorator on each class.
"""

from __future__ import annotations
