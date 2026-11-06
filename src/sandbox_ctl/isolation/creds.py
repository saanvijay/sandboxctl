"""Per-session short-lived credentials.

A credential is a signed, narrowly-scoped bearer token minted at lease time,
bound to the ``session_id`` and ``tenant_id``, with a TTL of ``CREDS_TTL_S``.
It is passed to the in-sandbox agent at startup, never written to a Pod spec,
log, or snapshot. On session end the issuer is told to revoke the id so TTL
is the fallback, not the only mechanism.

Signing uses HMAC-SHA256 with a key file loaded once at startup. In prod the
key file is projected from KMS.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionCredential:
    cred_id: str
    session_id: str
    tenant_id: str
    expires_at: int  # unix seconds
    token: str  # opaque bearer value — never log.


class _Payload(TypedDict):
    cid: str
    sid: str
    tid: str
    iat: int
    exp: int


class CredentialMinter:
    """Mint and revoke per-session credentials.

    Thread-safe. Tracks live cred ids in-memory for revocation; the token
    itself is HMAC-signed so verifiers can validate it without consulting
    state, with revocation handled by the active set.
    """

    def __init__(self, signing_key_path: str, ttl_s: int) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        self._ttl_s = ttl_s
        self._key = Path(signing_key_path).read_bytes()
        if len(self._key) < 32:
            raise ValueError("signing key must be at least 32 bytes")
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._revoked: set[str] = set()

    def mint(self, session_id: str, tenant_id: str, *, now: int | None = None) -> SessionCredential:
        issued = int(time.time()) if now is None else now
        expires = issued + self._ttl_s
        cred_id = secrets.token_urlsafe(16)
        payload: _Payload = {
            "cid": cred_id,
            "sid": session_id,
            "tid": tenant_id,
            "iat": issued,
            "exp": expires,
        }
        token = _sign(self._key, payload)
        with self._lock:
            self._active.add(cred_id)
        logger.info(
            "credential minted",
            extra={"session_id": session_id, "tenant_id": tenant_id, "cred_id": cred_id},
        )
        return SessionCredential(
            cred_id=cred_id,
            session_id=session_id,
            tenant_id=tenant_id,
            expires_at=expires,
            token=token,
        )

    def revoke(self, cred_id: str) -> bool:
        with self._lock:
            if cred_id in self._active:
                self._active.remove(cred_id)
                self._revoked.add(cred_id)
                logger.info("credential revoked", extra={"cred_id": cred_id})
                return True
        return False

    def verify(self, token: str, *, now: int | None = None) -> SessionCredential:
        payload, signature = _parse(token)
        expected = _sign(self._key, payload)
        _, expected_sig = _parse(expected)
        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError("invalid signature")
        current = int(time.time()) if now is None else now
        if current >= payload["exp"]:
            raise ValueError("expired")
        with self._lock:
            if payload["cid"] in self._revoked:
                raise ValueError("revoked")
            if payload["cid"] not in self._active:
                raise ValueError("unknown credential")
        return SessionCredential(
            cred_id=payload["cid"],
            session_id=payload["sid"],
            tenant_id=payload["tid"],
            expires_at=payload["exp"],
            token=token,
        )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(key: bytes, payload: _Payload | dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(key, body.encode("ascii"), sha256).digest())
    return f"{body}.{sig}"


def _parse(token: str) -> tuple[_Payload, str]:
    if token.count(".") != 1:
        raise ValueError("malformed token")
    body, sig = token.split(".", 1)
    try:
        raw = json.loads(_b64decode(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("malformed payload") from exc
    if not isinstance(raw, dict):
        raise ValueError("malformed payload")
    try:
        payload: _Payload = {
            "cid": str(raw["cid"]),
            "sid": str(raw["sid"]),
            "tid": str(raw["tid"]),
            "iat": int(raw["iat"]),
            "exp": int(raw["exp"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed payload") from exc
    return payload, sig
