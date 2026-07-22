"""Guarded GitHub orchestration for Tavus CVI and RQH releases."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import httpx

from centaur_sdk import secret

_GITHUB_API = "https://api.github.com"
_RELEASE_TITLE = re.compile(r"^chore\(main\): release (?P<version>\d+\.\d+\.\d+)$")
_TERMINAL_RUN_STATUS = "completed"
_GOOD_CHECK_CONCLUSIONS = {"success", "neutral", "skipped"}
_ACTIVE_RUN_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
_CVI_APPROVAL_ENVIRONMENTS = {
    "promote-to-prod-cerebrium",
    "promote-to-prod-fal",
    "promote-to-prod-modal",
}
_RQH_APPROVAL_ENVIRONMENTS = {"manual-approval"}


@dataclasses.dataclass(frozen=True)
class ServiceConfig:
    key: str
    display_name: str
    repository: str
    deployment_workflow: str
    release_branch_prefix: str
    approval_environments: frozenset[str]


_SERVICES = {
    "cvi": ServiceConfig(
        key="cvi",
        display_name="CVI",
        repository="Tavus-Engineering/realtime-replica",
        deployment_workflow="deploy-cvi.yml",
        release_branch_prefix="release-please--branches--main",
        approval_environments=frozenset(_CVI_APPROVAL_ENVIRONMENTS),
    ),
    "rqh": ServiceConfig(
        key="rqh",
        display_name="RQH",
        repository="Tavus-Engineering/request-handler",
        deployment_workflow="build-test-deploy-staging-prod-region.yml",
        release_branch_prefix="release-please--branches--main",
        approval_environments=frozenset(_RQH_APPROVAL_ENVIRONMENTS),
    ),
}


def _service(service: str) -> ServiceConfig:
    normalized = (service or "").strip().lower()
    if normalized not in _SERVICES:
        raise RuntimeError("service must be one of: cvi, rqh")
    return _SERVICES[normalized]


def _confirmation() -> str:
    return "deploy"


def _cancel_confirmation(config: ServiceConfig, run_id: int) -> str:
    return f"CANCEL {config.display_name} RUN {run_id}"


def _rerun_confirmation(config: ServiceConfig, run_id: int, head_sha: str) -> str:
    return f"RERUN FAILED {config.display_name} RUN {run_id} AT {head_sha}"


class DeploymentCaptainClient:
    """Release operations constrained to CVI and RQH repositories and workflows."""

    def __init__(
        self,
        token: str | None = None,
        approver_token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        centaur_api_url: str | None = None,
    ) -> None:
        self._token = token
        self._approver_token_value = approver_token
        self._centaur_api_url = centaur_api_url
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _github_token(self) -> str:
        token = (self._token or secret("GITHUB_TOKEN", "")).strip()
        if not token or token == "GITHUB_TOKEN":
            raise RuntimeError("GITHUB_TOKEN is required.")
        return token

    def _approver_token(self) -> str:
        token = (self._approver_token_value or secret("GITHUB_APPROVER_TOKEN", "")).strip()
        if not token or token == "GITHUB_APPROVER_TOKEN":
            raise RuntimeError(
                "GITHUB_APPROVER_TOKEN is required and must belong to an eligible "
                "identity distinct from the release initiator."
            )
        return token

    def _headers(self, token: str | None = None) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token or self._github_token()}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _github(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        expected: set[int] | None = None,
        token: str | None = None,
    ) -> Any:
        response = self._client.request(
            method,
            f"{_GITHUB_API}{path}",
            headers=self._headers(token),
            params=params,
            json=json,
        )
        allowed = expected or {200}
        if response.status_code not in allowed:
            body = response.text[:1000]
            raise RuntimeError(
                f"GitHub API {method} {path} failed ({response.status_code}): {body}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _repo(self, config: ServiceConfig, path: str) -> str:
        return f"/repos/{config.repository}{path}"

    def _workflow_runs(self, config: ServiceConfig, *, per_page: int = 30) -> list[dict[str, Any]]:
        payload = self._github(
            "GET",
            self._repo(config, f"/actions/workflows/{config.deployment_workflow}/runs"),
            params={"per_page": per_page},
        )
        runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
        return [run for run in runs if isinstance(run, dict)]

    def _active_runs(self, config: ServiceConfig) -> list[dict[str, Any]]:
        active = []
        for run in self._workflow_runs(config):
            status = str(run.get("status") or "")
            if status in _ACTIVE_RUN_STATUSES or status != _TERMINAL_RUN_STATUS:
                active.append(
                    {
                        "id": run.get("id"),
                        "status": status,
                        "conclusion": run.get("conclusion"),
                        "head_sha": run.get("head_sha"),
                        "display_title": run.get("display_title"),
                        "created_at": run.get("created_at"),
                        "url": run.get("html_url"),
                    }
                )
        return active

    def _release_pull_requests(self, config: ServiceConfig) -> list[dict[str, Any]]:
        pulls = self._github(
            "GET",
            self._repo(config, "/pulls"),
            params={"state": "open", "base": "main", "per_page": 100},
        )
        releases = []
        for pull in pulls if isinstance(pulls, list) else []:
            title = str(pull.get("title") or "")
            head_ref = str((pull.get("head") or {}).get("ref") or "")
            if _RELEASE_TITLE.fullmatch(title) and head_ref.startswith(
                config.release_branch_prefix
            ):
                releases.append(pull)
        return releases

    def _checks(self, config: ServiceConfig, head_sha: str) -> list[dict[str, Any]]:
        payload = self._github(
            "GET",
            self._repo(config, f"/commits/{head_sha}/check-runs"),
            params={"per_page": 100},
        )
        checks = payload.get("check_runs", []) if isinstance(payload, dict) else []
        return [
            {
                "name": check.get("name"),
                "status": check.get("status"),
                "conclusion": check.get("conclusion"),
                "url": check.get("html_url"),
            }
            for check in checks
            if isinstance(check, dict)
        ]

    def _reviews(self, config: ServiceConfig, pr_number: int) -> list[dict[str, Any]]:
        reviews = self._github(
            "GET",
            self._repo(config, f"/pulls/{pr_number}/reviews"),
            params={"per_page": 100},
        )
        return [
            {
                "author": (review.get("user") or {}).get("login"),
                "state": review.get("state"),
                "submitted_at": review.get("submitted_at"),
            }
            for review in reviews
            if isinstance(reviews, list) and isinstance(review, dict)
        ]

    def prepare_release(self, service: str) -> dict[str, Any]:
        """Build a read-only release plan. This never starts or changes a deployment."""
        config = _service(service)
        releases = self._release_pull_requests(config)
        active_runs = self._active_runs(config)
        if len(releases) != 1:
            return {
                "service": config.key,
                "ready_to_start": False,
                "blockers": [
                    f"Expected exactly one open release-please PR; found {len(releases)}."
                ],
                "active_deployment_runs": active_runs,
                "release_pull_requests": [
                    {"number": pull.get("number"), "title": pull.get("title")} for pull in releases
                ],
            }

        candidate = releases[0]
        pr_number = int(candidate["number"])
        pull = self._github("GET", self._repo(config, f"/pulls/{pr_number}"))
        title_match = _RELEASE_TITLE.fullmatch(str(pull.get("title") or ""))
        if not title_match:
            raise RuntimeError("Release PR title changed during preparation.")
        version = title_match.group("version")
        head_sha = str((pull.get("head") or {}).get("sha") or "")
        checks = self._checks(config, head_sha)
        reviews = self._reviews(config, pr_number)
        blockers: list[str] = []
        if active_runs:
            ids = ", ".join(str(run["id"]) for run in active_runs)
            blockers.append(f"Deployment workflow already has active run(s): {ids}.")
        mergeable_state = str(pull.get("mergeable_state") or "unknown")
        if mergeable_state != "clean":
            blockers.append(f"Release PR mergeable_state is {mergeable_state!r}, not 'clean'.")
        incomplete = [check["name"] for check in checks if check["status"] != "completed"]
        failing = [
            check["name"]
            for check in checks
            if check["status"] == "completed" and check["conclusion"] not in _GOOD_CHECK_CONCLUSIONS
        ]
        if incomplete:
            blockers.append(f"Checks still running: {', '.join(str(name) for name in incomplete)}.")
        if failing:
            blockers.append(f"Checks not successful: {', '.join(str(name) for name in failing)}.")

        return {
            "service": config.key,
            "repository": config.repository,
            "version": version,
            "release_pr": {
                "number": pr_number,
                "url": pull.get("html_url"),
                "head_sha": head_sha,
                "head_ref": (pull.get("head") or {}).get("ref"),
                "mergeable_state": mergeable_state,
            },
            "ready_to_start": not blockers,
            "blockers": blockers,
            "active_deployment_runs": active_runs,
            "checks": checks,
            "reviews": reviews,
            "confirmation": _confirmation(),
            "notes": [
                "No pre-deployment acknowledgement or polling window is required.",
                "Starting merges this exact PR and triggers the repository deployment workflow.",
                "Announce only after the exact staging/canary deployment is healthy.",
                "Production environment approval remains a human gate.",
            ],
        }

    def start_release(
        self,
        service: str,
        pr_number: int,
        head_sha: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Merge one exact, prepared release PR after an explicit confirmation."""
        config = _service(service)
        plan = self.prepare_release(config.key)
        release_pr = plan.get("release_pr") or {}
        if not plan.get("ready_to_start"):
            raise RuntimeError(f"Release is blocked: {plan.get('blockers')}")
        if int(release_pr.get("number") or 0) != pr_number:
            raise RuntimeError("Prepared release PR number no longer matches.")
        if str(release_pr.get("head_sha") or "") != head_sha:
            raise RuntimeError("Prepared release head SHA no longer matches.")
        if confirmation != plan.get("confirmation"):
            raise RuntimeError(f"Confirmation must be exactly: {plan.get('confirmation')}")

        merged = self._github(
            "PUT",
            self._repo(config, f"/pulls/{pr_number}/merge"),
            json={"sha": head_sha, "merge_method": "squash"},
            expected={200},
        )
        if not merged.get("merged"):
            raise RuntimeError(f"GitHub did not merge the release PR: {merged.get('message')}")
        return {
            "started": True,
            "service": config.key,
            "version": plan["version"],
            "release_pr_number": pr_number,
            "release_head_sha": head_sha,
            "merge_commit_sha": merged.get("sha"),
            "deployment_workflow": config.deployment_workflow,
        }

    def launch_release(
        self,
        service: str,
        pr_number: int,
        head_sha: str,
        confirmation: str,
        slack_channel: str,
        slack_thread_ts: str,
        soak_minutes: int = 10,
    ) -> dict[str, Any]:
        """Create the durable Centaur release workflow; the workflow performs the merge."""
        config = _service(service)
        plan = self.prepare_release(config.key)
        if confirmation != plan.get("confirmation"):
            raise RuntimeError(f"Confirmation must be exactly: {plan.get('confirmation')}")
        if int((plan.get("release_pr") or {}).get("number") or 0) != pr_number:
            raise RuntimeError("Prepared release PR number no longer matches.")
        if str((plan.get("release_pr") or {}).get("head_sha") or "") != head_sha:
            raise RuntimeError("Prepared release head SHA no longer matches.")
        if not plan.get("ready_to_start"):
            raise RuntimeError(f"Release is blocked: {plan.get('blockers')}")
        if not slack_channel.strip() or not slack_thread_ts.strip():
            raise RuntimeError("slack_channel and slack_thread_ts are required for supervision.")

        configured_url = self._centaur_api_url or secret("CENTAUR_API_URL", "")
        api_url = configured_url.strip().rstrip("/")
        if not api_url or api_url == "CENTAUR_API_URL":
            api_url = "http://centaur-centaur-api-rs:8080"
        payload = {
            "workflow_name": "deployment_captain",
            "input": {
                "service": config.key,
                "pr_number": pr_number,
                "head_sha": head_sha,
                "confirmation": confirmation,
                "slack_channel": slack_channel,
                "slack_thread_ts": slack_thread_ts,
                "soak_minutes": max(5, min(int(soak_minutes), 60)),
            },
            "idempotency_key": f"deployment-captain:{config.key}:{head_sha}",
            "max_attempts": 3,
        }
        response = self._client.post(f"{api_url}/api/workflows/runs", json=payload)
        if response.status_code not in {200, 201, 202}:
            raise RuntimeError(
                f"Centaur workflow launch failed ({response.status_code}): {response.text[:1000]}"
            )
        result = response.json()
        return {
            "launched": True,
            "service": config.key,
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "created": result.get("created"),
            "idempotency_key": payload["idempotency_key"],
        }

    def release_run_status(
        self,
        service: str,
        merge_commit_sha: str,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        """Inspect the exact deployment run for a release merge commit."""
        config = _service(service)
        candidates = [
            run
            for run in self._workflow_runs(config, per_page=100)
            if str(run.get("head_sha") or "") == merge_commit_sha
        ]
        if run_id is not None:
            candidates = [run for run in candidates if int(run.get("id") or 0) == int(run_id)]
        if len(candidates) != 1:
            return {
                "found": False,
                "service": config.key,
                "merge_commit_sha": merge_commit_sha,
                "candidate_run_ids": [run.get("id") for run in candidates],
            }
        run = candidates[0]
        exact_run_id = int(run["id"])
        jobs_payload = self._github(
            "GET",
            self._repo(config, f"/actions/runs/{exact_run_id}/jobs"),
            params={"per_page": 100},
        )
        jobs = [
            {
                "id": job.get("id"),
                "name": job.get("name"),
                "status": job.get("status"),
                "conclusion": job.get("conclusion"),
                "url": job.get("html_url"),
            }
            for job in jobs_payload.get("jobs", [])
            if isinstance(job, dict)
        ]
        pending = self._github(
            "GET",
            self._repo(config, f"/actions/runs/{exact_run_id}/pending_deployments"),
        )
        pending_environments = [
            {
                "id": (item.get("environment") or {}).get("id"),
                "name": (item.get("environment") or {}).get("name"),
            }
            for item in pending
            if isinstance(pending, list) and isinstance(item, dict)
        ]
        names = {str(item["name"]) for item in pending_environments}
        required = set(config.approval_environments)
        return {
            "found": True,
            "service": config.key,
            "run_id": exact_run_id,
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("head_sha"),
            "url": run.get("html_url"),
            "jobs": jobs,
            "pending_environments": pending_environments,
            "required_approval_environments": sorted(required),
            "all_production_gates_ready": required.issubset(names),
        }

    def dispatch_cvi_traffic(
        self,
        stage_fraction: int,
        request_id: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Dispatch the RQH-owned CVI traffic workflow for exactly 0% or 5% stage."""
        if stage_fraction not in {0, 5}:
            raise RuntimeError("stage_fraction must be 0 or 5.")
        expected = f"SET CVI STAGE TO {stage_fraction} FOR {request_id}"
        if confirmation != expected:
            raise RuntimeError(f"Confirmation must be exactly: {expected}")
        config = _service("rqh")
        self._github(
            "POST",
            self._repo(config, "/actions/workflows/cvi-traffic-routing.yml/dispatches"),
            json={
                "ref": "main",
                "inputs": {
                    "mode": "apply",
                    "stage_fraction": str(stage_fraction),
                    "request_id": request_id,
                    "reason": "Centaur deployment-captain workflow",
                    "confirmation": confirmation,
                },
            },
            expected={204},
        )
        return {"dispatched": True, "stage_fraction": stage_fraction, "request_id": request_id}

    def dispatch_cerebrium_rollback(
        self,
        phoenix3_build_id: str,
        phoenix4_build_id: str,
        incident_url: str,
        request_id: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Dispatch the CVI-owned exact-build Cerebrium rollback workflow."""
        if not re.fullmatch(r"build-[A-Za-z0-9_-]+", phoenix3_build_id):
            raise RuntimeError("phoenix3_build_id must be an exact Cerebrium build-* ID.")
        if not re.fullmatch(r"build-[A-Za-z0-9_-]+", phoenix4_build_id):
            raise RuntimeError("phoenix4_build_id must be an exact Cerebrium build-* ID.")
        expected = (
            f"ROLL BACK CEREBRIUM TO {phoenix3_build_id},{phoenix4_build_id} FOR {request_id}"
        )
        if confirmation != expected:
            raise RuntimeError(f"Confirmation must be exactly: {expected}")
        if not incident_url.startswith("https://"):
            raise RuntimeError(
                "incident_url must be an https URL for the active outage thread/call."
            )
        config = _service("cvi")
        self._github(
            "POST",
            self._repo(config, "/actions/workflows/cerebrium-emergency-rollback.yml/dispatches"),
            json={
                "ref": "main",
                "inputs": {
                    "mode": "apply",
                    "phoenix3_build_id": phoenix3_build_id,
                    "phoenix4_build_id": phoenix4_build_id,
                    "incident_url": incident_url,
                    "request_id": request_id,
                    "confirmation": confirmation,
                },
            },
            expected={204},
        )
        return {"dispatched": True, "request_id": request_id}

    def cancel_release_run(self, service: str, run_id: int, confirmation: str) -> dict[str, Any]:
        """Cancel one exact active deployment run after explicit confirmation."""
        config = _service(service)
        expected = _cancel_confirmation(config, run_id)
        if confirmation != expected:
            raise RuntimeError(f"Confirmation must be exactly: {expected}")
        run = self._github("GET", self._repo(config, f"/actions/runs/{run_id}"))
        if str(run.get("path") or "").split("@")[0] != (
            f".github/workflows/{config.deployment_workflow}"
        ):
            raise RuntimeError("Run does not belong to the configured deployment workflow.")
        if run.get("status") == _TERMINAL_RUN_STATUS:
            return {"cancelled": False, "already_terminal": True, "run_id": run_id}
        self._github(
            "POST",
            self._repo(config, f"/actions/runs/{run_id}/cancel"),
            expected={202, 409},
        )
        return {"cancelled": True, "run_id": run_id}

    def rerun_failed_jobs(
        self,
        service: str,
        run_id: int,
        head_sha: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Rerun failed jobs on one exact deployment run and head SHA."""
        config = _service(service)
        expected = _rerun_confirmation(config, run_id, head_sha)
        if confirmation != expected:
            raise RuntimeError(f"Confirmation must be exactly: {expected}")
        run = self._github("GET", self._repo(config, f"/actions/runs/{run_id}"))
        if str(run.get("head_sha") or "") != head_sha:
            raise RuntimeError("Run head SHA does not match the supplied head_sha.")
        if run.get("status") != _TERMINAL_RUN_STATUS:
            raise RuntimeError("Only a completed run can rerun failed jobs.")
        self._github(
            "POST",
            self._repo(config, f"/actions/runs/{run_id}/rerun-failed-jobs"),
            expected={201},
        )
        return {"rerun_started": True, "run_id": run_id, "head_sha": head_sha}

    def approve_production_gates(
        self,
        service: str,
        run_id: int,
        environment_names: list[str],
        comment: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Approve exact pending environments; requires a distinct eligible GitHub identity."""
        config = _service(service)
        requested = set(environment_names)
        if not requested or not requested.issubset(config.approval_environments):
            raise RuntimeError(
                f"environment_names must be a non-empty subset of "
                f"{sorted(config.approval_environments)}"
            )
        expected = (
            f"APPROVE {config.display_name} RUN {run_id} ENVIRONMENTS {','.join(sorted(requested))}"
        )
        if confirmation != expected:
            raise RuntimeError(f"Confirmation must be exactly: {expected}")
        pending = self._github(
            "GET", self._repo(config, f"/actions/runs/{run_id}/pending_deployments")
        )
        available = {
            str((item.get("environment") or {}).get("name")): int(
                (item.get("environment") or {}).get("id")
            )
            for item in pending
            if isinstance(pending, list)
            and isinstance(item, dict)
            and (item.get("environment") or {}).get("id") is not None
        }
        missing = requested - set(available)
        if missing:
            raise RuntimeError(f"Environments are not pending on run {run_id}: {sorted(missing)}")
        self._github(
            "POST",
            self._repo(config, f"/actions/runs/{run_id}/pending_deployments"),
            json={
                "environment_ids": [available[name] for name in sorted(requested)],
                "state": "approved",
                "comment": comment[:1000],
            },
            expected={200},
            token=self._approver_token(),
        )
        return {"approved": True, "run_id": run_id, "environments": sorted(requested)}

    def workflow_dispatch_status(
        self, repository_service: str, workflow_file: str, request_id: str
    ) -> dict[str, Any]:
        """Find a guarded facade workflow run by its unique request ID."""
        config = _service(repository_service)
        allowed = {
            "rqh": {"cvi-traffic-routing.yml"},
            "cvi": {"cerebrium-emergency-rollback.yml"},
        }
        if workflow_file not in allowed[config.key]:
            raise RuntimeError("workflow_file is not an allowed deployment-captain facade.")
        payload = self._github(
            "GET",
            self._repo(config, f"/actions/workflows/{workflow_file}/runs"),
            params={"event": "workflow_dispatch", "per_page": 50},
        )
        candidates = [
            run
            for run in payload.get("workflow_runs", [])
            if request_id in str(run.get("display_title") or "")
        ]
        if len(candidates) != 1:
            return {
                "found": False,
                "request_id": request_id,
                "candidate_run_ids": [run.get("id") for run in candidates],
            }
        run = candidates[0]
        return {
            "found": True,
            "request_id": request_id,
            "run_id": run.get("id"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "url": run.get("html_url"),
        }

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DeploymentCaptainClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _client() -> DeploymentCaptainClient:
    return DeploymentCaptainClient()
