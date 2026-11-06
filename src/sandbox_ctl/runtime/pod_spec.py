"""Build the Kubernetes Pod spec for a sandbox.

Takes the typed inputs from :mod:`isolation` and the runtime settings and
produces a dict suitable for ``CoreV1Api.create_namespaced_pod``. No I/O
here; every value is pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sandbox_ctl.config import Settings
from sandbox_ctl.isolation.compute import ComputeLimits, to_pod_resources
from sandbox_ctl.isolation.filesystem import FilesystemLayout, to_pod_volumes_and_mounts
from sandbox_ctl.isolation.seccomp import SeccompProfile, to_pod_seccomp


@dataclass(frozen=True, slots=True)
class PodBuildInputs:
    sandbox_id: str
    tenant_id: str
    session_id: str  # "" for warm Pods
    flavor_id: str
    image: str  # fully-qualified image reference, including tag/digest.
    compute: ComputeLimits
    filesystem: FilesystemLayout
    seccomp: SeccompProfile | None
    runtime_class: str
    priority_class: str
    # Env the agent needs; credentials go in via a Secret-backed env entry so
    # the Pod spec itself never contains the token.
    cred_secret_name: str | None
    extra_labels: dict[str, str] | None = None


def build_pod_spec(inputs: PodBuildInputs, settings: Settings) -> dict[str, Any]:
    """Return a complete Pod manifest dict."""
    labels = {
        "app": "sandbox",
        "pool": "warm" if not inputs.session_id else "ondemand",
        "sandbox_id": inputs.sandbox_id,
        "tenant_id": inputs.tenant_id,
        "session_id": inputs.session_id,
        "flavor_id": inputs.flavor_id,
    }
    if inputs.extra_labels:
        labels.update(inputs.extra_labels)

    volumes, mounts = to_pod_volumes_and_mounts(inputs.filesystem)

    env: list[dict[str, Any]] = [
        {"name": "SESSION_ID", "value": inputs.session_id or ""},
        {"name": "TENANT_ID", "value": inputs.tenant_id},
        {"name": "FLAVOR_ID", "value": inputs.flavor_id},
        {"name": "AGENT_TIMEOUT_S", "value": str(settings.agent_timeout_s)},
    ]
    if inputs.cred_secret_name is not None:
        env.append(
            {
                "name": "SESSION_CREDENTIAL",
                "valueFrom": {
                    "secretKeyRef": {"name": inputs.cred_secret_name, "key": "token"},
                },
            }
        )

    spec: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": f"sandbox-{inputs.sandbox_id}",
            "namespace": settings.kube_namespace,
            "labels": labels,
        },
        "spec": {
            "runtimeClassName": inputs.runtime_class,
            "priorityClassName": inputs.priority_class,
            "automountServiceAccountToken": False,
            "activeDeadlineSeconds": inputs.compute.wall_s,
            "restartPolicy": "Never",
            "nodeSelector": _parse_node_selector(settings.sandbox_node_selector),
            "tolerations": [
                {"key": "role", "value": "sandbox", "effect": "NoSchedule"},
            ],
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "fsGroup": 10001,
                "seccompProfile": to_pod_seccomp(inputs.seccomp, settings.pod_seccomp_profile),
            },
            "containers": [
                {
                    "name": "agent",
                    "image": inputs.image,
                    "imagePullPolicy": "IfNotPresent",
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "resources": to_pod_resources(inputs.compute),
                    "env": env,
                    "volumeMounts": mounts,
                }
            ],
            "volumes": volumes,
        },
    }

    if settings.sandbox_image_pull_secret:
        spec["spec"]["imagePullSecrets"] = [{"name": settings.sandbox_image_pull_secret}]

    return spec


def _parse_node_selector(spec: str) -> dict[str, str]:
    """Parse ``"k1=v1,k2=v2"`` into a dict. Empty string yields ``{}``."""
    out: dict[str, str] = {}
    if not spec:
        return out
    for part in spec.split(","):
        if "=" not in part:
            raise ValueError(f"invalid node selector entry: {part!r}")
        key, _, value = part.partition("=")
        out[key.strip()] = value.strip()
    return out
