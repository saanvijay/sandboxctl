.PHONY: venv install lint fmt type test test-unit test-e2e dev dev-preflight clean

PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(BIN)/pip install -U pip
	$(BIN)/pip install -r requirements-dev.txt
	$(BIN)/pip install -e .

lint:
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests

fmt:
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

type:
	$(BIN)/mypy src

test: test-unit

test-unit:
	$(BIN)/pytest tests/unit

test-e2e:
	$(BIN)/pytest tests/e2e -m e2e

dev-preflight:
	@echo "Checking minikube status, CNI, and metrics-server…"
	@minikube status >/dev/null || (echo "minikube not Running"; exit 1)
	@kubectl get apiservice v1beta1.metrics.k8s.io -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' | grep -q True \
		|| (echo "metrics-server not Available"; exit 1)
	@echo "preflight OK"

dev: dev-preflight
	helm upgrade --install sandbox-ctl deploy/helm/sandbox-ctl \
		-f deploy/helm/sandbox-ctl/values-dev.yaml \
		-n sandbox --create-namespace

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
