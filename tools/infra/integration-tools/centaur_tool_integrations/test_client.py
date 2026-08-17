from __future__ import annotations

import json
import sys
import types

import httpx
import pytest

if "centaur_sdk" not in sys.modules:
    sdk_module = types.ModuleType("centaur_sdk")
    sdk_module.secret = lambda name, default="": default  # type: ignore[attr-defined]
    sys.modules["centaur_sdk"] = sdk_module

from .client import IntegrationToolsClient, _decode_mcp_envelope


def _sse(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(payload)}\n\n",
    )


def test_mcp_health_handles_stateful_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("centaur_tool_integrations.client.secret", lambda name, default="": name)
    requests: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(
            (
                str(payload.get("method")),
                request.headers.get("mcp-session-id", ""),
                request.headers.get("authorization", ""),
            )
        )
        if payload.get("method") == "initialize":
            response = _sse({"jsonrpc": "2.0", "id": payload["id"], "result": {}})
            response.headers["mcp-session-id"] = "session-1"
            return response
        if payload.get("method") == "notifications/initialized":
            return httpx.Response(202)
        return _sse(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": [{"name": "search"}, {"name": "whoami"}]},
            }
        )

    client = IntegrationToolsClient(
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert client.mcp_health("coda") == {
        "status": "ready",
        "server": "coda",
        "tool_count": 2,
    }
    assert requests == [
        ("initialize", "", "Bearer CODA_API_KEY"),
        ("notifications/initialized", "session-1", "Bearer CODA_API_KEY"),
        ("tools/list", "session-1", "Bearer CODA_API_KEY"),
    ]


def test_braintrust_health_requires_authenticated_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = IntegrationToolsClient()
    monkeypatch.setattr(
        client,
        "mcp_tools",
        lambda server: {"server": server, "tool_count": 35, "tools": []},
    )
    calls: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        client,
        "mcp_call",
        lambda server, tool, arguments: calls.append((server, tool, arguments)),
    )

    assert client.mcp_health("braintrust") == {
        "status": "ready",
        "server": "braintrust",
        "tool_count": 35,
    }
    assert calls == [
        (
            "braintrust",
            "list_recent_objects",
            {"object_type": "project", "limit": 1},
        )
    ]


def test_decode_mcp_envelope_uses_latest_sse_event() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=(
            'event: message\ndata: {"step": 1}\n\n'
            'event: message\ndata: {"result": {"tools": []}}\n\n'
        ),
    )
    assert _decode_mcp_envelope(response) == {"result": {"tools": []}}


def test_github_get_rejects_absolute_or_scheme_relative_paths() -> None:
    client = IntegrationToolsClient()
    with pytest.raises(ValueError, match="one slash"):
        client.github_get("https://example.com")
    with pytest.raises(ValueError, match="one slash"):
        client.github_get("//example.com")
