# Host disk cleanup

`make install-host-cleanup` installs and enables an hourly systemd timer for
hosts that build Centaur images locally before importing them into Kubernetes.

The cleanup keeps the three newest tags for each `centaur-*` image repository
and every image referenced by a workload or a Pending/Running Kubernetes pod.
It removes terminal API-managed sandbox and proxy pods after 24 hours, caps
unused build cache at 30 GB, and removes dangling images. It never prunes
containers or volumes.

A run fails if less than 20% of the filesystem remains available after cleanup,
even when every prune command succeeds. This flags low headroom before node disk
pressure prevents replacement pods from starting. Monitor failures of
`centaur-host-cleanup.service`; a successful prune that reclaims zero bytes is
not evidence that the host has enough capacity. On shared hosts, provision for
other workloads as well as container images and build cache.

`make deploy` checks the same threshold before starting a build. The threshold
should exceed the node's eviction threshold plus its minimum reclaim margin.

Override defaults in `/etc/default/centaur-host-cleanup` when the host needs a
different policy:

```bash
CENTAUR_NAMESPACE=centaur
CENTAUR_IMAGE_GENERATIONS_TO_KEEP=3
CENTAUR_BUILD_CACHE_MAX_USED_SPACE=30GB
CENTAUR_TERMINAL_POD_MAX_AGE_SECS=86400
CENTAUR_DISK_MIN_FREE_PERCENT=20
```

Preview a run without deleting anything:

```bash
sudo CENTAUR_HOST_CLEANUP_DRY_RUN=1 \
  /usr/local/libexec/centaur/host-disk-cleanup
```

Inspect the installed schedule and its latest result:

```bash
systemctl list-timers centaur-host-cleanup.timer
journalctl -u centaur-host-cleanup.service -n 100
```

Check capacity without Docker, Kubernetes, or any cleanup operations:

```bash
CENTAUR_HOST_CLEANUP_CHECK_ONLY=1 contrib/scripts/host-disk-cleanup.sh
```

The command returns 0 for sufficient headroom, 1 for insufficient headroom, or
2 for invalid settings or a failed measurement. The installed service reads
overrides from `/etc/default/centaur-host-cleanup`; export the same overrides
when invoking `make deploy` or running the check directly.
