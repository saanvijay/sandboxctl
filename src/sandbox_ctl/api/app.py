"""ASGI app factory. Routes only, no business logic.

Separates **construction** of the service's dependency graph from the pure
HTTP surface. Callers (uvicorn, tests) instantiate the app via
:func:`create_app`; tests swap out individual components by passing a
pre-built :class:`AppContext`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import FastAPI

from sandbox_ctl.api.auth import CallerAuth, DevHeaderAuth, caller_dependency
from sandbox_ctl.api.routes_health import router as health_router
from sandbox_ctl.api.routes_sessions import build_router as build_sessions_router
from sandbox_ctl.config import Settings, get_settings
from sandbox_ctl.session.manager import SessionManager
from sandbox_ctl.session.registry import SessionRegistry
from sandbox_ctl.telemetry.logger import configure_logging

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    settings: Settings
    manager: SessionManager
    registry: SessionRegistry
    auth: CallerAuth
    default_flavor_id: str = "python-3.11-ctr"


def create_app(context: AppContext | None = None) -> FastAPI:
    """Build the FastAPI app.

    When ``context`` is ``None`` the app refuses to serve session traffic —
    only health endpoints are mounted. Full-service startup wires the context
    in via :mod:`sandbox_ctl.boot` (not shown here; the production entrypoint
    builds driver, pool, manager, etc. before calling this).
    """
    settings = context.settings if context is not None else get_settings()
    configure_logging(settings)
    app = FastAPI(title=settings.service_name, version="0.1.0")
    app.include_router(health_router)
    if context is not None:
        caller_dep = caller_dependency(context.auth)
        app.include_router(
            build_sessions_router(
                manager=context.manager,
                registry=context.registry,
                caller_dep=caller_dep,
                default_flavor_id=context.default_flavor_id,
            )
        )
    else:
        logger.warning("no AppContext provided — only health routes active")
    return app


def default_auth(settings: Settings) -> CallerAuth:
    if settings.is_prod():
        raise RuntimeError("DevHeaderAuth refuses to run in prod; wire a real verifier")
    return DevHeaderAuth()
