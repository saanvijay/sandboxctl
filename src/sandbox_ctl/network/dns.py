"""Per-session DNS pinning.

The sandbox Pod resolves names only through the in-cluster resolver that
enforces the same allowlist as the egress proxy. We emit the ``dnsPolicy``
and ``dnsConfig`` fragment that drives this.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DnsPinning:
    resolver_ips: tuple[str, ...]
    search: tuple[str, ...] = ()
    options: tuple[tuple[str, str | None], ...] = (
        ("ndots", "2"),
        ("timeout", "2"),
        ("attempts", "2"),
    )

    def __post_init__(self) -> None:
        if not self.resolver_ips:
            raise ValueError("at least one resolver IP is required")


def to_pod_dns(pinning: DnsPinning) -> tuple[str, dict[str, object]]:
    """Return ``(dnsPolicy, dnsConfig)`` for the Pod spec."""
    config: dict[str, object] = {
        "nameservers": list(pinning.resolver_ips),
    }
    if pinning.search:
        config["searches"] = list(pinning.search)
    config["options"] = [
        {"name": name} if value is None else {"name": name, "value": value}
        for name, value in pinning.options
    ]
    return "None", config
