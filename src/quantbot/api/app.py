"""FastAPI application factory.

Assembles the monitoring backend: CORS, routers, the WebSocket push endpoint and
the shared :class:`AppState`. The engine populates ``AppState`` (portfolio, risk
engine, performance, db, redis) and connects the :class:`EventBroadcaster` to its
event bus so the dashboard receives live updates.
"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from quantbot.api.dependencies import AppState, set_state
from quantbot.api.routers import portfolio, positions, risk, strategies, system, trades
from quantbot.api.websocket import ConnectionManager, EventBroadcaster
from quantbot import __version__
from quantbot.core.config import Settings, get_settings
from quantbot.core.events import EventBus
from quantbot.core.logging import get_logger

_log = get_logger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    state: AppState | None = None,
    event_bus: EventBus | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or get_settings()
    app = FastAPI(
        title="QuantBot API",
        version=__version__,
        description="Monitoring & control backend for the QuantBot trading engine.",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared application state (engine fills this in; default is a bare state).
    app_state = state or AppState(settings=settings)
    set_state(app_state)

    # REST routers.
    app.include_router(system.router)
    app.include_router(portfolio.router)
    app.include_router(positions.router)
    app.include_router(trades.router)
    app.include_router(strategies.router)
    app.include_router(risk.router)

    # WebSocket push.
    manager = ConnectionManager()
    broadcaster = EventBroadcaster(manager)
    if event_bus is not None:
        broadcaster.subscribe(event_bus)
    app.state.ws_manager = manager
    app.state.broadcaster = broadcaster

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                # Keep the connection alive; ignore inbound messages (push-only).
                await websocket.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception:  # noqa: BLE001 - ensure cleanup on any error
            await manager.disconnect(websocket)

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {"name": "QuantBot API", "version": __version__, "docs": "/docs"}

    _log.info("api_app_created", routes=len(app.routes))
    return app


__all__ = ["create_app"]
