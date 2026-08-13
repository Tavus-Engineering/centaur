SHELL := /bin/bash

CENTAUR_NAMESPACE ?= centaur
CENTAUR_RELEASE ?= centaur
CENTAUR_CHART ?= contrib/chart
CENTAUR_API_IMAGE_REPOSITORY ?= centaur-api-tavus
CENTAUR_SANDBOX_IMAGE_REPOSITORY ?= centaur-agent-tavus
CENTAUR_SLACKBOTV2_IMAGE_REPOSITORY ?= centaur-slackbotv2-tavus
CENTAUR_CONSOLE_IMAGE_REPOSITORY ?= centaur-console-tavus
CENTAUR_IRON_PROXY_IMAGE_REPOSITORY ?= centaur-iron-proxy-tavus
CENTAUR_TOOLS_REPOSITORY ?= Tavus-Engineering/centaur
CENTAUR_K3S_CTR ?= sudo k3s ctr
CENTAUR_API_DEPLOYMENT ?= $(CENTAUR_RELEASE)-centaur-api-rs
CENTAUR_SLACKBOTV2_DEPLOYMENT ?= $(CENTAUR_RELEASE)-centaur-slackbotv2
CENTAUR_CONSOLE_DEPLOYMENT ?= $(CENTAUR_RELEASE)-centaur-console
CENTAUR_CONSOLE_WORKER_DEPLOYMENT ?= $(CENTAUR_RELEASE)-centaur-console-worker
CENTAUR_REPO_CACHE_DAEMONSET ?= $(CENTAUR_RELEASE)-centaur-repo-cache
CENTAUR_REQUIRED_INFRA_TOOLS ?= slack company_context

.PHONY: deploy

deploy:
	set -euo pipefail; \
	SHA="$$(git rev-parse --short HEAD)"; \
	FULL_SHA="$$(git rev-parse HEAD)"; \
	API_IMAGE="$(CENTAUR_API_IMAGE_REPOSITORY):fork-$${SHA}"; \
	SANDBOX_IMAGE="$(CENTAUR_SANDBOX_IMAGE_REPOSITORY):fork-$${SHA}"; \
	SLACKBOTV2_IMAGE="$(CENTAUR_SLACKBOTV2_IMAGE_REPOSITORY):fork-$${SHA}"; \
	CONSOLE_IMAGE="$(CENTAUR_CONSOLE_IMAGE_REPOSITORY):fork-$${SHA}"; \
	IRON_PROXY_IMAGE="$(CENTAUR_IRON_PROXY_IMAGE_REPOSITORY):fork-$${SHA}"; \
	CENTAUR_POSTGRES_DSN_B64="$$(kubectl -n "$(CENTAUR_NAMESPACE)" get secret centaur-infra-env \
	  -o 'jsonpath={.data.CENTAUR_POSTGRES_DSN}')"; \
	if [[ -z "$${CENTAUR_POSTGRES_DSN_B64}" ]]; then \
	  CENTAUR_POSTGRES_DSN_B64="$$(kubectl -n "$(CENTAUR_NAMESPACE)" get secret centaur-infra-env \
	    -o 'jsonpath={.data.DATABASE_URL}')"; \
	  if [[ -z "$${CENTAUR_POSTGRES_DSN_B64}" ]]; then \
	    echo "centaur-infra-env is missing DATABASE_URL; cannot seed CENTAUR_POSTGRES_DSN" >&2; \
	    exit 1; \
	  fi; \
	  kubectl -n "$(CENTAUR_NAMESPACE)" patch secret centaur-infra-env --type merge \
	    -p "{\"data\":{\"CENTAUR_POSTGRES_DSN\":\"$${CENTAUR_POSTGRES_DSN_B64}\"}}" >/dev/null; \
	  echo "Seeded CENTAUR_POSTGRES_DSN from the existing DATABASE_URL"; \
	fi; \
	echo "Building $${API_IMAGE}"; \
	docker build -t "$${API_IMAGE}" -f services/api-rs/Dockerfile .; \
	echo "Building $${SANDBOX_IMAGE}"; \
	docker build --target sandbox -t "$${SANDBOX_IMAGE}" -f services/sandbox/Dockerfile .; \
	echo "Building $${SLACKBOTV2_IMAGE}"; \
	docker build -t "$${SLACKBOTV2_IMAGE}" -f services/slackbotv2/Dockerfile .; \
	echo "Building $${CONSOLE_IMAGE}"; \
	docker build -t "$${CONSOLE_IMAGE}" -f services/console/Dockerfile services/console; \
	echo "Building $${IRON_PROXY_IMAGE}"; \
	docker build -t "$${IRON_PROXY_IMAGE}" -f services/iron-proxy/Dockerfile .; \
	echo "Importing images into k3s"; \
	docker save "$${API_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	docker save "$${SANDBOX_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	docker save "$${SLACKBOTV2_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	docker save "$${CONSOLE_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	docker save "$${IRON_PROXY_IMAGE}" | $(CENTAUR_K3S_CTR) images import -; \
	helm repo add centaur-onepassword https://1password.github.io/connect-helm-charts --force-update >/dev/null; \
	for attempt in 1 2 3; do \
	  if helm dependency build "$(CENTAUR_CHART)" --skip-refresh >/dev/null; then break; fi; \
	  if [[ "$${attempt}" -eq 3 ]]; then exit 1; fi; \
	done; \
	kubectl apply -f "$(CENTAUR_CHART)/charts/agent-sandbox/crds" >/dev/null; \
	helm upgrade "$(CENTAUR_RELEASE)" "$(CENTAUR_CHART)" -n "$(CENTAUR_NAMESPACE)" --reset-then-reuse-values \
	  --set apiRs.image.repository="$(CENTAUR_API_IMAGE_REPOSITORY)" \
	  --set apiRs.image.tag="fork-$${SHA}" \
	  --set apiRs.image.pullPolicy=IfNotPresent \
	  --set apiRs.syncInfraSecrets=true \
	  --set apiRs.etl.slack.enabled=true \
	  --set apiRs.etl.slack.indexPrivateChannels=false \
	  --set sandbox.image.repository="$(CENTAUR_SANDBOX_IMAGE_REPOSITORY)" \
	  --set sandbox.image.tag="fork-$${SHA}" \
	  --set sandbox.image.pullPolicy=IfNotPresent \
	  --set-string sandbox.extraEnv.CENTAUR_HARNESS_CONFIG_DIR=/home/agent/harness \
	  --set toolServer.repo="$(CENTAUR_TOOLS_REPOSITORY)" \
	  --set toolServer.ref="$${FULL_SHA}" \
	  --set slackbotv2.image.repository="$(CENTAUR_SLACKBOTV2_IMAGE_REPOSITORY)" \
	  --set slackbotv2.image.tag="fork-$${SHA}" \
	  --set slackbotv2.image.pullPolicy=IfNotPresent \
	  --set console.image.repository="$(CENTAUR_CONSOLE_IMAGE_REPOSITORY)" \
	  --set console.image.tag="fork-$${SHA}" \
	  --set console.image.pullPolicy=IfNotPresent \
	  --set ironProxy.image.repository="$(CENTAUR_IRON_PROXY_IMAGE_REPOSITORY)" \
	  --set ironProxy.image.tag="fork-$${SHA}" \
	  --set ironProxy.image.pullPolicy=IfNotPresent; \
	kubectl -n "$(CENTAUR_NAMESPACE)" rollout status "deploy/$(CENTAUR_CONSOLE_DEPLOYMENT)" --timeout=180s; \
	kubectl -n "$(CENTAUR_NAMESPACE)" rollout status "deploy/$(CENTAUR_CONSOLE_WORKER_DEPLOYMENT)" --timeout=180s; \
	kubectl -n "$(CENTAUR_NAMESPACE)" rollout status "deploy/$(CENTAUR_API_DEPLOYMENT)" --timeout=180s; \
	for tool in $(CENTAUR_REQUIRED_INFRA_TOOLS); do \
	  kubectl -n "$(CENTAUR_NAMESPACE)" exec "deploy/$(CENTAUR_API_DEPLOYMENT)" -- \
	    centaur-perms --tools-dir /app/tools roles grant infra --tool "$${tool}"; \
	done; \
	kubectl -n "$(CENTAUR_NAMESPACE)" rollout status "deploy/$(CENTAUR_SLACKBOTV2_DEPLOYMENT)" --timeout=180s; \
	kubectl -n "$(CENTAUR_NAMESPACE)" rollout status "daemonset/$(CENTAUR_REPO_CACHE_DAEMONSET)" --timeout=180s; \
	kubectl -n "$(CENTAUR_NAMESPACE)" get deploy "$(CENTAUR_API_DEPLOYMENT)" \
	  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'; \
	kubectl -n "$(CENTAUR_NAMESPACE)" get deploy "$(CENTAUR_API_DEPLOYMENT)" \
	  -o jsonpath='{range .spec.template.spec.containers[0].env[?(@.name=="AGENT_IMAGE")]}{.value}{"\n"}{end}'
