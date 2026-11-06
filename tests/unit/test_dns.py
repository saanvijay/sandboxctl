from __future__ import annotations

import pytest

from sandbox_ctl.network.dns import DnsPinning, to_pod_dns


def test_pinning_shape() -> None:
    pinning = DnsPinning(resolver_ips=("10.0.0.1",), search=("svc.cluster.local",))
    policy, config = to_pod_dns(pinning)
    assert policy == "None"
    assert config["nameservers"] == ["10.0.0.1"]
    assert config["searches"] == ["svc.cluster.local"]
    assert {"name": "ndots", "value": "2"} in config["options"]


def test_requires_at_least_one_resolver() -> None:
    with pytest.raises(ValueError):
        DnsPinning(resolver_ips=())
