"""Egress allowlist policy evaluation.

The source of truth is a YAML file on disk. Each entry is a ``host`` glob and
optional ``ports`` list. Policies are per-flavor-and-tenant; evaluation is
host-first, ports second. The default policy (allow / deny) covers requests
that match no entry.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class AllowlistError(RuntimeError):
    """Raised on malformed allowlist input."""


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    host: str  # glob, e.g. "*.pypi.org"
    ports: tuple[int, ...] = ()  # empty tuple means "any"
    tenants: tuple[str, ...] = ()  # empty tuple means "all tenants"
    flavors: tuple[str, ...] = ()  # empty tuple means "all flavors"


@dataclass(frozen=True, slots=True)
class Allowlist:
    default_policy: str  # "deny" or "allow"
    entries: tuple[AllowlistEntry, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.default_policy not in {"deny", "allow"}:
            raise AllowlistError(f"default_policy must be deny|allow, got {self.default_policy!r}")


def load_allowlist(path: str, default_policy: str) -> Allowlist:
    """Load the allowlist from ``path``.

    Missing file is a non-fatal — we fall back to the default policy. That
    matches operator intent: ``EGRESS_DEFAULT_POLICY=deny`` with no file is
    the safest possible config.
    """
    file = Path(path)
    if not file.is_file():
        logger.warning("allowlist file not found, using default policy only", extra={"path": path})
        return Allowlist(default_policy=default_policy)
    raw = yaml.safe_load(file.read_text()) or {}
    if not isinstance(raw, dict):
        raise AllowlistError(f"allowlist root must be a mapping, got {type(raw).__name__}")
    entries_raw = raw.get("entries", [])
    if not isinstance(entries_raw, list):
        raise AllowlistError("`entries` must be a list")
    entries = tuple(_parse_entry(e) for e in entries_raw)
    return Allowlist(
        default_policy=raw.get("default_policy", default_policy),
        entries=entries,
    )


def _parse_entry(raw: Any) -> AllowlistEntry:
    if not isinstance(raw, dict):
        raise AllowlistError(f"allowlist entry must be a mapping, got {type(raw).__name__}")
    host = raw.get("host")
    if not isinstance(host, str) or not host:
        raise AllowlistError(f"entry missing non-empty `host`: {raw!r}")
    ports = tuple(int(p) for p in raw.get("ports", []))
    tenants = tuple(str(t) for t in raw.get("tenants", []))
    flavors = tuple(str(f) for f in raw.get("flavors", []))
    return AllowlistEntry(host=host, ports=ports, tenants=tenants, flavors=flavors)


def is_allowed(
    allowlist: Allowlist,
    *,
    host: str,
    port: int,
    tenant_id: str,
    flavor_id: str,
) -> bool:
    """Return True iff ``(host, port)`` is permitted for ``(tenant, flavor)``."""
    for entry in allowlist.entries:
        if entry.tenants and tenant_id not in entry.tenants:
            continue
        if entry.flavors and flavor_id not in entry.flavors:
            continue
        if not fnmatch.fnmatchcase(host, entry.host):
            continue
        if entry.ports and port not in entry.ports:
            continue
        return True
    return allowlist.default_policy == "allow"
