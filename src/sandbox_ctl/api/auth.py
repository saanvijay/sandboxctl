"""Caller auth: verify identity, extract tenant.

The production implementation verifies a bearer JWT against a JWKS; here we
expose the small typed interface and a dev-mode header shim that trusts an
``X-Tenant-Id`` header. The production verifier plugs in at app startup.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fastapi import Header, HTTPException, status


@dataclass(frozen=True, slots=True)
class Caller:
    tenant_id: str
    principal: str  # user or service identifier for audit; opaque here.


@runtime_checkable
class CallerAuth(Protocol):
    async def verify(self, authorization: str | None, tenant_header: str | None) -> Caller: ...


class DevHeaderAuth(CallerAuth):
    """Trusts ``X-Tenant-Id``. Enabled only when ``SERVICE_ENV != 'prod'``."""

    async def verify(self, authorization: str | None, tenant_header: str | None) -> Caller:
        if not tenant_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Tenant-Id header required in dev auth",
            )
        return Caller(tenant_id=tenant_header, principal=f"dev:{tenant_header}")


def caller_dependency(auth: CallerAuth) -> Callable[..., Awaitable[Caller]]:
    """Return a FastAPI dependency bound to a specific CallerAuth instance."""

    async def _dep(
        authorization: str | None = Header(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> Caller:
        return await auth.verify(authorization, x_tenant_id)

    return _dep
