from __future__ import annotations

from pathlib import Path

import pytest

from sandbox_ctl.network.allowlist import (
    Allowlist,
    AllowlistEntry,
    AllowlistError,
    is_allowed,
    load_allowlist,
)


def _mk(path: Path, body: str) -> str:
    f = path / "egress.yaml"
    f.write_text(body)
    return str(f)


def test_default_deny_when_no_entries() -> None:
    allowlist = Allowlist(default_policy="deny")
    assert not is_allowed(allowlist, host="pypi.org", port=443, tenant_id="t", flavor_id="f")


def test_matching_entry_allows(tmp_path: Path) -> None:
    path = _mk(
        tmp_path,
        "default_policy: deny\n" "entries:\n" "  - host: '*.pypi.org'\n" "    ports: [443]\n",
    )
    allowlist = load_allowlist(path, "deny")
    assert is_allowed(allowlist, host="files.pypi.org", port=443, tenant_id="t", flavor_id="f")
    assert not is_allowed(allowlist, host="evil.net", port=443, tenant_id="t", flavor_id="f")
    assert not is_allowed(allowlist, host="files.pypi.org", port=80, tenant_id="t", flavor_id="f")


def test_tenant_scoped_entry(tmp_path: Path) -> None:
    path = _mk(
        tmp_path,
        "default_policy: deny\n"
        "entries:\n"
        "  - host: 'internal.corp'\n"
        "    tenants: ['alpha']\n",
    )
    allowlist = load_allowlist(path, "deny")
    assert is_allowed(allowlist, host="internal.corp", port=443, tenant_id="alpha", flavor_id="f")
    assert not is_allowed(
        allowlist, host="internal.corp", port=443, tenant_id="beta", flavor_id="f"
    )


def test_missing_file_falls_back_to_default() -> None:
    allowlist = load_allowlist("/nope/absent.yaml", "allow")
    assert is_allowed(allowlist, host="x", port=1, tenant_id="t", flavor_id="f")


def test_bad_yaml_rejected(tmp_path: Path) -> None:
    path = _mk(tmp_path, "entries: not-a-list\n")
    with pytest.raises(AllowlistError):
        load_allowlist(path, "deny")


def test_entry_missing_host_rejected(tmp_path: Path) -> None:
    path = _mk(tmp_path, "entries:\n  - ports: [443]\n")
    with pytest.raises(AllowlistError):
        load_allowlist(path, "deny")


def test_entry_constructor() -> None:
    e = AllowlistEntry(host="x", ports=(80, 443))
    assert e.ports == (80, 443)
