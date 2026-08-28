# Host disk cleanup

`make install-host-cleanup` installs and enables a daily systemd timer for
hosts that build Centaur images locally before importing them into Kubernetes.

The cleanup keeps the three newest tags for each `centaur-*` image repository
and every image referenced by a workload or a Pending/Running Kubernetes pod.
It removes terminal API-managed sandbox and proxy pods after 24 hours, caps
unused build cache at 30 GB, and removes dangling images. It never prunes
containers or volumes.

Override defaults in `/etc/default/centaur-host-cleanup` when the host needs a
different policy:

```bash
CENTAUR_NAMESPACE=centaur
CENTAUR_IMAGE_GENERATIONS_TO_KEEP=3
CENTAUR_BUILD_CACHE_MAX_USED_SPACE=30GB
CENTAUR_TERMINAL_POD_MAX_AGE_SECS=86400
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
