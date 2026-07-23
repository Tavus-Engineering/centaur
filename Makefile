SHELL := /bin/bash

CENTAUR_NAMESPACE ?= centaur
CENTAUR_RELEASE ?= centaur
CENTAUR_CHART ?= contrib/chart
CENTAUR_API_IMAGE_REPOSITORY ?= centaur-api-tavus
CENTAUR_SANDBOX_IMAGE_REPOSITORY ?= centaur-agent-tavus
CENTAUR_SLACKBOTV2_IMAGE_REPOSITORY ?= centaur-slackbotv2-tavus
CENTAUR_K3S_CTR ?= sudo k3s ctr
CENTAUR_API_DEPLOYMENT ?= $(CENTAUR_RELEASE)-centaur-api-rs

.PHONY: deploy

deploy:
	set -euo pipefail; \
	SHA="$$(git rev-parse --short HEAD)"; \
	API_IMAGE="$(CENTAUR_API_IMAGE_REPOSITORY):fork-$${SHA}"; \
	SANDBOX_IMAGE="$(CENTAUR_SANDBOX_IMAGE_REPOSITORY):fork-$${SHA}"; \
	SLACKBOTV2_IMAGE="$(CENTAUR_SLACKBOTV2_IMAGE_REPOSITORY):fork-$${SHA}"; \
	echo "Building $${API_IMAGE}"; \
	docker build -t "$${API_IMAGE}" -f services/api-rs/Dockerfile .; \
	echo "Building $${SANDBOX_IMAGE}"; \
	docker build --target sandbox -t "$${SANDBOX_IMAGE}" -f services/sandbox/Dockerfile .; \
	echo "Building $${SLACKBOTV2_IMAGE}"; \
	docker build -t "$${SLACKBOTV2_IMAGE}" -f services/slackbotv2/Dockerfile .; \
	echo "Importing images into k3s"; \
	docker save "$${API_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	docker save "$${SANDBOX_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	docker save "$${SLACKBOTV2_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	helm dependency update "$(CENTAUR_CHART)" >/dev/null; \
	kubectl apply -f "$(CENTAUR_CHART)/charts/agent-sandbox/crds" >/dev/null; \
	helm upgrade "$(CENTAUR_RELEASE)" "$(CENTAUR_CHART)" -n "$(CENTAUR_NAMESPACE)" --reset-then-reuse-values \
	  --set apiRs.image.repository="$(CENTAUR_API_IMAGE_REPOSITORY)" \
	  --set apiRs.image.tag="fork-$${SHA}" \
	  --set apiRs.image.pullPolicy=IfNotPresent \
	  --set apiRs.ironProxy.mode=disabled \
	  --set apiRs.syncInfraSecrets=false \
	  --set sandbox.image.repository="$(CENTAUR_SANDBOX_IMAGE_REPOSITORY)" \
	  --set sandbox.image.tag="fork-$${SHA}" \
	  --set sandbox.image.pullPolicy=IfNotPresent \
	  --set slackbotv2.image.repository="$(CENTAUR_SLACKBOTV2_IMAGE_REPOSITORY)" \
	  --set slackbotv2.image.tag="fork-$${SHA}" \
	  --set slackbotv2.image.pullPolicy=IfNotPresent; \
	kubectl -n "$(CENTAUR_NAMESPACE)" rollout status "deploy/$(CENTAUR_API_DEPLOYMENT)" --timeout=180s; \
	kubectl -n "$(CENTAUR_NAMESPACE)" get deploy "$(CENTAUR_API_DEPLOYMENT)" \
	  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'; \
	kubectl -n "$(CENTAUR_NAMESPACE)" get deploy "$(CENTAUR_API_DEPLOYMENT)" \
	  -o jsonpath='{range .spec.template.spec.containers[0].env[?(@.name=="AGENT_IMAGE")]}{.value}{"\n"}{end}'
