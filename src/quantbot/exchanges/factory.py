"""Factory for constructing exchange gateways from configuration.

Keeps the rest of the application free of concrete adapter imports: callers ask
the factory for "the configured gateway" (or explicitly for spot/futures) and
receive an :class:`~quantbot.exchanges.base.ExchangeGateway`. This is the single
place that maps ``Settings`` → concrete adapter, so adding a new exchange or
market type later touches only this module.
"""

from __future__ import annotations

from quantbot.core.config import Settings, get_settings
from quantbot.core.constants import MarketType
from quantbot.core.events import EventBus
from quantbot.core.exceptions import ConfigurationError
from quantbot.core.logging import get_logger
from quantbot.exchanges.base import ExchangeGateway
from quantbot.exchanges.binance_futures import BinanceFuturesGateway
from quantbot.exchanges.binance_spot import BinanceSpotGateway

_log = get_logger(__name__)

#: Registry mapping a market type to its concrete gateway class.
_GATEWAYS: dict[MarketType, type[ExchangeGateway]] = {
    MarketType.SPOT: BinanceSpotGateway,
    MarketType.FUTURES: BinanceFuturesGateway,
}


def create_gateway(
    settings: Settings | None = None,
    *,
    market: MarketType | None = None,
    event_bus: EventBus | None = None,
) -> ExchangeGateway:
    """Construct an exchange gateway from configuration.

    Args:
        settings: Application settings (defaults to the cached singleton).
        market: Override the configured market type (spot/futures); defaults to
            ``settings.binance.market``.
        event_bus: Optional event bus passed to the gateway for connection
            lifecycle events.

    Returns:
        A constructed (but not yet connected) :class:`ExchangeGateway`.

    Raises:
        ConfigurationError: If the requested market type has no adapter.
    """
    settings = settings or get_settings()
    market = market or settings.binance.market
    gateway_cls = _GATEWAYS.get(market)
    if gateway_cls is None:  # pragma: no cover - guarded by enum
        raise ConfigurationError(
            f"No gateway registered for market {market!r}",
            context={"market": getattr(market, "value", market)},
        )
    # Both Binance adapters share the same constructor signature.
    gateway = gateway_cls(settings, event_bus=event_bus)  # type: ignore[call-arg]
    _log.info(
        "gateway_created",
        market=market.value,
        adapter=gateway_cls.__name__,
        testnet=settings.binance.testnet,
    )
    return gateway


def register_gateway(market: MarketType, gateway_cls: type[ExchangeGateway]) -> None:
    """Register a custom gateway adapter for *market* (extensibility hook)."""
    _GATEWAYS[market] = gateway_cls
    _log.info("gateway_registered", market=market.value, adapter=gateway_cls.__name__)


async def create_connected_gateway(
    settings: Settings | None = None,
    *,
    market: MarketType | None = None,
    event_bus: EventBus | None = None,
) -> ExchangeGateway:
    """Construct *and* connect a gateway, ready for immediate use."""
    gateway = create_gateway(settings, market=market, event_bus=event_bus)
    await gateway.connect()
    return gateway


__all__ = ["create_connected_gateway", "create_gateway", "register_gateway"]
