# AGENTS.md

Operating guide for AI coding agents working in this repository.

## Role

You are a **Python developer**. Write idiomatic, production-grade Python. Prefer the standard library and well-maintained packages. Target Python 3.11+ unless the project pins otherwise.

## Core Principles

### 1. Single Responsibility per File
- Each file has **one purpose**. Do not bundle unrelated concerns.
- If a file starts doing two things, split it.
- Module names should describe that single purpose (e.g. `http_client.py`, not `utils.py`).

### 2. Simple Classes, Simple Methods
- One class per file when the class is the file's purpose.
- Methods stay short: one responsibility, few parameters, clear return type.
- Prefer composition over inheritance. Avoid deep hierarchies and metaclasses.
- Type-annotate every public function and method.
- No clever one-liners when a clear block will do.

### 3. Configuration via `.env`

- **Never hardcode** API keys, URLs, timeouts, retry counts, model names, limits, feature flags, or any tunable value.
- All runtime configuration comes from environment variables, loaded from a `.env` file at startup.
- Use `python-dotenv` to load, and a single `config.py` module to read and validate.
- Fail fast at startup if a required variable is missing — raise with a clear message naming the missing var.
- Config values are parsed and typed in `config.py` (e.g. `TIMEOUT: int`, `MAX_RETRIES: int`), not re-parsed at each call site.
- **Never commit `.env` itself** — it goes in `.gitignore`.

#### `.env.example` rules

`.env.example` is the committed template. It is the operator's reference and the source of truth for *which* variables exist. The rules:

1. **One row per variable in `DESIGN.md` §7.** If a variable is in §7, it is in `.env.example`. If it is in `.env.example`, it is in §7. These two must never disagree.
2. **Order and group** `.env.example` to match `DESIGN.md` §7's groupings (service, http, runtime, pool, snapshot, session, tenant, egress, creds, telemetry, logging, kubernetes…). Use a comment header for each group.
3. **Every variable gets a short comment above it** stating what it does and its unit (seconds, MB, ratio, bool).
4. **Values are safe placeholders, never real credentials or private endpoints.**
   - Secrets: `change-me` or `<set-in-prod>` — never a plausible-looking fake that could be mistaken for real.
   - URLs: `http://localhost:<port>` for things that run locally in dev; `<set-in-prod>` for things that only exist in prod.
   - Numeric defaults: use the same default as `DESIGN.md` §7 so a fresh copy of `.env` works out of the box.
   - Booleans: `true` or `false`, lowercase.
   - Paths: paths that exist in the repo's `deploy/` tree, or `<set-in-prod>` for host paths that only exist on a node.
5. **Required vs. optional.** If a variable has no default in §7, mark the line with `# REQUIRED` so an operator doing a diff spots it immediately.
6. **No secrets in example values.** Even if a value "looks safe," do not paste anything from a real `.env`. Review the file before committing.
7. **Changes are atomic.** A PR that adds, removes, or renames a config variable updates `config.py`, `.env.example`, **and** `DESIGN.md` §7 in the same commit. Tests should include one that asserts the three stay in sync (parse `.env.example`, parse §7, compare key sets).

#### Example shape (illustrative, not exhaustive)

```dotenv
# ─── Service ──────────────────────────────────────────────────────────
# Logical name used in logs and traces.
SERVICE_NAME=sandbox-ctl
# dev | staging | prod
SERVICE_ENV=dev

# ─── HTTP ─────────────────────────────────────────────────────────────
HTTP_HOST=0.0.0.0
HTTP_PORT=8080
# Max wall time for any single API request, seconds.
HTTP_REQUEST_TIMEOUT_S=30

# ─── Kubernetes ───────────────────────────────────────────────────────
# true inside the cluster; false when using a local kubeconfig.
KUBE_IN_CLUSTER=true
KUBE_NAMESPACE=sandbox
# Only used when KUBE_IN_CLUSTER=false.
KUBE_KUBECONFIG_PATH=
RUNTIME_CLASS_MVM=kata-mvm
RUNTIME_CLASS_CTR=runc-hardened
SANDBOX_NODE_SELECTOR=role=sandbox
# REQUIRED when using private base images.
SANDBOX_IMAGE_PULL_SECRET=<set-in-prod>
WARM_POOL_PRIORITY_CLASS=warm-preemptible
ONDEMAND_PRIORITY_CLASS=sandbox-ondemand
POD_SECCOMP_PROFILE=sandbox/default.json

# ─── Snapshot store ───────────────────────────────────────────────────
# REQUIRED
SNAPSHOT_STORE_URL=<set-in-prod>
SNAPSHOT_STORE_BUCKET=sandbox-snapshots
SNAPSHOT_STORE_KEY_ID=change-me
SNAPSHOT_STORE_SECRET=change-me

# ─── Credentials ──────────────────────────────────────────────────────
# REQUIRED. Path to the signing key for short-lived session credentials.
CREDS_SIGNING_KEY_PATH=<set-in-prod>
CREDS_TTL_S=300

# ─── Telemetry & logging ──────────────────────────────────────────────
OTLP_ENDPOINT=http://otel-collector:4317
OTLP_SAMPLE_RATIO=0.1
METRICS_PORT=9090
LOG_LEVEL=INFO
LOG_FORMAT=json
```

The full list is whatever `DESIGN.md` §7 contains at the time of the change. When in doubt, treat §7 as authoritative and bring `.env.example` into alignment.

### 4. Tests Are Mandatory
- Every source file has corresponding tests. No file ships without them.
- **Unit tests**: `tests/unit/test_<module>.py` — fast, isolated, mock external I/O.
- **End-to-end tests**: `tests/e2e/test_<flow>.py` — exercise the full path against real or realistic dependencies.
- Framework: `pytest`. Use `pytest-mock` for mocks, `pytest-asyncio` for async code.
- **After any code change, the agent MUST run the full test suite** (`pytest`) and report results before declaring the task done. If tests fail, fix them before moving on.
- Aim for meaningful coverage of behavior, not line-count theatre. Each public method gets at least one happy-path and one failure-path test.
- Tests must be deterministic — no network flakiness, no time-of-day dependencies.

### 5. Follow `DESIGN.md`
- Before writing or changing code, read `DESIGN.md`.
- If `DESIGN.md` **does not exist**, create one. It describes:
  - Project purpose and scope (1–2 paragraphs).
  - Module layout: each file's name and single responsibility.
  - Data flow / sequence of the main operation.
  - External dependencies and why each is needed.
  - Configuration variables (mirrors `.env.example`).
  - Known trade-offs and rejected alternatives.
- When the design changes, update `DESIGN.md` in the **same change** that updates the code. Design drift is a bug.

### 6. Keep `README.txt` Current
- Maintain `README.txt` (plain text, not Markdown) with two clearly separated sections:
  - **Quick Start** — the minimum commands to install, configure, and run. Target a reader who wants it working in under 2 minutes.
  - **Detailed Guide** — environment setup, every config variable with meaning and default, how to run tests (unit + e2e), how to run the application, how to extend it, troubleshooting.
- Update `README.txt` in the same change that adds a new feature, config variable, or dependency.

### 7. Production Grade
Every change ships at production quality:

- **Logging**: Use the `logging` module. One `logger = logging.getLogger(__name__)` per file. No `print()` in library/application code. Log levels used correctly (DEBUG for diagnosis, INFO for lifecycle, WARNING for recoverable, ERROR for failures).
- **Error handling**: Catch narrowly. Never bare `except:`. Never `except Exception` without re-raising or logging with context. Raise domain-specific exceptions, not generic ones.
- **Validation**: Validate inputs at system boundaries (user input, env vars, external API responses). Trust internal calls.
- **Dependencies**: Pin versions in `requirements.txt` (or `pyproject.toml`). Separate `requirements-dev.txt` for test/lint tools.
- **Formatting & linting**: Code passes `ruff check` and `ruff format` (or `black` + `flake8` if the project uses those). Run before committing.
- **Type checking**: Code passes `mypy` in strict-ish mode on the application package.
- **No dead code**: Remove unused imports, variables, functions. Don't leave commented-out blocks.
- **No TODOs without an owner**: If you add a `TODO`, include a reason and the condition under which it's resolved.
- **Secrets**: Never log secrets. Never commit `.env`, credentials, tokens, or private keys.
- **Reproducibility**: `python -m venv .venv && pip install -r requirements.txt` on a clean machine must produce a working install.

## Standard Project Layout

```
.
├── AGENTS.md              # this file
├── DESIGN.md              # architecture and module responsibilities
├── README.txt             # quick start + detailed guide
├── .env.example           # every config var, placeholder values
├── .env                   # local only, gitignored
├── .gitignore
├── pyproject.toml         # or requirements.txt
├── requirements-dev.txt
├── src/
│   └── <package>/
│       ├── __init__.py
│       ├── config.py      # loads and validates env vars
│       ├── <feature>.py   # one responsibility per file
│       └── ...
└── tests/
    ├── unit/
    │   └── test_<module>.py
    └── e2e/
        └── test_<flow>.py
```

## Workflow for Any Change

1. Read `DESIGN.md` (create it if missing) and the files you will touch.
2. If adding config, update `.env.example` and `config.py`.
3. Make the smallest change that solves the task. One file = one purpose.
4. Add or update unit tests for every touched module.
5. Add or update an e2e test when behavior visible to the user changes.
6. Run `pytest` — all tests must pass.
7. Run `ruff check`, `ruff format --check`, and `mypy` — all clean.
8. Update `DESIGN.md` if structure changed.
9. Update `README.txt` if setup, config, or usage changed.
10. Report what changed, which tests ran, and the result.

## What NOT to Do

- Don't create `utils.py` or `helpers.py` grab-bags.
- Don't hardcode any value that a user or operator might reasonably want to change.
- Don't skip tests "because the change is small".
- Don't catch exceptions you can't meaningfully handle.
- Don't add dependencies without recording them and justifying them in `DESIGN.md`.
- Don't commit without the tests passing.
- Don't modify `.env` in commits. Don't ever print or log its contents.
