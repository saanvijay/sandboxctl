"""Compose the full AppContext for the production entrypoint.

:func:`sandbox_ctl.api.app.create_app` serves only health routes when given
no context. This module builds the real context — the SessionManager and
every collaborator it needs — and exposes :func:`build_app`, the ASGI
factory uvicorn targets with ``--factory``.

Backend selection reuses :mod:`sandbox_ctl.runtime.boot`. Both docker
(laptop) and kubernetes (dev cluster, kubectl-exec agent) backends are
wired; production Kata + gRPC agent is still STATUS.md future.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI

from sandbox_ctl.api.app import AppContext, create_app, default_auth
from sandbox_ctl.config import Settings, get_settings
from sandbox_ctl.isolation.creds import CredentialMinter, SessionCredential
from sandbox_ctl.pool.warm_pool import WarmPool
from sandbox_ctl.runtime.boot import build_agent, build_driver
from sandbox_ctl.session.manager import SessionManager
from sandbox_ctl.session.quotas import QuotaConfig, QuotaEnforcer
from sandbox_ctl.session.registry import SessionRegistry
from sandbox_ctl.telemetry.events import EventEmitter

logger = logging.getLogger(__name__)


class BootError(RuntimeError):
    """Raised when the full AppContext cannot be composed."""


# Flavor id → sandbox image. Same mapping for both backends today; a real
# per-env registry lookup lands with the Kata path.
_FLAVOR_IMAGES: dict[str, str] = {
    "python-3.11-ctr": "python:3.11-slim",
    "python": "python:3.11-slim",
    "node-20-ctr": "node:20-slim",
    "shell-ctr": "python:3.11-slim",
}

# Keepalive command for sandbox containers in both backends. The container
# must stay Running while the control plane streams exec into it.
_KEEPALIVE_CMD: list[str] = [
    "sh",
    "-c",
    "trap 'exit 0' TERM; while :; do sleep 3600 & wait $!; done",
]


ColdSpec = Callable[[str, SessionCredential], Awaitable[dict[str, Any]]]


def _flavor_image(flavor_id: str) -> str:
    image = _FLAVOR_IMAGES.get(flavor_id)
    if image is None:
        raise BootError(
            f"no image mapping for flavor {flavor_id!r}; " f"known: {sorted(_FLAVOR_IMAGES)}"
        )
    return image


def _docker_cold_spec_factory(settings: Settings) -> ColdSpec:
    async def factory(flavor_id: str, cred: SessionCredential) -> dict[str, Any]:
        image = _flavor_image(flavor_id)
        return {
            "metadata": {
                "name": f"sandbox-{cred.session_id}",
                "labels": {
                    "app": "sandbox",
                    "sandbox_id": cred.session_id,
                    "flavor_id": flavor_id,
                    "tenant_id": cred.tenant_id,
                },
            },
            "spec": {
                "containers": [
                    {
                        "name": "sandbox",
                        "image": image,
                        "securityContext": {"readOnlyRootFilesystem": True},
                        "resources": {
                            "limits": {
                                "cpu": "500m",
                                "memory": f"{settings.session_max_memory_mb}Mi",
                            }
                        },
                        "volumeMounts": [{"name": "scratch", "mountPath": "/scratch"}],
                    }
                ],
                "volumes": [
                    {
                        "name": "scratch",
                        "emptyDir": {
                            "medium": "Memory",
                            "sizeLimit": f"{settings.session_scratch_mb}Mi",
                        },
                    }
                ],
            },
        }

    return factory


def _k8s_pod_name(session_id: str) -> str:
    """Render ``session_id`` as an RFC 1123-compliant Pod name.

    Session ids carry an ``s_<hex>`` prefix for readability; K8s Pod names
    can't contain ``_``, so we swap to ``-``. The result is still unique
    (the hex suffix is the id's entropy).
    """
    return f"sandbox-{session_id.replace('_', '-')}"


def _k8s_cold_spec_factory(settings: Settings) -> ColdSpec:
    """Minimal sandbox-Pod spec for the dev-cluster + kube-exec agent path.

    The production microVM path uses :func:`build_pod_spec`; that path
    assumes RuntimeClasses, PriorityClasses, and an in-sandbox agent
    binary that minikube clusters don't have. This spec drops the
    optional pieces and sets a keepalive command so the Pod stays
    Running while :class:`KubeExecAgent` execs into it.
    """

    async def factory(flavor_id: str, cred: SessionCredential) -> dict[str, Any]:
        image = _flavor_image(flavor_id)
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": _k8s_pod_name(cred.session_id),
                "namespace": settings.kube_namespace,
                "labels": {
                    "app": "sandbox",
                    "sandbox_id": cred.session_id,
                    "flavor_id": flavor_id,
                    "tenant_id": cred.tenant_id,
                },
            },
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "containers": [
                    {
                        "name": "sandbox",
                        "image": image,
                        "imagePullPolicy": "IfNotPresent",
                        "command": _KEEPALIVE_CMD,
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "resources": {
                            "requests": {
                                "cpu": "100m",
                                "memory": f"{settings.session_max_memory_mb}Mi",
                            },
                            "limits": {
                                "cpu": "500m",
                                "memory": f"{settings.session_max_memory_mb}Mi",
                            },
                        },
                        "env": [
                            {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
                        ],
                        "volumeMounts": [{"name": "scratch", "mountPath": "/scratch"}],
                    }
                ],
                "volumes": [
                    {
                        "name": "scratch",
                        "emptyDir": {
                            "medium": "Memory",
                            "sizeLimit": f"{settings.session_scratch_mb}Mi",
                        },
                    }
                ],
            },
        }

    return factory


def build_context(settings: Settings | None = None) -> AppContext:
    """Build the production AppContext from settings.

    Raises :class:`BootError` for backends whose full dependency graph is
    not available in this build. Callers that can gracefully degrade
    (:func:`build_app`) catch that and mount health routes only.
    """
    s = settings or get_settings()
    if s.runtime_backend == "kubernetes":
        cold_spec = _k8s_cold_spec_factory(s)
    elif s.runtime_backend == "docker":
        cold_spec = _docker_cold_spec_factory(s)
    else:
        raise BootError(f"unsupported RUNTIME_BACKEND: {s.runtime_backend!r}")

    driver = build_driver(s)
    agent = build_agent(s)
    pool = WarmPool(max_idle_s=s.warm_pool_max_idle_s)
    registry = SessionRegistry()
    events = EventEmitter()
    creds = CredentialMinter(s.creds_signing_key_path, ttl_s=s.creds_ttl_s)
    quotas = QuotaEnforcer(
        QuotaConfig(max_concurrent=s.tenant_max_concurrent, rps=s.tenant_quota_rps)
    )
    manager = SessionManager(
        settings=s,
        driver=driver,
        pool=pool,
        agent=agent,
        creds=creds,
        quotas=quotas,
        registry=registry,
        events=events,
        cold_spec_factory=cold_spec,
    )
    logger.info(
        "boot: AppContext assembled",
        extra={"backend": s.runtime_backend, "env": s.service_env},
    )
    return AppContext(settings=s, manager=manager, registry=registry, auth=default_auth(s))


def build_app() -> FastAPI:
    """ASGI factory for uvicorn ``--factory``.

    Builds the full AppContext when possible. If the configured backend
    cannot be wired in this build, logs a warning and returns a
    health-only app so the Pod stays up and the operator can see the
    cause in logs instead of a CrashLoopBackOff.
    """
    try:
        return create_app(build_context())
    except BootError as exc:
        logger.warning("boot: %s — serving health routes only", exc)
        return create_app(None)
