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


def test_dispatch_traffic_rejects_non_handbook_fraction_without_api_call():
    def fail_if_called(request):
        raise AssertionError(f"unexpected request: {request}")

    transport = httpx.MockTransport(fail_if_called)
    with (
        DeploymentCaptainClient(token="token", transport=transport) as client,
        pytest.raises(RuntimeError, match="0 or 5"),
    ):
        client.dispatch_cvi_traffic(10, "request-1", "anything")


def test_approval_uses_distinct_approver_token():
    def handler(request):
        path = request.url.path
        if path.endswith("/actions/runs/700/pending_deployments") and request.method == "GET":
            assert request.headers["authorization"] == "Bearer initiator"
            return _response([{"environment": {"id": 9, "name": "manual-approval"}}])
        if path.endswith("/actions/runs/700/pending_deployments") and request.method == "POST":
            assert request.headers["authorization"] == "Bearer approver"
            return _response({"ok": True})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    transport = httpx.MockTransport(handler)
    with DeploymentCaptainClient(
        token="initiator", approver_token="approver", transport=transport
    ) as client:
        result = client.approve_production_gates(
            "rqh",
            700,
            ["manual-approval"],
            "Canary is healthy",
            "APPROVE RQH RUN 700 ENVIRONMENTS manual-approval",
        )

    assert result["approved"] is True


def test_dispatch_traffic_is_bound_to_request_confirmation():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    with DeploymentCaptainClient(token="token", transport=transport) as client:
        result = client.dispatch_cvi_traffic(
            5,
            "workflow-run-1-stage-5",
            "SET CVI STAGE TO 5 FOR workflow-run-1-stage-5",
        )
    assert result["dispatched"] is True
    assert seen[0]["inputs"]["stage_fraction"] == "5"
    assert seen[0]["inputs"]["request_id"] == "workflow-run-1-stage-5"
