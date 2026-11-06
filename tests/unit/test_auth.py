from __future__ import annotations

import pytest
from fastapi import HTTPException

from sandbox_ctl.api.auth import DevHeaderAuth


async def test_dev_auth_requires_tenant_header() -> None:
    auth = DevHeaderAuth()
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify(None, None)
    assert excinfo.value.status_code == 401


async def test_dev_auth_round_trip() -> None:
    auth = DevHeaderAuth()
    caller = await auth.verify(None, "tenantX")
    assert caller.tenant_id == "tenantX"
    assert "tenantX" in caller.principal
