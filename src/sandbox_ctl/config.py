"""Load and validate runtime configuration from environment variables.

This is the only module that reads environment variables; everything else
imports the typed :class:`Settings` singleton. See DESIGN.md §7 — the set of
fields here is kept in lockstep with ``.env.example`` by a sync test under
``tests/unit/test_env_sync.py``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when a required configuration variable is missing or malformed."""


def _get_str(name: str, default: str | None = None) -> str:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ConfigError(f"required env var {name} is not set")
        return default
    return raw


def _get_int(name: str, default: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ConfigError(f"required env var {name} is not set")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"env var {name} must be an int, got {raw!r}") from exc


def _get_float(name: str, default: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ConfigError(f"required env var {name} is not set")
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"env var {name} must be a float, got {raw!r}") from exc


def _get_bool(name: str, default: bool | None = None) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ConfigError(f"required env var {name} is not set")
        return default
    low = raw.strip().lower()
    if low in {"1", "true", "yes", "on"}:
        return True
    if low in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"env var {name} must be a bool, got {raw!r}")


@dataclass(frozen=True, slots=True)
class Settings:
    # Service
    service_name: str
    service_env: str

    # HTTP
    http_host: str
    http_port: int
    http_request_timeout_s: int

    # Runtime driver
    runtime_backend: str
    runtime_driver: str
    runtime_api_url: str
    agent_grpc_endpoint: str
    agent_timeout_s: int
    docker_network: str

    # Warm pool
    warm_pool_size: int
    warm_pool_max_idle_s: int
    warm_pool_refill_concurrency: int

    # Snapshot store
    snapshot_store_url: str
    snapshot_store_bucket: str
    snapshot_store_key_id: str
    snapshot_store_secret: str

    # Session limits
    session_max_wall_s: int
    session_max_cpu_ms: int
    session_max_memory_mb: int
    session_max_pids: int
    session_scratch_mb: int

    # Tenant quotas
    tenant_max_concurrent: int
    tenant_quota_rps: int

    # Egress
    egress_default_policy: str
    egress_allowlist_path: str

    # Credentials
    creds_signing_key_path: str
    creds_ttl_s: int

    # Telemetry & logging
    otlp_endpoint: str
    otlp_sample_ratio: float
    metrics_port: int
    log_level: str
    log_format: str

    # Kubernetes
    kube_in_cluster: bool
    kube_namespace: str
    kube_kubeconfig_path: str
    runtime_class_mvm: str
    runtime_class_ctr: str
    sandbox_node_selector: str
    sandbox_image_pull_secret: str
    warm_pool_priority_class: str
    ondemand_priority_class: str
    pod_seccomp_profile: str

    def is_prod(self) -> bool:
        return self.service_env == "prod"


def load_settings(dotenv_path: str | None = None) -> Settings:
    """Load settings from the environment (optionally seeded from a .env file).

    Called once at startup. Prefer :func:`get_settings` elsewhere, which caches.
    """
    load_dotenv(dotenv_path=dotenv_path, override=False)
    s = Settings(
        service_name=_get_str("SERVICE_NAME", "sandbox-ctl"),
        service_env=_get_str("SERVICE_ENV", "dev"),
        http_host=_get_str("HTTP_HOST", "0.0.0.0"),
        http_port=_get_int("HTTP_PORT", 8080),
        http_request_timeout_s=_get_int("HTTP_REQUEST_TIMEOUT_S", 30),
        runtime_backend=_get_str("RUNTIME_BACKEND", "kubernetes"),
        runtime_driver=_get_str("RUNTIME_DRIVER", "container"),
        runtime_api_url=_get_str("RUNTIME_API_URL"),
        agent_grpc_endpoint=_get_str("AGENT_GRPC_ENDPOINT"),
        agent_timeout_s=_get_int("AGENT_TIMEOUT_S", 10),
        docker_network=_get_str("DOCKER_NETWORK", ""),
        warm_pool_size=_get_int("WARM_POOL_SIZE", 16),
        warm_pool_max_idle_s=_get_int("WARM_POOL_MAX_IDLE_S", 600),
        warm_pool_refill_concurrency=_get_int("WARM_POOL_REFILL_CONCURRENCY", 4),
        snapshot_store_url=_get_str("SNAPSHOT_STORE_URL"),
        snapshot_store_bucket=_get_str("SNAPSHOT_STORE_BUCKET"),
        snapshot_store_key_id=_get_str("SNAPSHOT_STORE_KEY_ID"),
        snapshot_store_secret=_get_str("SNAPSHOT_STORE_SECRET"),
        session_max_wall_s=_get_int("SESSION_MAX_WALL_S", 300),
        session_max_cpu_ms=_get_int("SESSION_MAX_CPU_MS", 60000),
        session_max_memory_mb=_get_int("SESSION_MAX_MEMORY_MB", 512),
        session_max_pids=_get_int("SESSION_MAX_PIDS", 256),
        session_scratch_mb=_get_int("SESSION_SCRATCH_MB", 256),
        tenant_max_concurrent=_get_int("TENANT_MAX_CONCURRENT", 32),
        tenant_quota_rps=_get_int("TENANT_QUOTA_RPS", 20),
        egress_default_policy=_get_str("EGRESS_DEFAULT_POLICY", "deny"),
        egress_allowlist_path=_get_str("EGRESS_ALLOWLIST_PATH", "/etc/sandbox-ctl/egress.yaml"),
        creds_signing_key_path=_get_str("CREDS_SIGNING_KEY_PATH"),
        creds_ttl_s=_get_int("CREDS_TTL_S", 300),
        otlp_endpoint=_get_str("OTLP_ENDPOINT", ""),
        otlp_sample_ratio=_get_float("OTLP_SAMPLE_RATIO", 0.1),
        metrics_port=_get_int("METRICS_PORT", 9090),
        log_level=_get_str("LOG_LEVEL", "INFO"),
        log_format=_get_str("LOG_FORMAT", "json"),
        kube_in_cluster=_get_bool("KUBE_IN_CLUSTER", True),
        kube_namespace=_get_str("KUBE_NAMESPACE", "sandbox"),
        kube_kubeconfig_path=_get_str("KUBE_KUBECONFIG_PATH", ""),
        runtime_class_mvm=_get_str("RUNTIME_CLASS_MVM", "kata-mvm"),
        runtime_class_ctr=_get_str("RUNTIME_CLASS_CTR", "runc-hardened"),
        sandbox_node_selector=_get_str("SANDBOX_NODE_SELECTOR", "role=sandbox"),
        sandbox_image_pull_secret=_get_str("SANDBOX_IMAGE_PULL_SECRET"),
        warm_pool_priority_class=_get_str("WARM_POOL_PRIORITY_CLASS", "warm-preemptible"),
        ondemand_priority_class=_get_str("ONDEMAND_PRIORITY_CLASS", "sandbox-ondemand"),
        pod_seccomp_profile=_get_str("POD_SECCOMP_PROFILE", "sandbox/default.json"),
    )
    _validate(s)
    return s


def _validate(s: Settings) -> None:
    if s.service_env not in {"dev", "staging", "prod"}:
        raise ConfigError(f"SERVICE_ENV must be dev|staging|prod, got {s.service_env!r}")
    if s.runtime_backend not in {"kubernetes", "docker"}:
        raise ConfigError(f"RUNTIME_BACKEND must be kubernetes|docker, got {s.runtime_backend!r}")
    if s.runtime_driver not in {"firecracker", "container"}:
        raise ConfigError(f"RUNTIME_DRIVER must be firecracker|container, got {s.runtime_driver!r}")
    if s.egress_default_policy not in {"deny", "allow"}:
        raise ConfigError(
            f"EGRESS_DEFAULT_POLICY must be deny|allow, got {s.egress_default_policy!r}"
        )
    if s.log_format not in {"json", "text"}:
        raise ConfigError(f"LOG_FORMAT must be json|text, got {s.log_format!r}")
    if not 0.0 <= s.otlp_sample_ratio <= 1.0:
        raise ConfigError(f"OTLP_SAMPLE_RATIO must be in [0,1], got {s.otlp_sample_ratio!r}")
    if s.warm_pool_size < 0:
        raise ConfigError(f"WARM_POOL_SIZE must be >= 0, got {s.warm_pool_size}")
    if s.session_max_wall_s <= 0:
        raise ConfigError(f"SESSION_MAX_WALL_S must be > 0, got {s.session_max_wall_s}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return load_settings()


def reset_settings_cache() -> None:
    """Clear the cached settings — for tests only."""
    get_settings.cache_clear()
