# STATUS.md

Honest, current state of `sandbox-ctl`.

- **DESIGN.md** = where we are going.
- **STATUS.md** (this file) = where we actually are.

If the two disagree, the code is the tiebreaker.

---

## 1. What this project is

`sandbox-ctl` is **the control plane** for a sandboxed code-execution
service. It is the Python service that:

- accepts a run request over HTTP,
- picks or creates a sandbox,
- enforces quotas, mints a short-lived credential, builds a locked-down
  Kubernetes Pod spec,
- orchestrates the Pod's lifecycle (acquire → isolate → run → teardown),
- records lifecycle events, traces, and metrics.

It is **not** the thing that *runs the code*. The code runs inside a
sandbox (microVM or hardened container) that is a separate component. See
§3 "What is NOT in this repo" below.

---

## 2. Who this is for, and what they get today

### A developer wanting to run arbitrary / untrusted code

**What you get today:**

- A working HTTP API that models the full lifecycle (session states,
  quotas, credentials, Pod spec), tested end-to-end with fakes.
- A local-development path that round-trips real code without a cluster:
  `RUNTIME_BACKEND=docker` makes the control plane create sandbox
  containers on the local Docker daemon and execute code via
  `docker exec`. Isolation is laptop-grade (shared kernel, no microVM) —
  fine for development, never for production or real tenant workloads.

**What you don't get today:** a production-grade executor. For the real
microVM path you still need the in-sandbox agent binary and the Kata
runtime installed on your nodes (see Path C in §4).

→ If you just want to see submit → run → return working on your laptop,
the Docker backend closes the loop today.

### A developer extending the control plane

**What you get today:** a tested, typed, module-per-purpose Python
codebase (§4 of DESIGN.md). 104 tests pass. `ruff`, `mypy --strict`, and
the full `pytest` suite are all green. Every public function is typed.
Config is loaded in exactly one place.

**What you can do with this today:**

- Add a new flavor, a new allowlist rule shape, a new quota dimension.
- Swap the credential signer, auth verifier, or snapshot store.
- Replace `K8sDriver` or `AsyncAgentClient` with your own.
- Write unit tests against the fakes in [tests/unit/fakes.py](tests/unit/fakes.py).

→ This is the audience the code is *most* useful to today.

### An end user wanting to submit code and get output back

**What you get today:** the API shape is real. The orchestration is real.
The response you'd get back is defined and type-checked.

**What you don't get today:** a working `POST /sessions/run` without
further work. End-to-end execution needs the sandbox agent and a cluster
with the Kata handler installed; neither ships here.

→ Not usable as a service as-is.

### A devops / platform engineer deploying it

**What you get today:**

- A Helm chart in [deploy/helm/sandbox-ctl/](deploy/helm/sandbox-ctl/)
  with `values-dev.yaml` and `values-prod.yaml`.
- `Deployment`, `Service`, `ServiceAccount`, `Role`, `RoleBinding`,
  `NetworkPolicy` (default-deny egress), `RuntimeClass` objects, and
  `PriorityClass` objects — the right primitives to plug into Kubernetes.
- A seccomp profile at [deploy/seccomp/sandbox-default.json](deploy/seccomp/sandbox-default.json).
- A `Dockerfile` that builds the control-plane image.
- A `Makefile` with `make dev-preflight` (CNI + metrics-server checks).

**What you don't get today:**

- Node-level Kata installation (upstream Kata work on your nodes).
- A sandbox base image + agent binary (external component).
- An actual snapshot store (bucket / MinIO / S3 — operator config).
- A real auth verifier for production (the shipped auth is a dev-only
  `X-Tenant-Id` header shim).

→ You can `helm install` the chart and the control plane will come up,
scrape metrics, serve `/healthz`, and talk to the Kubernetes API — but
`POST /sessions/run` will fail because the sandbox side isn't there.

---

## 3. What is in this repo vs. not

### ✅ Implemented (in Python, in this repo)

| Area | Where |
|---|---|
| Config loader (one source of truth) | [src/sandbox_ctl/config.py](src/sandbox_ctl/config.py) |
| Local Docker runtime backend | [src/sandbox_ctl/runtime/docker_driver.py](src/sandbox_ctl/runtime/docker_driver.py), [src/sandbox_ctl/runtime/docker_agent.py](src/sandbox_ctl/runtime/docker_agent.py), [src/sandbox_ctl/runtime/boot.py](src/sandbox_ctl/runtime/boot.py) |
| Structured JSON logger | [src/sandbox_ctl/telemetry/logger.py](src/sandbox_ctl/telemetry/logger.py) |
| Prometheus metric registration | [src/sandbox_ctl/telemetry/metrics.py](src/sandbox_ctl/telemetry/metrics.py) |
| OpenTelemetry tracer wiring | [src/sandbox_ctl/telemetry/tracer.py](src/sandbox_ctl/telemetry/tracer.py) |
| Lifecycle event emitter | [src/sandbox_ctl/telemetry/events.py](src/sandbox_ctl/telemetry/events.py) |
| Compute / filesystem / seccomp primitives | [src/sandbox_ctl/isolation/](src/sandbox_ctl/isolation/) |
| HMAC-signed short-lived credentials | [src/sandbox_ctl/isolation/creds.py](src/sandbox_ctl/isolation/creds.py) |
| Allowlist evaluation, DNS pinning, egress proxy client | [src/sandbox_ctl/network/](src/sandbox_ctl/network/) |
| Pod spec builder | [src/sandbox_ctl/runtime/pod_spec.py](src/sandbox_ctl/runtime/pod_spec.py) |
| Kubernetes driver (create / destroy / relabel) | [src/sandbox_ctl/runtime/k8s_driver.py](src/sandbox_ctl/runtime/k8s_driver.py) |
| Warm pool bookkeeping + refill loop | [src/sandbox_ctl/pool/](src/sandbox_ctl/pool/) |
| Snapshot store client, checkpointer, restorer | [src/sandbox_ctl/snapshot/](src/sandbox_ctl/snapshot/) |
| Session state machine, registry, quotas | [src/sandbox_ctl/session/](src/sandbox_ctl/session/) |
| Session Manager (end-to-end orchestration) | [src/sandbox_ctl/session/manager.py](src/sandbox_ctl/session/manager.py) |
| HTTP API (FastAPI) + health + session routes | [src/sandbox_ctl/api/](src/sandbox_ctl/api/) |
| Debug: per-session timeline, cgroup/proc introspect, profiler | [src/sandbox_ctl/debug/](src/sandbox_ctl/debug/) |
| 90 unit tests + 14 e2e tests (in-process, with fakes) | [tests/](tests/) |
| Helm chart (dev + prod values) | [deploy/helm/sandbox-ctl/](deploy/helm/sandbox-ctl/) |
| Dockerfile + Makefile | repo root |

### ⚠️ Stubbed — present as typed interface, implementation deferred

| Thing | Where | What's needed |
|---|---|---|
| `AsyncAgentClient.run` (gRPC to in-sandbox agent) | [src/sandbox_ctl/runtime/agent_client.py](src/sandbox_ctl/runtime/agent_client.py) | Generate stubs from the agent's `.proto` and inject a stub factory. Protocol is agent-repo's call. |
| Checkpoint "upload payload" callable | [src/sandbox_ctl/snapshot/checkpointer.py](src/sandbox_ctl/snapshot/checkpointer.py) | The actual pause + bytes-to-object-store step; runtime-specific. |
| Production auth verifier | [src/sandbox_ctl/api/auth.py](src/sandbox_ctl/api/auth.py) | JWT/OIDC verifier against your IdP. Only `DevHeaderAuth` ships. |
| Egress-proxy control endpoint | [src/sandbox_ctl/network/egress_proxy.py](src/sandbox_ctl/network/egress_proxy.py) | Client is wired; the server is a separate component. |

### ❌ Not in this repo (and never intended to be)

Per DESIGN.md §1 and §3:

| Component | Why it's out |
|---|---|
| **In-sandbox agent binary** | Separate repo, likely Rust/Go/C. Lives inside the sandbox image. |
| **Firecracker / Kata runtime** | Node-level infra. Installed via upstream Kata, outside the chart. |
| **Node provisioning / autoscaler config** | Cluster-level infra. |
| **Object storage for snapshots** | Operator-provided (S3, GCS, MinIO). |
| **The LLM / agent that generates the code** | Explicit non-goal (DESIGN §1). |
| **Developer IDE / UI** | Explicit non-goal (DESIGN §1). |
| **Multi-region orchestration** | Explicit non-goal (DESIGN §1). |

---

## 4. "How do I actually run code with this?"

Three paths, from least to most work.

### Path A — Run the tests. See orchestration work end-to-end against fakes.

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
pytest
```

The e2e suite in [tests/e2e/](tests/e2e/) exercises `POST /sessions/run`
through the real HTTP surface, with a `FakeDriver` and `FakeAgent`
standing in for the cluster and the sandbox agent.

### Path B — Local Docker backend. Round-trip real code without a cluster.

```bash
cp .env.example .env
head -c 64 /dev/urandom > .venv/signing.key
export RUNTIME_BACKEND=docker
export CREDS_SIGNING_KEY_PATH=$PWD/.venv/signing.key
uvicorn sandbox_ctl.api.app:create_app --factory --port 8080
```

The control plane creates sandbox containers on the local Docker daemon
via [docker_driver.py](src/sandbox_ctl/runtime/docker_driver.py) and
executes code via `docker exec` in
[docker_agent.py](src/sandbox_ctl/runtime/docker_agent.py). Same
Session Manager, quotas, registry, warm pool, HTTP routes as prod — only
the driver and agent change. Isolation is container-grade, not
microVM-grade: dev clusters only.

### Path C — The design, for real.

What the system actually needs to execute untrusted code safely:

1. Install the Kata runtime handler on your sandbox nodes (upstream Kata
   docs). Nodes need `/dev/kvm`.
2. Build the sandbox base image: a tiny guest rootfs with an agent
   binary that serves a gRPC `Run` RPC.
3. Define a `.proto` for the agent protocol, generate Python stubs,
   wire them into `AsyncAgentClient`.
4. Deploy the Helm chart to the cluster, with
   `RUNTIME_CLASS_MVM=kata-mvm` and nodes tainted `role=sandbox`.
5. Verify the sandbox Pod comes up on a Kata handler, the agent is
   reachable, and `POST /sessions/run` returns a result.

This is weeks of work and spans multiple repos. The point of the split
is that each piece evolves on its own cadence.

---

## 5. Quick commands

```bash
# install
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e .

# tests
pytest                        # all 104 pass
pytest tests/unit             # 90 unit tests, no cluster
pytest tests/e2e -m e2e       # 14 in-process e2e tests

# quality gates
ruff check src tests
ruff format --check src tests
mypy src                      # strict, zero errors

# run the API locally (health only without a wired agent)
cp .env.example .env
head -c 64 /dev/urandom > .venv/signing.key
export CREDS_SIGNING_KEY_PATH=.venv/signing.key
export KUBE_IN_CLUSTER=false
uvicorn sandbox_ctl.api.app:create_app --factory --port 8080
curl http://localhost:8080/healthz
```

---

## 6. The one-sentence summary

**`sandbox-ctl` today is a production-grade control plane that runs
end-to-end on a laptop with `RUNTIME_BACKEND=docker` (sandbox =
container, executor = `docker exec`) and ships the right Kubernetes
primitives for the production microVM path with
`RUNTIME_BACKEND=kubernetes` — the in-sandbox agent and
Kata/Firecracker runtime still live outside this repo and must be
installed separately before the production tier does useful work
end-to-end.**
