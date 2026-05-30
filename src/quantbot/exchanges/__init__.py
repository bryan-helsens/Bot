"""Exchange-adapter layer.

The domain never talks to Binance directly; it depends on the
:class:`~quantbot.exchanges.base.ExchangeGateway` abstraction. Concrete adapters
(:mod:`quantbot.exchanges.binance_spot`, :mod:`quantbot.exchanges.binance_futures`)
implement that port, while :mod:`quantbot.exchanges.factory` selects one from
configuration.
"""

from __future__ import annotations
