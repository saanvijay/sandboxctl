from __future__ import annotations

from pathlib import Path

import pytest

from sandbox_ctl.isolation.creds import CredentialMinter


def test_mint_and_verify_roundtrip(signing_key: Path) -> None:
    minter = CredentialMinter(str(signing_key), ttl_s=60)
    cred = minter.mint("s1", "tenantA")
    verified = minter.verify(cred.token)
    assert verified.cred_id == cred.cred_id
    assert verified.session_id == "s1"
    assert verified.tenant_id == "tenantA"


def test_revoke_blocks_verify(signing_key: Path) -> None:
    minter = CredentialMinter(str(signing_key), ttl_s=60)
    cred = minter.mint("s1", "tenantA")
    assert minter.revoke(cred.cred_id) is True
    with pytest.raises(ValueError, match="revoked"):
        minter.verify(cred.token)


def test_expired_rejected(signing_key: Path) -> None:
    minter = CredentialMinter(str(signing_key), ttl_s=1)
    cred = minter.mint("s1", "t", now=1_000_000)
    with pytest.raises(ValueError, match="expired"):
        minter.verify(cred.token, now=1_000_200)


def test_bad_signature_rejected(signing_key: Path) -> None:
    minter = CredentialMinter(str(signing_key), ttl_s=60)
    cred = minter.mint("s1", "t")
    tampered = cred.token[:-2] + "AA"
    with pytest.raises(ValueError):
        minter.verify(tampered)


def test_short_key_rejected(tmp_path: Path) -> None:
    key = tmp_path / "k"
    key.write_bytes(b"abc")
    with pytest.raises(ValueError):
        CredentialMinter(str(key), ttl_s=60)
