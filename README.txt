sandbox-ctl
===========

Kubernetes-native control plane that runs untrusted, model-generated code
inside isolated, short-lived sandboxes. See README.md for the long form;
this file is the plain-text version AGENTS.md asks every repo to carry.


QUICK START
-----------

Three supported paths. All use the same image, HTTP API, and code
paths above the Driver + Agent layer. RUNTIME_BACKEND plus the chosen
AgentClient pick which one; isolation strength is the only axis that
really differs.

  - Laptop   — RUNTIME_BACKEND=docker. Sandboxes are containers on the
               local Docker daemon, executor is `docker exec`. Shared
               kernel; never real tenant workloads.
  - Dev K8s  — RUNTIME_BACKEND=kubernetes on minikube / kind.
               Sandboxes are Pods with Pod-level hardening + default-
               deny NetworkPolicy; executor is the K8s exec stream
               (`KubeExecAgent`). No microVM.
  - Prod     — RUNTIME_BACKEND=kubernetes on a Kata cluster. Same
               chart, swap in the in-sandbox gRPC agent and
               kata-mvm RuntimeClass. The agent binary and Kata
               runtime live outside this repo (STATUS.md §4 path C).

Pick the matching numbered section below:

  §1.  LOCAL DEPLOY & TEST         — Docker only, no cluster.
  §2a. DEV K8S (MINIKUBE/KIND)     — chart with the kube-exec agent.
  §2b. PRODUCTION CLUSTER          — same chart against prod.


§1. LOCAL DEPLOY & TEST
-----------------------

Goal: full submit → run → return loop on a laptop, no cluster. Isolation
is laptop-grade (shared kernel, Docker-hardened container) — fine for
development, never for real tenant workloads.

Prereqs
    Python 3.11+, Docker Desktop (or an equivalent local daemon) running.

Step 1 — Install.
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-dev.txt
    pip install -e .

Step 2 — Configure for the Docker backend.
    cp .env.example .env
    head -c 64 /dev/urandom > .venv/signing.key
    # Edit the three lines that matter for local:
    #   RUNTIME_BACKEND=docker
    #   CREDS_SIGNING_KEY_PATH=./.venv/signing.key
    #   KUBE_IN_CLUSTER=false
    # Everything else in .env can keep its placeholder; the Docker
    # backend ignores KUBE_*, RUNTIME_API_URL, and AGENT_GRPC_ENDPOINT.

Step 3 — Optional: isolate egress with a dedicated Docker network.
    docker network create --internal sandbox-net
    # then in .env:  DOCKER_NETWORK=sandbox-net

Step 4 — Pre-pull the sandbox image your flavor uses.
    docker pull python:3.11-slim

Step 5 — Run the control plane.
    # sandbox_ctl.boot:build_app wires the full AppContext (driver, pool,
    # manager, auth, …). The health-only factory in sandbox_ctl.api.app
    # is reserved for tests.
    uvicorn sandbox_ctl.boot:build_app --factory --port 8080

Step 6 — Smoke-test the API.
    curl -s http://localhost:8080/healthz
    # => {"status":"ok"}

Step 7 — Submit a run.
    curl -s http://localhost:8080/sessions/run \
      -H 'content-type: application/json' \
      -H 'x-tenant-id: demo' \
      -d '{"language":"python","code":"print(sum(range(10)))","timeout_s":5}'
    # => {"session_id":"s_...", "exit_code":0, "stdout":"45\n", ...}

Step 8 — Verify what the control plane did against Docker.
    docker ps -a --filter label=app=sandbox
    # Should list the (now-destroyed) sandbox container. Live containers
    # appear mid-run; `sandbox_ctl` destroys them on teardown.

Step 9 — Test suite.
    pytest tests/unit      # 100+ unit tests, <20s.
    pytest tests/e2e       # Full lifecycle through HTTP with fakes.
    pytest                 # Everything, ~15s.

Step 10 — Clean up.
    # Stop uvicorn with Ctrl-C.
    # Remove any sandbox containers left behind by a crashed run:
    docker ps -a --filter label=app=sandbox -q | xargs -r docker rm -f
    docker network rm sandbox-net   # if you created one.

Troubleshooting §1 specifics:
    - "docker run failed: image not found": `docker pull` the flavor
      image on your daemon.
    - "Cannot connect to the Docker daemon": start Docker Desktop.
    - "required env var ...": a REQUIRED var is still unset. In local
      mode, only CREDS_SIGNING_KEY_PATH must point at a real file; the
      others accept their `<set-in-prod>` placeholders.
    - `/sessions/run` returns 401 `X-Tenant-Id header required in dev
      auth`: the DevHeaderAuth stub needs `-H 'x-tenant-id: demo'` on
      every request. Any string works; it refuses to start in prod.
    - `/sessions/run` returns 404 while `/healthz` works: either the
      local uvicorn booted without an AppContext (use
      sandbox_ctl.boot:build_app, not sandbox_ctl.api.app:create_app),
      or port 8080 is already held by a `kubectl port-forward` to the
      in-cluster Pod — that Pod runs health-only (§2a) so it has no
      `/sessions/run`. Tell them apart:
          lsof -nP -iTCP:8080 -sTCP:LISTEN
          # uvicorn → your local API; kubectl → the port-forward.
          # "Handling connection for 8080" on your terminal means
          # kubectl port-forward is still running.
      Stop the port-forward (Ctrl-C) or run uvicorn on another port
      (`--port 8181`) and curl that.


§2. PRODUCTION DEPLOY & TEST
----------------------------

Goal: exercise the full chart against a real Kubernetes API.
§2a covers minikube/kind with the kube-exec agent (dev-grade
isolation, container tier only). §2b is the same chart against a
Kata-enabled cluster, with the gRPC agent in place of the kube-exec
one — the real microVM path.

Prereqs
    Python 3.11+, Docker, kubectl, helm. For §2a: minikube (preferred)
    or kind. For §2b: a cluster with Kata installed on sandbox nodes
    and the in-sandbox agent image published.

§2a — Dev cluster (minikube/kind)
.................................

Step 1 — Start minikube with a CNI that enforces NetworkPolicy.
    minikube start --cni=calico
    minikube addons enable metrics-server

Step 2 — Build and load the control-plane image into the cluster.
    # The name must match values-dev.yaml's image.repository:tag
    # (sandbox-ctl:dev). The chart sets pullPolicy=Never in dev, so a
    # name mismatch surfaces as ErrImageNeverPull on the Pod.
    docker build -t sandbox-ctl:dev .
    minikube image load sandbox-ctl:dev
    # Pre-load the sandbox flavor image so the sandbox Pod starts without
    # waiting on a registry pull. The chart sets
    # imagePullPolicy: IfNotPresent on sandbox Pods, so the local image
    # is used when it's already on the node.
    docker pull python:3.11-slim
    minikube image load python:3.11-slim

Step 3 — Preflight (CNI + metrics-server). Refuses to proceed otherwise.
    make dev-preflight

Step 4 — Install the chart with dev values.
    helm upgrade --install sandbox-ctl deploy/helm/sandbox-ctl \
      -f deploy/helm/sandbox-ctl/values-dev.yaml \
      -n sandbox --create-namespace

Step 5 — Verify the control plane is healthy in-cluster.
    kubectl -n sandbox rollout status deploy/sandbox-api
    kubectl -n sandbox port-forward svc/sandbox-api 8080:8080 &
    curl -s http://localhost:8080/healthz
    curl -s http://localhost:8080/readyz

Step 6 — Submit a run against the cluster.
    curl -s http://localhost:8080/sessions/run \
      -H 'content-type: application/json' \
      -H 'x-tenant-id: demo' \
      -d '{"language":"python","code":"print(1+1)","timeout_s":5}'

Step 7 — Watch what got created in the cluster.
    # Each /sessions/run creates one sandbox-<id> Pod, execs into it,
    # then deletes it. The Pod is usually gone before the response
    # lands, which is why --watch is the easiest way to see one.
    kubectl -n sandbox get pods -l app=sandbox --watch
    kubectl -n sandbox get networkpolicy
    kubectl -n sandbox get runtimeclass

Step 8 — Run the e2e suite against the cluster.
    # Point the suite at the real driver; the fakes are only used when
    # no cluster context is set. See tests/e2e/conftest.py.
    export E2E_TARGET=cluster
    export E2E_KUBECONFIG=$HOME/.kube/config
    pytest tests/e2e -m e2e

Step 9 — Tear down.
    helm -n sandbox uninstall sandbox-ctl
    kubectl delete ns sandbox
    minikube stop   # or `minikube delete` to wipe entirely.

Dev-cluster caveats (see DESIGN.md §14.11, §14.13):
    - Container tier only: /dev/kvm is not available inside the
      minikube VM on macOS, so the chart's values-dev.yaml leaves
      RUNTIME_CLASS_MVM unset and every flavor falls back to
      runc-hardened. Isolation is weaker than §2b.
    - NetworkPolicy enforcement depends on the CNI. kindnet (the kind
      default) does NOT enforce — use Calico or Cilium.

Troubleshooting §2a specifics:
    - "ErrImageNeverPull" on the sandbox-api Pod: the chart's
      image.repository:tag does not match what was loaded into
      minikube. values-dev.yaml pins repository=sandbox-ctl, tag=dev,
      pullPolicy=Never, so `docker build -t sandbox-ctl:dev .` and
      `minikube image load sandbox-ctl:dev` are what must line up.
      Verify with `minikube image ls | grep sandbox-ctl`.
    - "ImagePullBackOff" without touching values-dev.yaml: you
      probably dropped the pullPolicy override. Dev images aren't on
      any registry; keep pullPolicy=Never and pre-load them.
    - `minikube ssh -- docker images` fails with "Cannot connect to
      the Docker daemon": minikube's inner container runtime is
      containerd, not Docker. Use `minikube image ls` from the host,
      or `minikube ssh -- sudo crictl images` inside the node.
    - `kubectl logs` shows `required env var SNAPSHOT_STORE_KEY_ID
      is not set` (or similar): you're on a chart before the dev
      Secret was wired. Pull the latest chart; the snapshot
      credentials come from templates/snapshot-secret.yaml, driven
      by values-dev.yaml's snapshot.keyId / snapshot.secret.
    - `POST /sessions/run` returns 404 from the port-forwarded Pod:
      the Pod booted health-only. That happens when the backend's
      cold-spec factory couldn't be assembled. Grep the Pod log:
          kubectl -n sandbox logs -l app=sandbox-api \
            | grep "serving health routes only"
      With the current chart the in-cluster path IS wired (sandbox
      Pods via KubeExecAgent); if you still see the degrade line,
      it's usually a missing env var or a misconfigured value, and
      the warning line prints the exact BootError that caused it.
    - Sandbox Pod stuck in Pending or ErrImagePull on the flavor
      image: pre-load it into the node store.
          docker pull python:3.11-slim
          minikube image load python:3.11-slim
      Image pulls are done by kubelet on the node, not by the Pod,
      so this is about reliability on slow or airgapped setups —
      NetworkPolicy does not gate image pulls.
    - API returns `{"detail":"runtime error"}` (HTTP 502) and the
      sandbox-api log shows `DriverError: create failed:
      Unprocessable Entity` with `Pod "sandbox-s_..." is invalid:
      metadata.name`: the session id has `_` in it and your build
      predates the RFC 1123 Pod-name sanitizer. Rebuild and reroll:
          docker build -t sandbox-ctl:dev .
          minikube image load sandbox-ctl:dev
          kubectl -n sandbox rollout restart deploy/sandbox-api
    - "Handling connection for 8080" appears on your terminal when
      you curl: that message is from `kubectl port-forward`. If you
      also started a local uvicorn on 8080, the port-forward wins
      (it bound first) and your curl hits the health-only Pod, not
      your laptop. Run uvicorn on another port or stop the
      port-forward.

§2b — Staging / production cluster
..................................

Step 1 — One-time cluster prerequisites (owned by platform, not this
         repo):
    - Install the Kata runtime handler on nodes labeled role=sandbox.
    - Taint sandbox nodes: role=sandbox:NoSchedule.
    - Create the sandbox base image(s) with the in-sandbox agent built
      in; push to your registry.
    - Create an ImagePullSecret in the sandbox namespace and set
      SANDBOX_IMAGE_PULL_SECRET.
    - Provision the snapshot object store (S3/GCS/MinIO) and fill
      SNAPSHOT_STORE_* in values-prod.yaml.
    - Wire a real auth verifier (JWT/OIDC) in place of DevHeaderAuth;
      the shipped auth refuses to start when SERVICE_ENV=prod.

Step 2 — Build the control-plane image and push to your registry.
    docker build -t <registry>/sandbox-ctl:<version> .
    docker push <registry>/sandbox-ctl:<version>

Step 3 — Populate values-prod.yaml. Override at minimum:
    image.repository, image.tag
    serviceEnv (prod)
    runtimeBackend (kubernetes)
    runtimeClassMvm (kata-mvm)
    snapshotStore.* (URL, bucket, credentials via Secret)
    credsSigningKeyPath (mount from a KMS-projected Secret)
    otlpEndpoint, metricsPort
    hpa.* and resources.* per your capacity plan

Step 4 — Deploy with rolling update (maxSurge=1, maxUnavailable=0).
    helm upgrade --install sandbox-ctl deploy/helm/sandbox-ctl \
      -f deploy/helm/sandbox-ctl/values-prod.yaml \
      -n sandbox --create-namespace --atomic --wait

Step 5 — Verify rollout and in-cluster health.
    kubectl -n sandbox rollout status deploy/sandbox-api
    kubectl -n sandbox rollout status deploy/sandbox-pool
    kubectl -n sandbox get pods
    kubectl -n sandbox port-forward svc/sandbox-api 8080:8080 &
    curl -s http://localhost:8080/readyz

Step 6 — Sanity-run through the production API. Use your real auth
         header, not x-tenant-id.
    curl -sS https://<your-api-host>/sessions/run \
      -H "authorization: Bearer <token>" \
      -H 'content-type: application/json' \
      -d '{"language":"python","code":"print(1)","timeout_s":5}'

Step 7 — Confirm the sandbox landed on a Kata node and respected the
         isolation primitives.
    kubectl -n sandbox get pods -l app=sandbox \
      -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.runtimeClassName}{"\n"}{end}'
    # Each line should show `kata-mvm`.
    kubectl -n sandbox get networkpolicy
    kubectl -n sandbox describe pod <one-sandbox> | \
      grep -E 'Seccomp|Capabilities|ReadOnlyRootFilesystem'

Step 8 — Run the production-parity e2e suite.
    # The parity suite re-runs lifecycle, isolation, egress-deny, and
    # credential-scope e2e tests against the staging/prod cluster on
    # every release candidate. See DESIGN.md §14.13.
    export E2E_TARGET=cluster
    export E2E_KUBECONFIG=<kubeconfig>
    pytest tests/e2e -m e2e -k "lifecycle or isolation or egress or credentials"

Step 9 — Observability spot-checks.
    - Grafana dashboard: deploy/dashboards/sandbox-overview.json loaded?
    - OTLP traces for `acquire → apply_isolation → mint_creds → exec →
      teardown` showing up on the collector?
    - Prometheus metrics (cold-start seconds, warm-start seconds, pool
      occupancy, egress denies per tenant) populating?

Step 10 — Roll back cleanly if needed.
    helm -n sandbox rollback sandbox-ctl <previous-revision>

Prod operational notes:
    - Never run RUNTIME_BACKEND=docker against shared infrastructure.
      The config validator does not block this — policy does.
    - PriorityClasses: cluster services > on-demand sandbox > warm pool
      (preemptible). Verify warm Pods actually get preempted under load
      before declaring capacity.
    - Rolling base images: bump the flavor tag, let sandbox-pool drain
      old warm Pods for that flavor, and canary one tenant first
      (DESIGN.md §14.8).


DETAILED GUIDE
--------------

What this is
    A Python control plane. It exposes an HTTP API, assembles Kubernetes
    Pod specs that pin seccomp + read-only root + drop-all caps + default-
    deny egress, submits them, watches them, collects their output, and
    tears them down. Isolation is enforced by Kubernetes and a RuntimeClass
    (Kata for microVMs; runc for the hardened container tier).

Design
    See DESIGN.md. §4 lists every module's single responsibility. §7 is
    the authoritative config list; .env.example mirrors it and a sync test
    (tests/unit/test_env_sync.py) fails CI if they drift.

Configuration
    Every tunable value is an env var, loaded by src/sandbox_ctl/config.py.
    Nothing else in the code reads os.environ. Each variable, its default
    and its meaning:

      SERVICE_NAME            Logical name used in logs and traces.
      SERVICE_ENV             dev | staging | prod.
      HTTP_HOST, HTTP_PORT    Bind address and port for the API.
      HTTP_REQUEST_TIMEOUT_S  Max wall time for any single request.
      RUNTIME_BACKEND         kubernetes (prod) | docker (local dev).
                              Picks the Driver + AgentClient pair.
      RUNTIME_DRIVER          firecracker | container. K8s isolation tier;
                              ignored by the docker backend.
      RUNTIME_API_URL         Base URL of the runtime driver. REQUIRED.
                              Read only by the kubernetes backend.
      AGENT_GRPC_ENDPOINT     How the control plane reaches the in-sandbox
                              agent. REQUIRED. Ignored by the docker
                              backend, which uses `docker exec`.
      AGENT_TIMEOUT_S         Timeout for a single agent RPC.
      DOCKER_NETWORK          Optional Docker network for sandbox
                              containers. Empty = default bridge.
      WARM_POOL_SIZE          Pre-booted sandboxes per flavor.
      WARM_POOL_MAX_IDLE_S    Max age of an unused warm sandbox.
      WARM_POOL_REFILL_CONCURRENCY  Parallel boots during refill.
      SNAPSHOT_STORE_URL      Object store base URL. REQUIRED.
      SNAPSHOT_STORE_BUCKET   Bucket / container name. REQUIRED.
      SNAPSHOT_STORE_KEY_ID   Access key id. REQUIRED.
      SNAPSHOT_STORE_SECRET   Access secret. REQUIRED, never logged.
      SESSION_MAX_WALL_S      Hard cap on session wall time.
      SESSION_MAX_CPU_MS      Hard cap on CPU time.
      SESSION_MAX_MEMORY_MB   Memory ceiling.
      SESSION_MAX_PIDS        PID limit inside the sandbox.
      SESSION_SCRATCH_MB      Writable scratch size.
      TENANT_MAX_CONCURRENT   Concurrent sessions per tenant.
      TENANT_QUOTA_RPS        Session creations per second per tenant.
      EGRESS_DEFAULT_POLICY   deny (default) | allow (dev-only).
      EGRESS_ALLOWLIST_PATH   Path to the allowlist YAML.
      CREDS_SIGNING_KEY_PATH  Path to the signing key. REQUIRED.
      CREDS_TTL_S             Lifetime of minted credentials.
      OTLP_ENDPOINT           OTLP collector URL. Empty disables export.
      OTLP_SAMPLE_RATIO       Trace sampling, 0.0..1.0.
      METRICS_PORT            Prometheus scrape port.
      LOG_LEVEL               Root log level.
      LOG_FORMAT              json | text.
      KUBE_IN_CLUSTER         true inside the cluster; false otherwise.
      KUBE_NAMESPACE          Namespace for sandbox Pods.
      KUBE_KUBECONFIG_PATH    Only when KUBE_IN_CLUSTER=false.
      RUNTIME_CLASS_MVM       RuntimeClass for microVM tier.
      RUNTIME_CLASS_CTR       RuntimeClass for the container tier.
      SANDBOX_NODE_SELECTOR   Label selector for sandbox nodes.
      SANDBOX_IMAGE_PULL_SECRET  ImagePullSecret. REQUIRED in prod.
      WARM_POOL_PRIORITY_CLASS   Preempted by on-demand sessions.
      ONDEMAND_PRIORITY_CLASS    Normal priority for leased sessions.
      POD_SECCOMP_PROFILE     Localhost seccomp profile path.

Testing
    pytest tests/unit     fast, no cluster.
    pytest tests/e2e      end-to-end against in-process fakes; the same
                          tests point at a real cluster when
                          sandbox_ctl.runtime.k8s_driver.K8sDriver and the
                          real gRPC agent client are wired in.
    pytest                everything.
    make lint             ruff check + ruff format --check.
    make type             mypy strict against src.

Running the service
    - Local Docker backend (no cluster needed):
          export RUNTIME_BACKEND=docker
          export CREDS_SIGNING_KEY_PATH=$PWD/.venv/signing.key
          uvicorn sandbox_ctl.boot:build_app --factory --port 8080
      Sandboxes become containers on the local Docker daemon; code is
      executed via `docker exec`. Isolation is weaker (shared kernel);
      the dev backend never runs real tenant workloads.
    - Outside a cluster, against a kubeconfig:
          export RUNTIME_BACKEND=kubernetes
          export KUBE_IN_CLUSTER=false
          export KUBE_KUBECONFIG_PATH=$HOME/.kube/config
          uvicorn sandbox_ctl.boot:build_app --factory --port 8080
      (The full K8s cold-Pod-spec factory is not wired yet — see
       STATUS.md. `build_app` refuses to start under RUNTIME_BACKEND=
       kubernetes until it is.)
    - In-cluster, via the Helm chart:
          helm upgrade --install sandbox-ctl deploy/helm/sandbox-ctl \
            -f deploy/helm/sandbox-ctl/values-dev.yaml \
            -n sandbox --create-namespace

Extending it
    One file, one purpose. Add a new module per the layout in
    DESIGN.md §4. Every new file ships with its own
    tests/unit/test_<module>.py. Config changes update config.py,
    .env.example, and DESIGN.md §7 in the same commit.

Troubleshooting
    - "required env var X is not set": the service refuses to start with
      a missing REQUIRED variable. Check .env against .env.example.
    - "pod not Ready after N s": the control plane waits up to
      SESSION_MAX_WALL_S for a sandbox to become Ready; past that it
      destroys the pod and surfaces a DriverError.
    - Egress unexpectedly works: the CNI isn't enforcing NetworkPolicy.
      Run `make dev-preflight` on your cluster.
    - "AsyncAgentClient requires generated gRPC stubs": you are on the
      kubernetes backend and the default agent client is a placeholder.
      Either wire in the real gRPC stubs, or switch to the Docker
      backend for local iteration: `export RUNTIME_BACKEND=docker`.
    - "docker run failed" on the local backend: the Docker daemon is not
      reachable, or the base image is not pullable. Check `docker ps`
      first; then verify the flavor image exists on your daemon.
