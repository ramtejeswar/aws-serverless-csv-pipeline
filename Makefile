# Common tasks. Run `make` or `make help` to list them.
TF  := terraform -chdir=infra
PY  := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.DEFAULT_GOAL := help
.PHONY: help install test fmt validate plan deploy smoke destroy

help: ## List available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install: ## Create .venv and install test dependencies
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements-dev.txt

test: ## Run unit tests (no AWS account needed)
	PYTHONDONTWRITEBYTECODE=1 $(PY) -m pytest

fmt: ## Format Terraform files
	terraform fmt -recursive infra

validate: ## Check Terraform formatting and configuration
	terraform fmt -check -recursive infra
	$(TF) init -backend=false -input=false >/dev/null
	$(TF) validate

plan: ## Show what a deploy would change
	$(TF) init -input=false >/dev/null
	$(TF) plan

deploy: test ## Run tests, then deploy to AWS
	$(TF) init -input=false >/dev/null
	$(TF) apply

smoke: ## End-to-end test against the deployed API
	./scripts/smoke_test.sh "$$($(TF) output -raw api_url)"

destroy: ## Delete everything this project created in AWS
	$(TF) destroy
