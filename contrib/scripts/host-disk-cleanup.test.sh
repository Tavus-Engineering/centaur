#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT
command_log="$test_dir/commands.log"

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

echo "host disk cleanup test: PASS"
