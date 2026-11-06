"""Snapshot metadata store.

The payload itself lives in the configured object store; this module tracks
metadata (ids, base image, kernel version, memory, caller tenant) and
exposes list/get/put APIs. The HTTP client is injected so tests can supply
``httpx.MockTransport``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SnapshotStoreError(RuntimeError):
    """Raised on store transport or validation failures."""


@dataclass(frozen=True, slots=True)
class SnapshotMeta:
    snapshot_id: str
    base_image: str
    kernel_version: str
    memory_mb: int
    tenant_id: str
    size_bytes: int


class SnapshotStore:
    """Thin wrapper over the object-store metadata API."""

    def __init__(
        self, base_url: str, bucket: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._bucket = bucket
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def put(self, meta: SnapshotMeta) -> None:
        url = f"{self._base}/{self._bucket}/{meta.snapshot_id}/meta"
        body = {
            "snapshot_id": meta.snapshot_id,
            "base_image": meta.base_image,
            "kernel_version": meta.kernel_version,
            "memory_mb": meta.memory_mb,
            "tenant_id": meta.tenant_id,
            "size_bytes": meta.size_bytes,
        }
        c = await self._get_client()
        try:
            r = await c.put(url, json=body)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise SnapshotStoreError(f"put failed for {meta.snapshot_id}") from exc

    async def get(self, snapshot_id: str) -> SnapshotMeta:
        url = f"{self._base}/{self._bucket}/{snapshot_id}/meta"
        c = await self._get_client()
        try:
            r = await c.get(url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise SnapshotStoreError(f"get failed for {snapshot_id}") from exc
        return _parse_meta(r.json())

    async def list_for_tenant(self, tenant_id: str) -> list[SnapshotMeta]:
        url = f"{self._base}/{self._bucket}/_list"
        c = await self._get_client()
        try:
            r = await c.get(url, params={"tenant_id": tenant_id})
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise SnapshotStoreError(f"list failed for tenant {tenant_id}") from exc
        items = r.json().get("items", [])
        if not isinstance(items, list):
            raise SnapshotStoreError("list returned non-list `items`")
        return [_parse_meta(x) for x in items]


def _parse_meta(raw: Any) -> SnapshotMeta:
    if not isinstance(raw, dict):
        raise SnapshotStoreError("snapshot meta must be a mapping")
    try:
        return SnapshotMeta(
            snapshot_id=str(raw["snapshot_id"]),
            base_image=str(raw["base_image"]),
            kernel_version=str(raw["kernel_version"]),
            memory_mb=int(raw["memory_mb"]),
            tenant_id=str(raw["tenant_id"]),
            size_bytes=int(raw["size_bytes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotStoreError(f"invalid snapshot meta: {raw!r}") from exc
