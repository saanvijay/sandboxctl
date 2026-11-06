"""Enforce DESIGN.md §7 ↔ .env.example ↔ config.py agreement.

Three things must name the same set of env vars:

- the field set loaded in ``config.py``
- the keys declared in ``.env.example``
- the rows in DESIGN.md §7

AGENTS.md calls this out explicitly as a hard invariant.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


_FIELD_TO_ENV = {
    "service_name": "SERVICE_NAME",
    "service_env": "SERVICE_ENV",
    "http_host": "HTTP_HOST",
    "http_port": "HTTP_PORT",
    "http_request_timeout_s": "HTTP_REQUEST_TIMEOUT_S",
    "runtime_backend": "RUNTIME_BACKEND",
    "runtime_driver": "RUNTIME_DRIVER",
    "runtime_api_url": "RUNTIME_API_URL",
    "agent_grpc_endpoint": "AGENT_GRPC_ENDPOINT",
    "agent_timeout_s": "AGENT_TIMEOUT_S",
    "docker_network": "DOCKER_NETWORK",
    "warm_pool_size": "WARM_POOL_SIZE",
    "warm_pool_max_idle_s": "WARM_POOL_MAX_IDLE_S",
    "warm_pool_refill_concurrency": "WARM_POOL_REFILL_CONCURRENCY",
    "snapshot_store_url": "SNAPSHOT_STORE_URL",
    "snapshot_store_bucket": "SNAPSHOT_STORE_BUCKET",
    "snapshot_store_key_id": "SNAPSHOT_STORE_KEY_ID",
    "snapshot_store_secret": "SNAPSHOT_STORE_SECRET",
    "session_max_wall_s": "SESSION_MAX_WALL_S",
    "session_max_cpu_ms": "SESSION_MAX_CPU_MS",
    "session_max_memory_mb": "SESSION_MAX_MEMORY_MB",
    "session_max_pids": "SESSION_MAX_PIDS",
    "session_scratch_mb": "SESSION_SCRATCH_MB",
    "tenant_max_concurrent": "TENANT_MAX_CONCURRENT",
    "tenant_quota_rps": "TENANT_QUOTA_RPS",
    "egress_default_policy": "EGRESS_DEFAULT_POLICY",
    "egress_allowlist_path": "EGRESS_ALLOWLIST_PATH",
    "creds_signing_key_path": "CREDS_SIGNING_KEY_PATH",
    "creds_ttl_s": "CREDS_TTL_S",
    "otlp_endpoint": "OTLP_ENDPOINT",
    "otlp_sample_ratio": "OTLP_SAMPLE_RATIO",
    "metrics_port": "METRICS_PORT",
    "log_level": "LOG_LEVEL",
    "log_format": "LOG_FORMAT",
    "kube_in_cluster": "KUBE_IN_CLUSTER",
    "kube_namespace": "KUBE_NAMESPACE",
    "kube_kubeconfig_path": "KUBE_KUBECONFIG_PATH",
    "runtime_class_mvm": "RUNTIME_CLASS_MVM",
    "runtime_class_ctr": "RUNTIME_CLASS_CTR",
    "sandbox_node_selector": "SANDBOX_NODE_SELECTOR",
    "sandbox_image_pull_secret": "SANDBOX_IMAGE_PULL_SECRET",
    "warm_pool_priority_class": "WARM_POOL_PRIORITY_CLASS",
    "ondemand_priority_class": "ONDEMAND_PRIORITY_CLASS",
    "pod_seccomp_profile": "POD_SECCOMP_PROFILE",
}


def _parse_env_example() -> set[str]:
    path = _REPO / ".env.example"
    keys: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            keys.add(line.split("=", 1)[0])
    return keys


def _parse_design_table() -> set[str]:
    path = _REPO / "DESIGN.md"
    text = path.read_text()
    section = text.split("## 7. Configuration", 1)[1].split("## 8.", 1)[0]
    # Match only the first cell on each row: a line beginning with `|` then a
    # backticked UPPER_SNAKE identifier. Avoids picking up value-cell tokens
    # like `INFO` or `json` that happen to be uppercase.
    rows = re.findall(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|", section, flags=re.MULTILINE)
    return set(rows)


def test_env_example_matches_config() -> None:
    config_vars = set(_FIELD_TO_ENV.values())
    env_example = _parse_env_example()
    assert config_vars == env_example, (
        f"missing in .env.example: {sorted(config_vars - env_example)}\n"
        f"extra in .env.example: {sorted(env_example - config_vars)}"
    )


def test_env_example_matches_design() -> None:
    env_example = _parse_env_example()
    design = _parse_design_table()
    assert env_example == design, (
        f"in .env.example only: {sorted(env_example - design)}\n"
        f"in DESIGN.md only: {sorted(design - env_example)}"
    )


def test_config_fields_match_mapping() -> None:
    """The ``_FIELD_TO_ENV`` map must cover every ``Settings`` field."""
    from dataclasses import fields

    from sandbox_ctl.config import Settings

    declared = {f.name for f in fields(Settings)}
    mapped = set(_FIELD_TO_ENV.keys())
    assert declared == mapped, (
        f"missing in mapping: {sorted(declared - mapped)}\n"
        f"stale in mapping: {sorted(mapped - declared)}"
    )
