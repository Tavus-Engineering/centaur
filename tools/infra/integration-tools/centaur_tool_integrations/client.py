"""Hosted MCP and GitHub health clients for Watch Agent integrations."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from centaur_sdk import secret

MCP_PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True)
class McpServer:
    name: str
    url: str
    token_env: str


MCP_SERVERS = {
    "braintrust": McpServer(
        name="braintrust",
        url="https://api.braintrust.dev/mcp",
        token_env="BRAINTRUST_API_KEY",
    ),
    "coda": McpServer(
        name="coda",
        url="https://docs.superhuman.com/apis/mcp",
        token_env="CODA_API_KEY",
    ),
    "logrocket": McpServer(
        name="logrocket",
        url="https://mcp.logrocket.com/mcp",
        token_env="LOGROCKET_API_TOKEN",
    ),
}


class IntegrationToolsClient:
    """Health and fallback access for hosted Watch Agent integrations."""

    def __init__(
        self,
        timeout: float = 120.0,
        client_factory: Callable[[], httpx.Client] | None = None,
    ):
        self.timeout = timeout
        self._client_factory = client_factory

    def _client(self) -> httpx.Client:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.Client(timeout=self.timeout)

    def _token(self, env_name: str) -> str:
        token = secret(env_name, "").strip()
        if not token:
            raise RuntimeError(f"{env_name} is required.")
        return token

    def _headers(self, server: McpServer, session_id: str = "") -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token(server.token_env)}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    def _post(
        self,
        client: httpx.Client,
        server: McpServer,
        payload: dict[str, Any],
        session_id: str = "",
    ) -> tuple[dict[str, Any], str]:
        response = client.post(
            server.url,
            headers=self._headers(server, session_id),
            json=payload,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(f"{server.name} MCP auth failed ({response.status_code}).")
        response.raise_for_status()
        return _decode_mcp_envelope(response), response.headers.get("mcp-session-id", "")

    def _mcp_request(
        self,
        server_name: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = _server(server_name)
        with self._client() as client:
            initialized, session_id = self._post(
                client,
                server,
                {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "centaur-watch-agent",
                            "version": "0.1.0",
                        },
                    },
                },
            )
            if "error" in initialized:
                raise RuntimeError(f"{server.name} MCP initialize failed: {initialized['error']}")

            acknowledged, _ = self._post(
                client,
                server,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                session_id,
            )
            if "error" in acknowledged:
                raise RuntimeError(
                    f"{server.name} MCP initialization ack failed: {acknowledged['error']}"
                )

            envelope, _ = self._post(
                client,
                server,
                {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": method,
                    "params": params or {},
                },
                session_id,
            )
        if "error" in envelope:
            raise RuntimeError(f"{server.name} MCP error: {envelope['error']}")
        return envelope

    def mcp_tools(self, server: str) -> dict[str, Any]:
        """List tools exposed by one hosted MCP server."""
        result = self._mcp_request(server, "tools/list").get("result") or {}
        tools = result.get("tools") or []
        return {
            "server": server,
            "tool_count": len(tools),
            "tools": tools,
        }

    def mcp_call(
        self,
        server: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call one tool on a hosted MCP server."""
        envelope = self._mcp_request(
            server,
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )
        result = envelope.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(f"{server} MCP tool failed: {result}")
        return _extract_tool_payload(result)

    def mcp_health(self, server: str) -> dict[str, Any]:
        """Verify hosted MCP authentication and tool discovery."""
        tools = self.mcp_tools(server)
        if tools["tool_count"] < 1:
            raise RuntimeError(f"{server} MCP returned no tools.")
        # Braintrust exposes its tool catalog before authentication. Exercise a
        # bounded read so a placeholder or revoked token cannot look healthy.
        if server == "braintrust":
            self.mcp_call(
                server,
                "list_recent_objects",
                {"object_type": "project", "limit": 1},
            )
        return {
            "status": "ready",
            "server": server,
            "tool_count": tools["tool_count"],
        }

    def github_health(self) -> dict[str, Any]:
        """Verify GitHub API authentication used by the gh CLI."""
        response = self._github_get("/rate_limit")
        resources = response.get("resources") or {}
        core = resources.get("core") or {}
        return {
            "status": "ready",
            "resource": "rate_limit",
            "limit": core.get("limit"),
            "remaining": core.get("remaining"),
        }

    def github_get(self, path: str) -> Any:
        """Make a read-only GET request to a GitHub API path."""
        return self._github_get(path)

    def _github_get(self, path: str) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("GitHub path must start with one slash.")
        token = self._token("GITHUB_TOKEN")
        with self._client() as client:
            response = client.get(
                f"https://api.github.com{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "centaur-watch-agent",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if response.status_code in (401, 403):
            raise RuntimeError(f"GitHub API auth failed ({response.status_code}).")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub API returned a non-object response.")
        return payload


def _server(name: str) -> McpServer:
    normalized = name.strip().lower()
    try:
        return MCP_SERVERS[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(MCP_SERVERS))
        raise ValueError(f"Unknown MCP server {name!r}; expected one of: {supported}.") from exc


def _decode_mcp_envelope(response: httpx.Response) -> dict[str, Any]:
    text = response.text
    if not text.strip():
        return {}
    if "text/event-stream" not in response.headers.get("content-type", ""):
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    latest: dict[str, Any] | None = None
    for event_block in text.split("\n\n"):
        data = "\n".join(
            line[len("data:") :].lstrip()
            for line in event_block.splitlines()
            if line.startswith("data:")
        ).strip()
        if not data:
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            latest = payload
    if latest is None:
        raise RuntimeError("MCP server returned an empty event stream.")
    return latest


def _extract_tool_payload(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    first_text: str | None = None
    for block in result.get("content", []) or []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = str(block.get("text") or "")
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if first_text is None:
                first_text = text
    if first_text is not None:
        return {"text": first_text}
    return result


def _client() -> IntegrationToolsClient:
    return IntegrationToolsClient()
