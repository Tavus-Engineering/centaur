#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT
command_log="$test_dir/commands.log"

cat >"$test_dir/df" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "${DF_FAIL:-0}" == "0" ]] || exit 1
printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
[[ "${DF_EMPTY:-0}" == "0" ]] || exit 0
printf '/dev/test 1000000 0 %s 0%% /\n' "${AVAILABLE_KIB:-500000}"
MOCK
chmod +x "$test_dir/df"
export DF_BIN="$test_dir/df"

cat >"$test_dir/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "image ls" ]]; then
  cat <<'IMAGES'
centaur-api|fork-new|sha-new
centaur-api|fork-second|sha-second
centaur-api|fork-third|sha-third
centaur-api|fork-active|sha-active
centaur-api|fork-terminal|sha-terminal
centaur-api|fork-old|sha-old
unrelated-service|latest|sha-unrelated
IMAGES
  exit 0
fi
printf '%s\n' "$*" >>"$COMMAND_LOG"
MOCK

cat >"$test_dir/kubectl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${KUBECTL_FAIL:-0}" == "1" ]]; then
  exit 1
fi
printf 'kubectl %s\n' "$*" >>"$COMMAND_LOG"
if [[ "$*" == *'status.phase=Failed'* ]]; then
  printf '2026-08-25T00:00:00Z\told-failed\n2026-08-27T23:30:00Z\trecent-failed\n'
elif [[ "$*" == *'status.phase=Succeeded'* ]]; then
  printf '2026-08-24T00:00:00Z\told-succeeded\n'
elif [[ "$*" == *'status.phase=Pending'* ]]; then
  printf '%s\n' 'docker.io/library/centaur-api:fork-active'
elif [[ "$*" == *'status.phase=Running'* ]]; then
  printf '%s\n' 'unrelated-service:latest'
elif [[ "$*" == *'deployments,statefulsets,daemonsets'* ]]; then
  printf '%s\n' 'centaur-api:fork-new'
fi
MOCK

cat >"$test_dir/date" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "+%s" ]]; then
  printf '%s\n' 1787877000
  exit 0
fi
case "$2" in
  2026-08-24T00:00:00Z) printf '%s\n' 1787529600 ;;
  2026-08-25T00:00:00Z) printf '%s\n' 1787616000 ;;
  2026-08-27T23:30:00Z) printf '%s\n' 1787873400 ;;
  *) exit 1 ;;
esac
MOCK

chmod +x "$test_dir/docker" "$test_dir/kubectl" "$test_dir/date"
COMMAND_LOG="$command_log" \
DOCKER_BIN="$test_dir/docker" \
KUBECTL_BIN="$test_dir/kubectl" \
DATE_BIN="$test_dir/date" \
CENTAUR_DISK_PATH="$test_dir" \
  "$repo_root/contrib/scripts/host-disk-cleanup.sh" >/dev/null

grep -Fqx 'builder prune --all --force --max-used-space 30GB' "$command_log"
grep -Fqx 'image prune --force' "$command_log"
grep -Fqx 'kubectl -n centaur delete pod old-failed --wait=true' "$command_log"
grep -Fqx 'kubectl -n centaur delete pod old-succeeded --wait=true' "$command_log"
grep -Fqx 'image rm centaur-api:fork-old' "$command_log"
grep -Fqx 'image rm centaur-api:fork-terminal' "$command_log"
if grep -Fq 'delete pod recent-failed' "$command_log"; then
  echo "recent terminal pod was pruned" >&2
  exit 1
fi
if grep -Fq 'fork-active' "$command_log"; then
  echo "active image was pruned" >&2
  exit 1
fi
if grep -Fq 'unrelated-service' "$command_log"; then
  echo "unrelated image was pruned" >&2
  exit 1
fi
if grep -Fq 'container prune' "$command_log"; then
  echo "containers must not be pruned" >&2
  exit 1
fi

: >"$command_log"
COMMAND_LOG="$command_log" \
DOCKER_BIN="$test_dir/docker" \
KUBECTL_BIN="$test_dir/kubectl" \
DATE_BIN="$test_dir/date" \
KUBECTL_FAIL=1 \
CENTAUR_DISK_PATH="$test_dir" \
  "$repo_root/contrib/scripts/host-disk-cleanup.sh" >/dev/null 2>&1
if grep -Fq 'image rm' "$command_log"; then
  echo "tagged images were pruned without a Kubernetes inventory" >&2
  exit 1
fi

# Successful no-op pruning must not hide the disk pressure that caused an outage.
: >"$command_log"
status=0
COMMAND_LOG="$command_log" \
DOCKER_BIN="$test_dir/docker" \
KUBECTL_BIN="$test_dir/kubectl" \
DATE_BIN="$test_dir/date" \
AVAILABLE_KIB=40000 \
  "$repo_root/contrib/scripts/host-disk-cleanup.sh" >"$test_dir/low-space.log" 2>&1 || status=$?
[[ "$status" == "1" ]]
grep -Fq 'insufficient disk headroom' "$test_dir/low-space.log"
grep -Fq 'builder prune' "$command_log"

# The deployment/monitoring check must never contact Docker or Kubernetes.
: >"$command_log"
for available in 0 199999 200000 500000; do
  status=0
  COMMAND_LOG="$command_log" \
  DOCKER_BIN="$test_dir/docker" \
  KUBECTL_BIN="$test_dir/kubectl" \
  AVAILABLE_KIB="$available" \
  CENTAUR_HOST_CLEANUP_CHECK_ONLY=1 \
    "$repo_root/contrib/scripts/host-disk-cleanup.sh" >/dev/null 2>&1 || status=$?
  if ((available < 200000)); then
    [[ "$status" == "1" ]]
  else
    [[ "$status" == "0" ]]
  fi
done
[[ ! -s "$command_log" ]]

AVAILABLE_KIB=300000 CENTAUR_DISK_MIN_FREE_PERCENT=30 CENTAUR_HOST_CLEANUP_CHECK_ONLY=1 \
  "$repo_root/contrib/scripts/host-disk-cleanup.sh" >/dev/null
for invalid in 0 100 invalid 020; do
  status=0
  CENTAUR_DISK_MIN_FREE_PERCENT="$invalid" CENTAUR_HOST_CLEANUP_CHECK_ONLY=1 \
    "$repo_root/contrib/scripts/host-disk-cleanup.sh" >/dev/null 2>&1 || status=$?
  [[ "$status" == "2" ]]
done
for measurement in failure malformed empty; do
  status=0
  DF_FAIL="$([[ "$measurement" == failure ]] && echo 1 || echo 0)" \
  DF_EMPTY="$([[ "$measurement" == empty ]] && echo 1 || echo 0)" \
  AVAILABLE_KIB=unknown CENTAUR_HOST_CLEANUP_CHECK_ONLY=1 \
    "$repo_root/contrib/scripts/host-disk-cleanup.sh" >/dev/null 2>&1 || status=$?
  [[ "$status" == "2" ]]
done

: >"$command_log"
status=0
PATH="$test_dir:$PATH" COMMAND_LOG="$command_log" AVAILABLE_KIB=40000 \
  make --no-print-directory -s -C "$repo_root" deploy >"$test_dir/deploy.log" 2>&1 || status=$?
[[ "$status" != "0" ]]
grep -Fq 'insufficient disk headroom' "$test_dir/deploy.log"
[[ ! -s "$command_log" ]]

COMMAND_LOG="$command_log" DOCKER_BIN="$test_dir/docker" \
KUBECTL_BIN="$test_dir/kubectl" DATE_BIN="$test_dir/date" CENTAUR_KUBE_CONTEXT=local-test \
  "$repo_root/contrib/scripts/host-disk-cleanup.sh" >/dev/null
grep -Fqx 'kubectl --context local-test -n centaur delete pod old-failed --wait=true' "$command_log"
if grep '^kubectl ' "$command_log" | grep -v '^kubectl --context local-test '; then
  echo "Kubernetes command ignored the configured context" >&2
  exit 1
fi

echo "host disk cleanup test: PASS"
