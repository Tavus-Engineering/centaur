#!/usr/bin/env bash
set -euo pipefail

docker_bin="${DOCKER_BIN:-docker}"
kubectl_bin="${KUBECTL_BIN:-kubectl}"
namespace="${CENTAUR_NAMESPACE:-centaur}"
image_prefix="${CENTAUR_IMAGE_PREFIX:-centaur-}"
generations_to_keep="${CENTAUR_IMAGE_GENERATIONS_TO_KEEP:-3}"
builder_max_used_space="${CENTAUR_BUILD_CACHE_MAX_USED_SPACE:-30GB}"
disk_path="${CENTAUR_DISK_PATH:-/}"
dry_run="${CENTAUR_HOST_CLEANUP_DRY_RUN:-0}"

die() {
  echo "centaur host cleanup: $*" >&2
  exit 2
}

[[ "$generations_to_keep" =~ ^[1-9][0-9]*$ ]] \
  || die "CENTAUR_IMAGE_GENERATIONS_TO_KEEP must be a positive integer"
[[ "$builder_max_used_space" =~ ^[1-9][0-9]*([kmgtKMGT][bB])?$ ]] \
  || die "CENTAUR_BUILD_CACHE_MAX_USED_SPACE must be a positive byte quantity"
[[ "$dry_run" =~ ^(0|1)$ ]] || die "CENTAUR_HOST_CLEANUP_DRY_RUN must be 0 or 1"
command -v "$docker_bin" >/dev/null 2>&1 || die "docker command not found: $docker_bin"

print_command() {
  printf 'centaur host cleanup: would run'
  printf ' %q' "$@"
  printf '\n'
}

run_docker() {
  if [[ "$dry_run" == "1" ]]; then
    print_command "$docker_bin" "$@"
    return 0
  fi
  "$docker_bin" "$@"
}

normalize_image_ref() {
  local ref="$1"
  ref="${ref#docker.io/library/}"
  ref="${ref#docker.io/}"
  printf '%s\n' "$ref"
}

echo "centaur host cleanup: disk usage before"
df -h "$disk_path"

# Bound the default builder even when a burst of recent deploys creates more
# cache than the host can safely carry. This never removes images or containers.
run_docker builder prune --all --force --max-used-space "$builder_max_used_space"
run_docker image prune --force

cleanup_dir="$(mktemp -d)"
trap 'rm -rf "$cleanup_dir"' EXIT
active_images_file="$cleanup_dir/active-images"
old_images_file="$cleanup_dir/old-images"
: >"$active_images_file"
kube_inventory_available=0

if command -v "$kubectl_bin" >/dev/null 2>&1; then
  if workload_images="$($kubectl_bin -n "$namespace" \
      get pods,deployments,statefulsets,daemonsets \
      -o jsonpath='{..image}' 2>/dev/null)"; then
    kube_inventory_available=1
    for image in $workload_images; do
      normalize_image_ref "$image" >>"$active_images_file"
    done
  else
    echo "centaur host cleanup: Kubernetes inventory failed; skipping tagged image pruning" >&2
  fi
else
  echo "centaur host cleanup: kubectl unavailable; skipping tagged image pruning" >&2
fi

if [[ "$kube_inventory_available" == "1" ]]; then
  "$docker_bin" image ls --format '{{.Repository}}|{{.Tag}}|{{.ID}}' \
    | awk -F '|' -v prefix="$image_prefix" -v keep="$generations_to_keep" '
        $1 != "" && $1 != "<none>" && $2 != "" && $2 != "<none>" {
          part_count = split($1, parts, "/")
          if (index(parts[part_count], prefix) != 1) next
          generations[$1]++
          if (generations[$1] > keep) print $1 ":" $2
        }
      ' >"$old_images_file"
else
  : >"$old_images_file"
fi

while IFS= read -r reference; do
  [[ -n "$reference" ]] || continue
  normalized_reference="$(normalize_image_ref "$reference")"
  if grep -Fqx -- "$normalized_reference" "$active_images_file"; then
    echo "centaur host cleanup: retaining active image $reference"
    continue
  fi

  echo "centaur host cleanup: pruning old Centaur image $reference"
  if ! run_docker image rm "$reference"; then
    echo "centaur host cleanup: could not prune $reference; leaving it in place" >&2
  fi
done <"$old_images_file"

echo "centaur host cleanup: disk usage after"
df -h "$disk_path"
