SHELL := /bin/bash

CENTAUR_NAMESPACE ?= centaur
CENTAUR_RELEASE ?= centaur
CENTAUR_CHART ?= contrib/chart
CENTAUR_API_IMAGE_REPOSITORY ?= centaur-api-tavus
CENTAUR_SANDBOX_IMAGE_REPOSITORY ?= centaur-agent-tavus
CENTAUR_K3S_CTR ?= sudo k3s ctr

.PHONY: deploy

deploy:
	set -euo pipefail; \
	SHA="$$(git rev-parse --short HEAD)"; \
	API_IMAGE="$(CENTAUR_API_IMAGE_REPOSITORY):fork-$${SHA}"; \
	SANDBOX_IMAGE="$(CENTAUR_SANDBOX_IMAGE_REPOSITORY):fork-$${SHA}"; \
	echo "Building $${API_IMAGE}"; \
	docker build -t "$${API_IMAGE}" -f services/api/Dockerfile .; \
	echo "Building $${SANDBOX_IMAGE}"; \
	docker build --target sandbox -t "$${SANDBOX_IMAGE}" -f services/sandbox/Dockerfile .; \
	echo "Importing images into k3s"; \
	docker save "$${API_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	docker save "$${SANDBOX_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	helm dependency update "$(CENTAUR_CHART)" >/dev/null; \
	helm upgrade "$(CENTAUR_RELEASE)" "$(CENTAUR_CHART)" -n "$(CENTAUR_NAMESPACE)" --reuse-values \
	  --set api.image.repository="$(CENTAUR_API_IMAGE_REPOSITORY)" \
	  --set api.image.tag="fork-$${SHA}" \
	  --set api.image.pullPolicy=IfNotPresent \
	  --set sandbox.image.repository="$(CENTAUR_SANDBOX_IMAGE_REPOSITORY)" \
	  --set sandbox.image.tag="fork-$${SHA}" \
	  --set sandbox.image.pullPolicy=IfNotPresent; \
	kubectl -n "$(CENTAUR_NAMESPACE)" rollout status "deploy/$(CENTAUR_RELEASE)-centaur-api" --timeout=180s; \
	kubectl -n "$(CENTAUR_NAMESPACE)" get deploy "$(CENTAUR_RELEASE)-centaur-api" \
	  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'; \
	kubectl -n "$(CENTAUR_NAMESPACE)" get deploy "$(CENTAUR_RELEASE)-centaur-api" \
	  -o jsonpath='{range .spec.template.spec.containers[0].env[?(@.name=="AGENT_IMAGE")]}{.value}{"\n"}{end}'
