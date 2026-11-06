from __future__ import annotations

import httpx
import pytest

from sandbox_ctl.network.allowlist import AllowlistEntry
from sandbox_ctl.network.egress_proxy import EgressProxyClient, SessionEgressRules


@pytest.fixture()
def transport_captures() -> tuple[list[httpx.Request], httpx.MockTransport]:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={})

    return captured, httpx.MockTransport(handler)


async def test_apply_sends_rules(
    transport_captures: tuple[list[httpx.Request], httpx.MockTransport],
) -> None:
    captured, transport = transport_captures
    async with httpx.AsyncClient(transport=transport, base_url="http://unused") as client:
        proxy = EgressProxyClient("http://proxy.local")
        rules = SessionEgressRules(
            session_id="s1",
            tenant_id="t",
            flavor_id="f",
            entries=(AllowlistEntry(host="x.y", ports=(443,)),),
        )
        await proxy.apply(rules, client=client)
    assert len(captured) == 1
    body = captured[0].read().decode()
    assert "x.y" in body


async def test_clear(
    transport_captures: tuple[list[httpx.Request], httpx.MockTransport],
) -> None:
    captured, transport = transport_captures
    async with httpx.AsyncClient(transport=transport, base_url="http://unused") as client:
        proxy = EgressProxyClient("http://proxy.local")
        await proxy.clear("s1", client=client)
    assert captured[0].url.path.endswith("/clear")
