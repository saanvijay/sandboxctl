# DESIGN.md

Design document for the Sandbox Control Plane — a Python service that provisions,
monitors, and tears down isolated sandboxes that execute untrusted,
model-generated code and agent workloads.

Follow [AGENTS.md](AGENTS.md). When this document and the code disagree, update
one of them in the same change — never leave them in conflict.

---

## 1. Purpose and Scope

### Purpose
Run untrusted code produced by LLMs and agents inside strongly isolated,
short-lived sandboxes at scale. Give callers a simple API — "run this code,
return the result" — and absorb the complexity of isolation, lifecycle, and
observability behind it.

### In scope
- Lifecycle: create, execute, snapshot, restore, destroy a sandbox.
- Warm pools and snapshot/restore to minimize cold start.
- Isolation across compute (CPU, memory, PID, time), filesystem (ro root,
  scratch overlays), and network (egress allowlists, per-session creds).
- Resource accounting and quotas per tenant and per session.
- Monitoring, tracing, and in-sandbox debugging surfaces.

### Out of scope (for now)
- The LLM or agent that generates the code — this service only runs code.
- Long-lived, multi-day sessions. The target is seconds to minutes.
- Multi-region orchestration. A single control plane serves one region;
  cross-region is a layer above.
- A full developer IDE. We expose primitives; UI is a separate project.

### Non-goals
- Perfect bug-for-bug compatibility with any specific local environment.
- Running kernel-level or privileged workloads submitted by callers.

---

## 2. Threat Model (Summary)

Attacker is the code running inside the sandbox. Assume it is actively hostile,
has full control of the guest userspace, and may know the host software stack.

**Must prevent**
- Breakout to host kernel or neighboring sandboxes.
- Exfiltration of credentials or data belonging to other tenants.
- Unapproved network egress.
- Resource exhaustion of the host (CPU, memory, inodes, FDs, PIDs).

**Accept (and detect)**
- A sandbox corrupting its own filesystem — it is discarded after use.
- A sandbox exceeding its own quotas — kill and record.

See `security/threat-model.md` for the full version (to be added alongside the
first production deploy).

---

## 3. High-Level Architecture

```
                 +----------------------+
    caller  --->  |  API Gateway (HTTP) |
                 +----------+-----------+
                            |
                            v
                 +----------------------+        +------------------+
                 |  Session Manager     | <----> |  Warm Pool       |
                 |  (orchestrates)      |        |  (pre-booted VMs)|
                 +----+-----------+-----+        +------------------+
                      |           |
                      v           v
         +---------------+   +------------------+
         | Sandbox Agent |   | Snapshot Store   |
         | (per sandbox) |   | (RO base images, |
         +-------+-------+   |  checkpoints)    |
                 |           +------------------+
                 v
         +---------------+
         | microVM /     |
         | container     |
         | (isolate.rs)  |
         +---------------+
                 |
                 v
         +---------------+   +------------------+
         | Egress Proxy  |-->| Allowlist Policy |
         +---------------+   +------------------+
                 |
                 v
         +---------------+
         | Telemetry Bus |  (traces, metrics, logs)
         +---------------+
```

The Python code in this repository is the **control plane**: API Gateway,
Session Manager, Warm Pool, Snapshot Store client, Egress Proxy configuration,
Telemetry fan-out. The in-sandbox agent and the microVM runtime are separate
components (likely Rust / Go / C) and are addressed over a well-defined
protocol. Treat them as external systems from the Python side.

---

## 4. Module Layout

Every file has one purpose. One class per file where the class is the file's
purpose.

```
src/sandbox_ctl/
├── __init__.py
├── config.py                    # Load + validate env vars. One source of truth.
├── boot.py                      # Compose AppContext for the uvicorn entrypoint.
│
├── api/
│   ├── app.py                   # ASGI app factory. Routes only, no logic.
│   ├── routes_sessions.py       # POST/GET/DELETE /sessions.
│   ├── routes_health.py         # /healthz, /readyz.
│   └── auth.py                  # Verify caller identity, extract tenant.
│
├── session/
│   ├── manager.py               # SessionManager: orchestrates one session.
│   ├── state.py                 # SessionState dataclass + transitions.
│   ├── quotas.py                # Per-tenant and per-session quota enforcement.
│   └── registry.py              # In-memory + persisted session lookup.
│
├── pool/
│   ├── warm_pool.py             # Pre-created idle sandbox Pods per flavor.
│   └── refiller.py              # Background refill loop against the K8s API.
│
├── snapshot/
│   ├── store.py                 # SnapshotStore: list/get/put metadata.
│   ├── restorer.py              # Restore a sandbox from a snapshot id.
│   └── checkpointer.py          # Checkpoint a live sandbox into a snapshot.
│
├── runtime/
│   ├── driver.py                # Driver interface (abstract).
│   ├── k8s_driver.py            # Create/watch/destroy sandbox Pods via K8s.
│   ├── docker_driver.py         # Docker backend for local dev (RUNTIME_BACKEND=docker).
│   ├── docker_agent.py          # Agent client that runs code via `docker exec`.
│   ├── boot.py                  # Select driver + agent by RUNTIME_BACKEND.
│   ├── pod_spec.py              # Builds the Pod spec for a given flavor.
│   └── agent_client.py          # Talks to the in-sandbox agent (gRPC).
│
├── isolation/
│   ├── compute.py               # cgroup v2 config: CPU, memory, pids.
│   ├── filesystem.py            # Overlay layout, ro root, scratch size.
│   ├── seccomp.py               # Seccomp profile selection.
│   └── creds.py                 # Per-session credential materialization + revoke.
│
├── network/
│   ├── egress_proxy.py          # Configure per-session egress proxy rules.
│   ├── allowlist.py             # Allowlist policy evaluation.
│   └── dns.py                   # Per-session DNS resolver pinning.
│
├── telemetry/
│   ├── logger.py                # Structured logging setup.
│   ├── tracer.py                # OpenTelemetry tracer provider.
│   ├── metrics.py               # Prometheus metrics registration.
│   └── events.py                # Lifecycle event emitter.
│
└── debug/
    ├── timeline.py              # Build a per-session timeline from spans.
    ├── introspect.py            # Pull /proc, cgroup stats from a live sandbox.
    └── profiler.py              # On-demand CPU/alloc profile from inside sandbox.

tests/
├── unit/
│   └── test_<module>.py         # Mirrors src/ layout.
└── e2e/
    ├── test_lifecycle.py        # Create → exec → destroy.
    ├── test_warm_pool.py        # Cold vs warm start timings.
    ├── test_snapshot_restore.py # Round-trip a session.
    ├── test_isolation.py        # Breakout, exhaustion, egress attempts.
    └── test_credentials.py      # Credentials scoped and revoked on teardown.
```

---

## 5. Data Flow — Primary Operation

### 5.1 `POST /sessions/run` (synchronous short job)

1. **API Gateway** receives the request. `auth.py` extracts and verifies the
   tenant identity. Request body is validated.
2. **Session Manager** allocates a `SessionState`, consults `quotas.py`
   (rejects on exceeded tenant limits), and generates a session id.
3. **Warm Pool** is asked for a ready sandbox. On hit, the sandbox is leased.
   On miss, a cold boot is started via `runtime.driver` and a fresh pool
   refill is scheduled.
4. **Isolation** modules apply the final per-session config: cgroup limits,
   overlay filesystem bind, seccomp profile, DNS pinning, egress proxy rules.
5. **Credentials** for this session (short-lived, narrowly scoped) are minted
   and injected via the in-sandbox agent — never written to disk on the host.
6. **Agent Client** sends the code and inputs to the in-sandbox agent, which
   runs them and streams stdout/stderr/results back.
7. **Telemetry** records spans and emits lifecycle events throughout.
8. **Teardown**: credentials are revoked, the sandbox is destroyed (microVM
   killed, overlays unmounted, cgroup removed). The session is marked
   terminal; the warm pool refills asynchronously.

### 5.2 Snapshot / Restore

- `POST /sessions/{id}/snapshot` → `checkpointer.py` pauses the sandbox,
  tells the runtime to produce a snapshot, uploads it to `snapshot/store.py`
  with metadata (base image id, kernel version, memory size, caller tenant).
- `POST /sessions` with `restore_from=<snapshot_id>` → `restorer.py` fetches
  the snapshot, hands it to the runtime driver, which brings up a VM from
  that state. Isolation layer re-applies per-session scope (credentials and
  egress rules do **not** survive snapshotting; they are re-minted).

### 5.3 Warm Pool

- A background task in `pool/refiller.py` keeps `WARM_POOL_SIZE` sandboxes
  pre-booted per flavor (combination of base image + resource shape).
- Each warm sandbox has no credentials and no network egress — it is inert
  until leased. Leasing is what grants it a scoped identity.
- Sandboxes in the pool have a max idle age (`WARM_POOL_MAX_IDLE_S`) after
  which they are recycled; this bounds exposure to any latent issue.

---

## 6. External Dependencies

| Dependency | Why it's used | Alternative considered |
|---|---|---|
| `fastapi` | ASGI framework, request validation, OpenAPI for free. | `starlette` directly — less ergonomic for the API surface we expose. |
| `uvicorn` | Production ASGI server. | `hypercorn` — comparable; fastapi/uvicorn is the common pairing. |
| `pydantic` v2 | Request/response schemas, config validation. | Hand-rolled dataclasses — more code, worse errors at the boundary. |
| `python-dotenv` | Load `.env` for local and container runs. | OS env only — makes local dev painful. |
| `httpx` | Async HTTP to the snapshot store and other services. | `requests` — sync only; we need async concurrency. |
| `kubernetes` | Official Python K8s client; create/watch/destroy sandbox Pods. | Rolling our own against the raw API — pointless reinvention. |
| `grpcio` | Talk to the in-sandbox agent over gRPC. | HTTP/JSON — higher overhead on the hot path. |
| `opentelemetry-sdk` + `-exporter-otlp` | Traces and metrics, vendor-neutral. | Vendor-specific SDKs — lock-in. |
| `prometheus-client` | Metrics scrape endpoint. | Push to OTLP only — breaks existing Prom infra. |
| `structlog` | Structured JSON logs with context binding. | stdlib `logging` only — reinventable, but structlog composes cleanly on top. |
| `cryptography` | Minting and verifying short-lived credentials. | PyJWT only — narrower than we need. |

Test/dev:
`pytest`, `pytest-asyncio`, `pytest-mock`, `ruff`, `mypy`, `hypothesis`
(for property tests on quota and allowlist logic).

**Pinning**: all production deps are pinned to exact versions in
`requirements.txt`. Dev deps live in `requirements-dev.txt`.

---

## 7. Configuration

Every tunable value comes from the environment (loaded from `.env` locally,
set by the orchestrator in production). `config.py` is the only module that
reads env vars; everything else imports typed values from it.

Mirrors `.env.example`:

| Variable | Type | Default | Meaning |
|---|---|---|---|
| `SERVICE_NAME` | str | `sandbox-ctl` | Logical name used in logs and traces. |
| `SERVICE_ENV` | str | `dev` | `dev` / `staging` / `prod`. Gates verbose logging. |
| `HTTP_HOST` | str | `0.0.0.0` | Bind address for the API. |
| `HTTP_PORT` | int | `8080` | Bind port. |
| `HTTP_REQUEST_TIMEOUT_S` | int | `30` | Max wall time for any single API request. |
| `RUNTIME_BACKEND` | str | `kubernetes` | `kubernetes` (prod) or `docker` (local dev). Selects the Driver backend. |
| `RUNTIME_DRIVER` | str | `container` | `firecracker` or `container`. K8s isolation tier; ignored by the docker backend. |
| `RUNTIME_API_URL` | str | — | Base URL of the runtime driver API. Read only by the K8s backend. |
| `AGENT_GRPC_ENDPOINT` | str | — | How the control plane reaches the in-sandbox agent. Ignored by the docker backend. |
| `AGENT_TIMEOUT_S` | int | `10` | Timeout for a single agent RPC. |
| `DOCKER_NETWORK` | str | `` | Optional Docker network for sandbox containers. Empty = default bridge. |
| `WARM_POOL_SIZE` | int | `16` | Pre-booted sandboxes kept ready per flavor. |
| `WARM_POOL_MAX_IDLE_S` | int | `600` | Max age of an unused warm sandbox. |
| `WARM_POOL_REFILL_CONCURRENCY` | int | `4` | How many sandboxes we boot in parallel. |
| `SNAPSHOT_STORE_URL` | str | — | Object store URL for snapshots. |
| `SNAPSHOT_STORE_BUCKET` | str | — | Bucket / container name. |
| `SNAPSHOT_STORE_KEY_ID` | str | — | Access key id. |
| `SNAPSHOT_STORE_SECRET` | str | — | Access secret (never logged). |
| `SESSION_MAX_WALL_S` | int | `300` | Hard cap on a session's wall time. |
| `SESSION_MAX_CPU_MS` | int | `60000` | Hard cap on CPU time. |
| `SESSION_MAX_MEMORY_MB` | int | `512` | Memory ceiling. |
| `SESSION_MAX_PIDS` | int | `256` | PID limit inside the sandbox. |
| `SESSION_SCRATCH_MB` | int | `256` | Writable scratch size. |
| `TENANT_MAX_CONCURRENT` | int | `32` | Concurrent sessions per tenant. |
| `TENANT_QUOTA_RPS` | int | `20` | Session creations per second per tenant. |
| `EGRESS_DEFAULT_POLICY` | str | `deny` | `deny` or `allow` (allow is dev-only). |
| `EGRESS_ALLOWLIST_PATH` | str | `/etc/sandbox-ctl/egress.yaml` | Allowlist source. |
| `CREDS_SIGNING_KEY_PATH` | str | — | Path to the signing key for short-lived creds. |
| `CREDS_TTL_S` | int | `300` | Lifetime of minted credentials. |
| `OTLP_ENDPOINT` | str | — | OTLP collector endpoint. |
| `OTLP_SAMPLE_RATIO` | float | `0.1` | Trace sampling ratio. |
| `METRICS_PORT` | int | `9090` | Prometheus scrape port. |
| `LOG_LEVEL` | str | `INFO` | Root log level. |
| `LOG_FORMAT` | str | `json` | `json` or `text`. |
| `KUBE_IN_CLUSTER` | bool | `true` | Load in-cluster config vs. kubeconfig. |
| `KUBE_NAMESPACE` | str | `sandbox` | Namespace where sandbox Pods are created. |
| `KUBE_KUBECONFIG_PATH` | str | — | Only used when `KUBE_IN_CLUSTER=false`. |
| `RUNTIME_CLASS_MVM` | str | `kata-mvm` | RuntimeClass for the microVM tier. |
| `RUNTIME_CLASS_CTR` | str | `runc-hardened` | RuntimeClass for the container tier. |
| `SANDBOX_NODE_SELECTOR` | str | `role=sandbox` | Label selector for sandbox nodes. |
| `SANDBOX_IMAGE_PULL_SECRET` | str | — | ImagePullSecret for private base images. |
| `WARM_POOL_PRIORITY_CLASS` | str | `warm-preemptible` | Preempted when on-demand runs arrive. |
| `ONDEMAND_PRIORITY_CLASS` | str | `sandbox-ondemand` | Normal priority for leased sessions. |
| `POD_SECCOMP_PROFILE` | str | `sandbox/default.json` | Localhost seccomp profile path. |

The service **refuses to start** if any variable without a default is unset.

---

## 8. Isolation Model (Detail)

### Compute
- cgroup v2 with `cpu.max`, `memory.max`, `memory.swap.max=0`, `pids.max`.
- `prlimit` ceilings for FDs and nofile.
- Wall-time deadline enforced by the Session Manager and independently by the
  in-sandbox agent (defense in depth).

### Filesystem
- Read-only base image, mounted as the sandbox root.
- Per-session overlay with capped size (`SESSION_SCRATCH_MB`); torn down on
  teardown.
- No bind mounts from the host beyond what the agent protocol needs.
- `noexec`, `nosuid`, `nodev` on scratch mounts.

### Network
- Default egress policy is `deny`. The egress proxy is the only path out.
- Per-session allowlist is evaluated on each connect by `allowlist.py`.
- DNS is pinned to an in-cluster resolver that enforces the same allowlist.
- No incoming connections.

### Credentials
- Credentials for a session are minted at lease time, bound to the session id
  and the tenant, carry a short TTL (`CREDS_TTL_S`), and are injected via the
  agent so they never land in a host-side log, env dump, or snapshot.
- On session end, credentials are proactively revoked at their issuer; TTL is
  the fallback, not the primary mechanism.

### Kernel / Hypervisor
- Primary tier runs microVMs (Firecracker-class) — hardware virtualization
  boundary between tenants.
- Secondary tier (optional, lower density needs higher trust) runs OCI
  containers with user namespaces + seccomp + AppArmor.
- Choice of tier is per-flavor policy, not per-caller.

---

## 9. Observability

- **Structured logs** (JSON in prod) with `session_id`, `tenant_id`,
  `flavor_id`, `trace_id` bound into every record.
- **Traces** span the full lifecycle: `acquire` → `apply_isolation` →
  `mint_creds` → `exec` → `teardown`. Spans from the in-sandbox agent are
  continuations of the control-plane trace.
- **Metrics** (at minimum): cold-start seconds, warm-start seconds, pool
  occupancy, pool miss ratio, snapshot restore seconds, egress denies per
  tenant, teardown failures, session wall-time histogram.
- **Debug surfaces**: `debug/timeline.py` produces a human-readable timeline
  of a session from its spans. `debug/introspect.py` pulls `/proc` and
  cgroup stats from a live sandbox for on-call. `debug/profiler.py` triggers
  an on-demand CPU profile inside the sandbox via the agent.

---

## 10. Performance Targets (initial)

These are targets, not guarantees — they drive design decisions and get
measured by the e2e suite.

| Metric | Target |
|---|---|
| Cold start (microVM, base image cached) | < 300 ms p50, < 800 ms p99 |
| Warm start (lease from pool) | < 30 ms p50, < 100 ms p99 |
| Snapshot restore | < 150 ms p50, < 500 ms p99 |
| Teardown | < 100 ms p50 |
| Density per host | 200+ concurrent sandboxes on a standard node |
| Control-plane overhead per session | < 20 ms excluding runtime boot |

---

## 11. Trade-offs and Rejected Alternatives

- **Firecracker over gVisor as primary tier.** gVisor has a smaller
  compatibility surface than a real kernel but adds per-syscall overhead
  that hurts the kinds of agent workloads we see (lots of syscalls from
  Python, Node, shell). We keep gVisor-style user-space kernels on the
  shortlist for a specific low-trust container tier if microVM density
  turns out insufficient.
- **Container runtime as primary tier was rejected.** Shared kernel between
  tenants is not acceptable at our threat model's default sensitivity. We
  keep it as a secondary tier for workloads an operator explicitly opts in.
- **Per-session short-lived credentials over long-lived shared ones.** Blast
  radius of a leaked credential is the session's TTL, not the lifetime of a
  deployed secret. Costs us a credential-mint round trip per session; worth
  it.
- **Allowlist-based egress over "block known bad".** Allowlist is small,
  auditable, and defaults closed. Denylists invite bypass by novel hosts
  and can't be reasoned about statically.
- **Snapshotting excludes credentials and egress state.** Including them
  would be convenient but would let a snapshot be restored into an
  unauthorized context. Re-mint on restore.
- **Python for the control plane, not the data plane.** The hot path for
  byte streaming and syscall-level isolation lives in languages that give
  us tighter control (Rust for the agent and runtime glue). Python is
  where orchestration logic, policy, and APIs are easiest to evolve
  safely.
- **One warm pool per flavor, not one global pool.** Simpler accounting
  and no cross-flavor fallbacks that would confuse latency SLOs.
- **Kata Containers over KubeVirt for the VM tier.** KubeVirt is tuned for
  long-lived, pet-like VMs with full device emulation. Kata gives us
  Pod-shaped, short-lived microVMs with a minimal device model — the right
  fit for sub-second lifecycles. KubeVirt stays an option only if we ever
  need long-running VM sessions.
- **kube-scheduler over a bespoke scheduler.** Writing our own only earns
  its keep if standard constraints can't express our placement rules.
  Anti-affinity, taints, and priority classes cover the current needs.
  If image-locality or warm-pool-aware scheduling becomes a bottleneck,
  we add a scheduler plugin, not a parallel scheduler.
- **Sandbox-as-Pod over sandbox-as-child-process on a DaemonSet host-agent.**
  Pod-shaped sandboxes get placement, resource accounting, lifecycle,
  logging, and node scaling from Kubernetes for free. The host-agent model
  reinvents all of that and makes the sandbox invisible to the cluster.
- **A first-class Docker backend alongside Kubernetes, selected by env.**
  A control plane whose only deploy target is Kubernetes is painful to
  evolve: iterating on the API, session state machine, or quota logic
  needs a cluster to see a real end-to-end run. We keep the same
  `Driver` / `AgentClient` interfaces and add `DockerDriver` +
  `DockerExecAgent` behind a `RUNTIME_BACKEND=docker` switch, so the
  laptop path exercises the same manager, pool, registry, and HTTP
  surface as prod. Isolation is weaker (shared kernel, no microVM) and
  the dev backend never runs real tenant workloads — the trade-off is
  explicit and the selection is per-deploy, not per-request.

---

## 12. Open Questions

- Checkpoint cadence policy — on explicit API call only, or opportunistic?
- Whether to expose a "live attach a debugger" surface to callers, and if so
  what the auth model looks like.
- Multi-tenant fair-share scheduling across the warm-pool refill queue
  under saturation.
- How to represent allowlist policies that are per-tenant *and* per-flavor
  without exploding the config.

Resolve each before the module that depends on it is written; log the
resolution here when it lands.

---

## 13. Change Protocol

- Any PR that adds a module adds a row to §4 and a brief in §5 if it
  changes a flow.
- Any PR that adds config adds a row to §7 **and** to `.env.example`.
- Any PR that changes isolation posture, threat model, or performance
  targets updates §8, §2, or §10 respectively in the same change.
- Design drift is a bug. If you see it, fix the doc or the code.

---

## 14. Kubernetes Deployment

Kubernetes is the deployment target. Each sandbox is a short-lived Pod;
Kubernetes handles placement, lifecycle, resource accounting, and node
scaling. The control plane *creates* those Pods and tracks sessions — it
does not spawn raw processes on nodes.

### 14.1 Topology

**Cluster services** (Deployments, HPA-scaled, stateless):

- `sandbox-api` — API Gateway + Session Manager (Python).
- `sandbox-pool` — Warm-pool manager; pre-creates idle sandbox Pods.
- `sandbox-egress-ctl` — Serves per-session egress allowlists.
- `sandbox-snapshot` — Snapshot upload/download coordinator.

**Platform services** (one Deployment or DaemonSet each):

- `egress-proxy` — DaemonSet; one per node, enforces per-session rules.
- `otel-collector` — DaemonSet; sidecar collector per node.
- `prometheus`, `loki` — standard cluster observability.

**Per-request**:

- `sandbox-<id>` — one Pod per run, created by `sandbox-api`, destroyed on
  completion or deadline.

### 14.2 RuntimeClasses

Two RuntimeClasses select the isolation boundary:

```yaml
kind: RuntimeClass
metadata: { name: kata-mvm }        # microVM tier — default for untrusted code
handler: kata
---
kind: RuntimeClass
metadata: { name: runc-hardened }   # container tier — opt-in, higher density
handler: runc
```

Flavor policy decides which class a Pod gets. Both classes carry the same
seccomp profile, NetworkPolicy, and resource shape — the only difference
is the isolation boundary.

### 14.3 The sandbox Pod shape

Each run creates a Pod with roughly this spec (built by
`runtime/pod_spec.py`):

```yaml
spec:
  runtimeClassName: kata-mvm            # or runc-hardened
  automountServiceAccountToken: false
  activeDeadlineSeconds: <SESSION_MAX_WALL_S>
  restartPolicy: Never
  nodeSelector:
    role: sandbox
  tolerations:
    - key: role
      value: sandbox
      effect: NoSchedule
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    fsGroup: 10001
    seccompProfile:
      type: Localhost
      localhostProfile: sandbox/default.json
  containers:
    - name: agent
      image: <signed base image for the requested flavor>
      imagePullPolicy: IfNotPresent
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities: { drop: ["ALL"] }
      resources:
        requests: { cpu: "...", memory: "..." }
        limits:   { cpu: "...", memory: "..." }
      env:
        - name: SESSION_ID        # injected
        - name: AGENT_ENDPOINT    # how it reports back
      volumeMounts:
        - { name: scratch, mountPath: /scratch }
        - { name: code,    mountPath: /work, readOnly: true }
  volumes:
    - name: scratch
      emptyDir: { medium: Memory, sizeLimit: <SESSION_SCRATCH_MB>Mi }
    - name: code
      projected:
        sources:
          - secret: { name: run-<id>-code }   # the submitted code
```

Labels: `session_id`, `tenant_id`, `flavor_id` — used for selectors,
NetworkPolicy, and metrics.

### 14.4 NetworkPolicy (default-deny egress)

Every sandbox Pod is subject to:

```yaml
kind: NetworkPolicy
spec:
  podSelector: { matchLabels: { app: sandbox } }
  policyTypes: [Ingress, Egress]
  ingress: []
  egress:
    - to:
        - podSelector: { matchLabels: { app: egress-proxy } }
      ports: [{ protocol: TCP, port: 3128 }]
    - to:
        - podSelector: { matchLabels: { app: kube-dns } }
          namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
      ports: [{ protocol: UDP, port: 53 }]
```

Only the egress proxy (and DNS) are reachable. The proxy enforces the
per-session allowlist from `sandbox-egress-ctl`.

### 14.5 Node pools

- `sandbox-mvm-pool` — bare-metal or nested-virt nodes with `/dev/kvm`,
  taint `role=sandbox:NoSchedule`. Hosts Kata-runtime Pods.
- `sandbox-ctr-pool` — standard nodes, same taint, container tier.
- `system-pool` — default pool for cluster services. No sandbox taint.

Dedicated node pools ensure untrusted workloads never share a kernel with
cluster services, even for the container tier.

### 14.6 Scaling

**Control plane**:

- HorizontalPodAutoscaler on `sandbox-api` (CPU + custom metric:
  `inflight_sessions_per_pod`).
- HPA on `sandbox-pool` keyed to pool-miss ratio.

**Sandbox nodes**:

- Cluster Autoscaler (or Karpenter) on `sandbox-mvm-pool` and
  `sandbox-ctr-pool`. Pending sandbox Pods trigger node scale-up; nodes
  drain and scale down on idle.
- PodDisruptionBudget on cluster services (`minAvailable`), none on
  sandbox Pods (they are expected to be ephemeral).

**Warm pool**:

- `sandbox-pool` pre-creates N idle Pods per flavor, labeled
  `pool=warm, session_id=""`. A run lease relabels one of them to the
  real session id and sends the code.
- Pre-created Pods carry no credentials and sit under the same default-deny
  NetworkPolicy, so they remain inert until leased.

### 14.7 Scheduling

We rely on `kube-scheduler`. The custom bits are:

- Pod topology-spread by `tenant_id` (anti-affinity).
- Priority classes: cluster services > on-demand sandbox > warm pool. Warm
  Pods are preemptible so on-demand runs always win under pressure.
- Image locality: `sandbox-pool` prefers nodes that already have the
  flavor image cached (handled by the scheduler's default image-locality
  scoring).

### 14.8 Rollout

- Cluster services: standard rolling update with `maxSurge=1`,
  `maxUnavailable=0`.
- Base images: new tag → `sandbox-pool` drains old warm Pods for that
  flavor and refills with the new tag. Canary tenant first.
- RuntimeClass changes are rare and go through a node-pool rotation.

### 14.9 Secrets and credentials

- Submitted code is created as a Secret (`run-<id>-code`), mounted
  read-only into the Pod, and deleted on teardown.
- Per-session outbound credentials are minted by `sandbox-api` and
  injected as env vars at Pod create time only. Never stored in a
  ConfigMap, never logged. ServiceAccount token is NOT mounted
  (`automountServiceAccountToken: false`).
- Signing keys for credential minting live in a Secret mounted only into
  `sandbox-api`, projected from an external KMS when available.

### 14.10 Observability

- All sandbox Pods carry `session_id` / `tenant_id` labels; Prometheus
  recording rules and Loki queries pivot on these.
- OpenTelemetry traces: `sandbox-api` starts the trace; the in-Pod agent
  continues it via W3C `traceparent` passed through env.
- A `ServiceMonitor` per cluster-service Deployment.
- Standard dashboards (JSON in `deploy/dashboards/`) ship with the repo.

### 14.11 Dev / single-cluster mode (minikube or kind)

Local dev targets **minikube** by default; `kind` is a supported fallback.
The same Helm chart is used — only `values-dev.yaml` differs.

Minikube quickstart:

```bash
# Required: a CNI that enforces NetworkPolicy. kindnet (the default) does
# not, which would silently defeat the default-deny egress policy.
minikube start --cni=calico

# Required for HPA on control-plane pods.
minikube addons enable metrics-server

# Build and load the control-plane image. The name must match
# values-dev.yaml's image.repository:tag (sandbox-ctl:dev); the chart
# pins pullPolicy=Never in dev, so a mismatch shows up as
# ErrImageNeverPull on the api Pod.
docker build -t sandbox-ctl:dev .
minikube image load sandbox-ctl:dev

# Install (creates the namespace on first run).
helm install sandbox-ctl deploy/helm/sandbox-ctl \
  -n sandbox --create-namespace \
  -f deploy/helm/sandbox-ctl/values-dev.yaml
```

Constraints in dev mode:

- **Container tier only.** Kata/microVM needs `/dev/kvm` inside the node
  VM; that doesn't work with the Docker driver on macOS and is finicky
  on Linux. `values-dev.yaml` leaves `RUNTIME_CLASS_MVM` unset, so flavor
  policy falls back to `runc-hardened` for every request.
- **Weaker isolation.** No hardware-virtualization boundary. Dev clusters
  must never run real tenant workloads.
- **Cluster Autoscaler is not exercised.** HPA on cluster services works;
  node scale-up/down is a staging/prod concern.
- **Snapshot store** is a MinIO Pod (installed via subchart).
- **Egress proxy still runs** so NetworkPolicy semantics match prod exactly.

`make dev` runs a preflight that checks (and refuses to proceed otherwise):

- `minikube status` reports Running.
- Cluster CNI enforces NetworkPolicy (apply a test policy and verify
  denial).
- `metrics-server` is reachable.

`kind` fallback: the same chart installs with
`-f values-dev.yaml --set cni.assumeEnforced=true` after starting kind with
a Calico or Cilium CNI config. Prefer minikube; `kind` is for CI only.

### 14.12 What ships with the repo

```
deploy/
├── helm/
│   └── sandbox-ctl/                  # one chart, values per environment
│       ├── Chart.yaml
│       ├── values.yaml               # defaults
│       ├── values-dev.yaml
│       ├── values-prod.yaml
│       └── templates/
│           ├── api-deployment.yaml
│           ├── api-hpa.yaml
│           ├── pool-deployment.yaml
│           ├── pool-hpa.yaml
│           ├── egress-proxy-ds.yaml
│           ├── runtimeclasses.yaml
│           ├── networkpolicies.yaml
│           ├── servicemonitors.yaml
│           └── priorityclasses.yaml
├── seccomp/
│   └── sandbox-default.json
└── dashboards/
    └── sandbox-overview.json
```

### 14.13 Dev/prod parity

The project runs on both minikube and production from the same image and
the same Helm chart. Parity is maintained by three rules:

1. **No environment branches in Python code.** `config.py` reads env vars
   from §7; the rest of the code acts on those typed values. There is no
   `if settings.env == "prod": ...`. Behavior differs only because inputs
   differ.
2. **Variance lives in `values-*.yaml` and env vars.** Resource shapes,
   runtime classes, node selectors, pull secrets, telemetry endpoints,
   feature flags — all set via Helm values that render env vars into Pods.
   A new environment is a new values file, never a new code path.
3. **Primitives are identical.** Seccomp profile, read-only root,
   `drop: ALL`, NetworkPolicy manifests, Pod security context,
   dashboards, and the API surface are the same objects in dev and prod.
   Only the isolation *boundary* changes (container vs. microVM), and
   that is a RuntimeClass selection, not a code change.

Caveats operators must know about dev vs. prod:

- **Isolation is weaker on minikube** (container tier only, no hardware
  virtualization boundary). Dev clusters never run real tenant workloads.
- **NetworkPolicy enforcement is a CNI concern.** `make dev` prefllights
  for Calico/Cilium; if the CNI silently ignores policies, default-deny
  egress becomes a no-op. Prod clusters guarantee enforcement.
- **Cluster Autoscaler is prod-only.** HPA exercises in both;
  node scale-up/down must be validated in staging before prod rollout.
- **Snapshot/restore flows exist in both** but are disabled by default in
  `values-dev.yaml` because snapshots are only meaningful for the microVM
  tier.

Enforcement:

- A unit test parses every `values-*.yaml` and asserts the set of env
  vars rendered into Pods matches §7's variable set exactly.
- A unit test greps the Python source for `SERVICE_ENV ==` and fails if
  it finds any — environment switches do not live in code.
- CI runs the e2e suite against a fresh minikube with
  `values-dev.yaml`; a parity suite re-runs the critical e2e tests
  (lifecycle, isolation, egress deny, credential scope) against a
  staging cluster with `values-prod.yaml` on every release candidate.

---

## 15. Local Docker Backend

The control plane supports a second backend selected by `RUNTIME_BACKEND`:

- `kubernetes` — production path. Sandboxes are Pods created via
  `K8sDriver`; code runs inside them via the gRPC `AsyncAgentClient` that
  talks to the in-sandbox agent.
- `docker` — local development path. Sandboxes are containers on the
  developer's local Docker daemon, created via `DockerDriver`; code is
  executed via `docker exec` by `DockerExecAgent`.

`src/sandbox_ctl/runtime/boot.py` is the single site that picks between
them. Everything above the driver layer — Session Manager, warm pool,
registry, quotas, credentials, HTTP API — is backend-agnostic.

### 15.1 Translation from Pod spec to `docker run`

`DockerDriver.create` takes the same Kubernetes-shaped Pod spec that
`K8sDriver` consumes and translates the subset that is enforceable
locally:

| Pod spec field | `docker run` argument | Notes |
|---|---|---|
| `metadata.name` | `--name` | Also the container id used by the agent. |
| `metadata.labels` | `--label k=v` (each) | Docker labels are immutable; `relabel` tracks updates in memory. |
| `spec.containers[0].image` | positional image arg | |
| `spec.containers[0].resources.limits.cpu` | `--cpus` | `500m` → `0.5`. |
| `spec.containers[0].resources.limits.memory` | `--memory` | `512Mi` → `512m`. |
| `spec.containers[0].securityContext.readOnlyRootFilesystem` | `--read-only` | |
| `spec.containers[0].securityContext.capabilities.drop` | `--cap-drop ALL` | Always applied. |
| (implicit) | `--security-opt no-new-privileges` | Always applied. |
| `spec.containers[0].env[*]` with `value` | `-e NAME=VALUE` | `valueFrom` (Secret-backed) entries are skipped; prod resolves them. |
| `spec.volumes[*].emptyDir.medium=Memory` + `volumeMounts[*]` | `--tmpfs <path>:rw,nosuid,noexec,nodev,size=<N>m` | Memory-backed scratch. Host-path volumes are intentionally not translated. |

The container is launched with a trivial keepalive command so the agent
can attach via `docker exec` for the lifetime of the session.

### 15.2 What the Docker backend does **not** provide

Primitives that are structurally Kubernetes-only are silently ignored in
Docker mode; running under `RUNTIME_BACKEND=docker` is an explicit
opt-out of them:

- `runtimeClassName`, `priorityClassName`, `nodeSelector`, `tolerations`.
- `automountServiceAccountToken`, `activeDeadlineSeconds`.
- `imagePullSecrets` (the local daemon uses whatever registry auth the
  user's Docker config holds).
- The default-deny `NetworkPolicy` — Docker networks do not enforce K8s
  `NetworkPolicy`. Local egress isolation is approximated by running
  sandbox containers on a dedicated `DOCKER_NETWORK` with no outbound
  routes, which is the operator's responsibility to create.

Isolation posture for the Docker backend:

| Boundary | Prod (Kata microVM) | Prod (runc-hardened) | Docker local |
|---|---|---|---|
| Kernel isolation | Hardware-virtualized | Shared with host | Shared with host |
| Seccomp profile | Pinned via RuntimeClass | Pinned via Pod spec | Docker default (no custom profile loaded by the driver) |
| `cap-drop=ALL` | Yes | Yes | Yes |
| `no-new-privileges` | Yes | Yes | Yes |
| `readOnlyRootFilesystem` | Yes | Yes | Yes |
| CPU / memory ceilings | cgroup v2 via kubelet | cgroup v2 via kubelet | cgroup via Docker |
| NetworkPolicy default-deny | Yes | Yes | **No** — rely on a dedicated bridge network |
| Short-lived credentials | Yes | Yes | Yes (same signer, same TTL) |

### 15.3 When to use which

- **`docker`** — day-to-day development on a laptop: changing a quota
  rule, extending the Pod-spec builder, iterating on the HTTP surface,
  running the e2e suite against a real executor without a cluster.
- **`kubernetes`** — any shared environment (staging, prod, CI parity
  runs). The local Docker backend is never a production option.

A unit test (`tests/unit/test_env_sync.py`) still enforces §7 ↔
`.env.example` ↔ `config.py` equality across both modes, and a unit
test for `runtime.boot` asserts the dispatch matches the configured
backend.
