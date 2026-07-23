from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

_CLIENT_PATH = Path(__file__).parents[1] / "client.py"
_SPEC = importlib.util.spec_from_file_location("deployment_captain_client", _CLIENT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
DeploymentCaptainClient = _MODULE.DeploymentCaptainClient


def _response(payload, status_code=200):
    return httpx.Response(status_code, json=payload)


def _github_handler(*, active_run: bool):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls"):
            assert request.method == "GET"
            return _response(
                [
                    {
                        "number": 10,
                        "title": "chore(main): release 3.4.5",
                        "head": {
                            "ref": "release-please--branches--main",
                            "sha": "a" * 40,
                        },
                    }
                ]
            )
        if path.endswith("/actions/workflows/deploy-cvi.yml/runs"):
            assert request.method == "GET"
            runs = (
                [
                    {
                        "id": 99,
                        "status": "waiting",
                        "conclusion": None,
                        "head_sha": "old",
                        "display_title": "old release",
                        "created_at": "2026-07-21T00:00:00Z",
                        "html_url": "https://github.test/run/99",
                    }
                ]
                if active_run
                else []
            )
            return _response({"workflow_runs": runs})
        if path.endswith("/pulls/10"):
            assert request.method == "GET"
            return _response(
                {
                    "number": 10,
                    "title": "chore(main): release 3.4.5",
                    "body": (
                        "## 3.4.5\n* change "
                        "(https://github.com/Tavus-Engineering/realtime-replica/issues/42)"
                    ),
                    "html_url": "https://github.test/pr/10",
                    "mergeable_state": "clean",
                    "head": {
                        "ref": "release-please--branches--main",
                        "sha": "a" * 40,
                    },
                }
            )
        if path.endswith(f"/commits/{'a' * 40}/check-runs"):
            assert request.method == "GET"
            return _response(
                {
                    "check_runs": [
                        {
                            "name": "validate",
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "https://github.test/check/1",
                        }
                    ]
                }
            )
        if path.endswith("/pulls/10/reviews"):
            assert request.method == "GET"
            return _response([])
        if path.endswith("/pulls/10/merge"):
            assert request.method == "PUT"
            assert json.loads(request.content) == {
                "sha": "a" * 40,
                "merge_method": "squash",
            }
            return _response(
                {
                    "merged": True,
                    "sha": "b" * 40,
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def test_prepare_is_read_only_and_blocks_stale_waiting_run():
    transport = httpx.MockTransport(_github_handler(active_run=True))
    with DeploymentCaptainClient(token="token", transport=transport) as client:
        plan = client.prepare_release("cvi")

    assert plan["ready_to_start"] is False
    assert "active run(s): 99" in plan["blockers"][0]
    assert plan["release_pr"]["head_sha"] == "a" * 40
    assert plan["confirmation"] == "deploy"
    assert "authors" not in plan
    assert "announcement" not in plan


def test_prepare_ready_when_checks_clean_and_no_active_run():
    transport = httpx.MockTransport(_github_handler(active_run=False))
    with DeploymentCaptainClient(token="token", transport=transport) as client:
        plan = client.prepare_release("cvi")
    assert plan["ready_to_start"] is True
    assert plan["blockers"] == []


def test_start_revalidates_exact_release_and_needs_only_deploy_confirmation():
    transport = httpx.MockTransport(_github_handler(active_run=False))
    with DeploymentCaptainClient(token="token", transport=transport) as client:
        result = client.start_release("cvi", 10, "a" * 40, "deploy")

    assert result["started"] is True
    assert result["merge_commit_sha"] == "b" * 40
    assert "acknowledgement_url" not in result


def test_start_rejects_any_other_confirmation_before_merge():
    transport = httpx.MockTransport(_github_handler(active_run=False))
    with (
        DeploymentCaptainClient(token="token", transport=transport) as client,
        pytest.raises(RuntimeError, match="Confirmation must be exactly: deploy"),
    ):
        client.start_release("cvi", 10, "a" * 40, "start")


def test_launch_payload_has_short_confirmation_and_no_acknowledgement():
    github_handler = _github_handler(active_run=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "centaur.test":
            captured.update(json.loads(request.content))
            return _response({"run_id": "wf-1", "status": "queued", "created": True}, 201)
        return github_handler(request)

    transport = httpx.MockTransport(handler)
    with DeploymentCaptainClient(
        token="token",
        transport=transport,
        centaur_api_url="https://centaur.test",
    ) as client:
        result = client.launch_release(
            "cvi",
            10,
            "a" * 40,
            "deploy",
            "C123",
            "1234.5",
        )

    assert result["launched"] is True
    assert captured["input"]["confirmation"] == "deploy"
    assert "acknowledgement_url" not in captured["input"]
    assert set(captured["input"]) == {
        "service",
        "pr_number",
        "head_sha",
        "confirmation",
        "slack_channel",
        "slack_thread_ts",
    }


def test_rerun_failed_jobs_is_bound_to_exact_existing_run_and_sha():
    head_sha = "b" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/actions/runs/700") and request.method == "GET":
            return _response(
                {
                    "id": 700,
                    "path": ".github/workflows/build-test-deploy-staging-prod-region.yml@refs/heads/main",
                    "head_sha": head_sha,
                    "status": "completed",
                    "conclusion": "failure",
                }
            )
        if path.endswith("/actions/runs/700/rerun-failed-jobs") and request.method == "POST":
            return _response({}, 201)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    transport = httpx.MockTransport(handler)
    with DeploymentCaptainClient(token="token", transport=transport) as client:
        result = client.rerun_failed_jobs(
            "rqh",
            700,
            head_sha,
            f"RERUN FAILED RQH RUN 700 AT {head_sha}",
        )

    assert result == {"rerun_started": True, "run_id": 700, "head_sha": head_sha}


def test_rerun_failed_jobs_rejects_wrong_sha_before_dispatch():
    head_sha = "b" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs/700"):
            return _response(
                {
                    "id": 700,
                    "path": ".github/workflows/build-test-deploy-staging-prod-region.yml@refs/heads/main",
                    "head_sha": "c" * 40,
                    "status": "completed",
                    "conclusion": "failure",
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    transport = httpx.MockTransport(handler)
    with (
        DeploymentCaptainClient(token="token", transport=transport) as client,
        pytest.raises(RuntimeError, match="head SHA"),
    ):
        client.rerun_failed_jobs(
            "rqh",
            700,
            head_sha,
            f"RERUN FAILED RQH RUN 700 AT {head_sha}",
        )
