"""Egress-proxy configuration helper.

The egress proxy is a DaemonSet (one Pod per node). The control plane pushes
a per-session rule set to a side-channel endpoint when a session is leased
and clears it on teardown.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from sandbox_ctl.network.allowlist import AllowlistEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionEgressRules:
    session_id: str
    tenant_id: str
    flavor_id: str
    entries: tuple[AllowlistEntry, ...]


class EgressProxyClient:
    """Pushes per-session rules to the egress-proxy control endpoint."""

    def __init__(self, base_url: str, *, timeout_s: int = 5) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    async def apply(
        self, rules: SessionEgressRules, client: httpx.AsyncClient | None = None
    ) -> None:
        body = {
            "session_id": rules.session_id,
            "tenant_id": rules.tenant_id,
            "flavor_id": rules.flavor_id,
            "entries": [
                {
                    "host": e.host,
                    "ports": list(e.ports),
                }
                for e in rules.entries
            ],
        }
        await self._post(f"/sessions/{rules.session_id}/rules", body, client)

    async def clear(self, session_id: str, client: httpx.AsyncClient | None = None) -> None:
        await self._post(f"/sessions/{session_id}/clear", {}, client)

    async def _post(
        self, path: str, body: Mapping[str, Any], client: httpx.AsyncClient | None
    ) -> None:
        url = self._base + path
        owned = client is None
        c = client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await c.post(url, json=dict(body))
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("egress-proxy call failed", extra={"url": url})
            raise
        finally:
            if owned:
                await c.aclose()
