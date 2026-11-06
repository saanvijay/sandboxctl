"""Kubernetes implementation of :class:`Driver`.

Uses the official ``kubernetes`` Python client. The client is sync, so we
wrap calls in ``asyncio.to_thread`` to stay off the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

from sandbox_ctl.config import Settings
from sandbox_ctl.runtime.driver import Driver, DriverError, SandboxHandle

logger = logging.getLogger(__name__)

_READY_POLL_INTERVAL_S = 0.1


class K8sDriver(Driver):
    """Create / destroy / relabel sandbox Pods via the Kubernetes API."""

    def __init__(self, settings: Settings, *, core_v1: Any | None = None) -> None:
        self._settings = settings
        if core_v1 is None:
            self._load_kubeconfig()
            self._core = k8s_client.CoreV1Api()
        else:
            self._core = core_v1

    def _load_kubeconfig(self) -> None:
        if self._settings.kube_in_cluster:
            k8s_config.load_incluster_config()
        else:
            path = self._settings.kube_kubeconfig_path or None
            k8s_config.load_kube_config(config_file=path)

    async def create(self, pod_spec: dict[str, Any], *, flavor_id: str) -> SandboxHandle:
        namespace = self._settings.kube_namespace
        name = pod_spec["metadata"]["name"]
        sandbox_id = pod_spec["metadata"]["labels"]["sandbox_id"]
        try:
            await asyncio.to_thread(self._core.create_namespaced_pod, namespace, pod_spec)
        except ApiException as exc:
            raise DriverError(f"create failed: {exc.reason}") from exc
        await self._wait_ready(name, namespace, timeout_s=self._settings.session_max_wall_s)
        pod = await asyncio.to_thread(self._core.read_namespaced_pod, name, namespace)
        pod_ip = getattr(pod.status, "pod_ip", None) or ""
        return SandboxHandle(
            sandbox_id=sandbox_id,
            pod_name=name,
            namespace=namespace,
            flavor_id=flavor_id,
            agent_endpoint=f"grpc://{pod_ip}:50051"
            if pod_ip
            else self._settings.agent_grpc_endpoint,
        )

    async def destroy(self, handle: SandboxHandle, *, grace_s: int = 0) -> None:
        try:
            await asyncio.to_thread(
                self._core.delete_namespaced_pod,
                handle.pod_name,
                handle.namespace,
                grace_period_seconds=grace_s,
            )
        except ApiException as exc:
            if exc.status == 404:
                logger.info("destroy: pod already gone", extra={"pod": handle.pod_name})
                return
            raise DriverError(f"destroy failed: {exc.reason}") from exc

    async def relabel(self, handle: SandboxHandle, labels: dict[str, str]) -> SandboxHandle:
        patch = {"metadata": {"labels": labels}}
        try:
            await asyncio.to_thread(
                self._core.patch_namespaced_pod, handle.pod_name, handle.namespace, patch
            )
        except ApiException as exc:
            raise DriverError(f"relabel failed: {exc.reason}") from exc
        return handle

    async def _wait_ready(self, name: str, namespace: str, *, timeout_s: int) -> None:
        """Poll Pod status until it reports Ready or times out."""
        waited = 0.0
        while waited < timeout_s:
            try:
                pod = await asyncio.to_thread(self._core.read_namespaced_pod, name, namespace)
            except ApiException as exc:
                raise DriverError(f"status read failed: {exc.reason}") from exc
            phase = getattr(pod.status, "phase", "Pending")
            if phase == "Running" and _is_ready(pod):
                return
            if phase in {"Failed", "Succeeded"}:
                raise DriverError(f"pod reached terminal phase {phase} before ready")
            await asyncio.sleep(_READY_POLL_INTERVAL_S)
            waited += _READY_POLL_INTERVAL_S
        raise DriverError(f"pod {name} not Ready after {timeout_s}s")


def _is_ready(pod: Any) -> bool:
    conds = getattr(pod.status, "conditions", None) or []
    return any(c.type == "Ready" and c.status == "True" for c in conds)
