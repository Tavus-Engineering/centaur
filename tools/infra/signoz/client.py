"""SigNoz MCP-backed observability client."""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

from centaur_sdk import secret

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_CLIENT_NAME = "centaur-signoz"
MCP_CLIENT_VERSION = "0.1.0"
DEFAULT_MCP_URL = "https://mcp.us.signoz.cloud/mcp"
_ALLOWED_MCP_HOSTS = {
    "mcp.us.signoz.cloud",
    "mcp.us2.signoz.cloud",
    "mcp.eu.signoz.cloud",
    "mcp.eu2.signoz.cloud",
    "mcp.in.signoz.cloud",
    "mcp.in2.signoz.cloud",
}


def _optional_config(name: str) -> str:
    value = secret(name, "").strip()
    return "" if value == name else value


class SignozClient:
    """Client that exposes hosted SigNoz MCP tools through Centaur REST tools."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    def _api_key(self) -> str:
        api_key = secret("SIGNOZ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SIGNOZ_API_KEY is required.")
        return api_key

    def _signoz_url(self) -> str:
        signoz_url = _optional_config("SIGNOZ_URL").rstrip("/")
        if not signoz_url:
            raise RuntimeError("SIGNOZ_URL is required for SigNoz MCP header auth.")
        return signoz_url

    def _mcp_url(self) -> str:
        mcp_url = (_optional_config("SIGNOZ_MCP_URL") or DEFAULT_MCP_URL).strip()
        parsed = urlparse(mcp_url)
        if parsed.scheme != "https" or parsed.netloc not in _ALLOWED_MCP_HOSTS:
            allowed = ", ".join(sorted(_ALLOWED_MCP_HOSTS))
            raise RuntimeError(f"Unsupported SIGNOZ_MCP_URL host. Allowed hosts: {allowed}.")
        return mcp_url

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "SIGNOZ-API-KEY": self._api_key(),
            "X-SigNoz-URL": self._signoz_url(),
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    def _initialize(self, client: httpx.Client, mcp_url: str) -> str:
        init_envelope = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": MCP_CLIENT_NAME, "version": MCP_CLIENT_VERSION},
            },
        }
        response = client.post(mcp_url, headers=self._headers(), json=init_envelope)
        if response.status_code in (401, 403):
            raise RuntimeError(f"SigNoz MCP auth failed ({response.status_code}).")
        response.raise_for_status()
        envelope = _decode_mcp_envelope(response)
        if "error" in envelope:
            raise RuntimeError(f"SigNoz MCP initialize error: {envelope['error']}")

        session_id = response.headers.get("mcp-session-id") or ""
        ack = client.post(
            mcp_url,
            headers=self._headers(session_id),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        if ack.status_code >= 400:
            raise RuntimeError(f"SigNoz MCP initialize ack failed ({ack.status_code}).")
        return session_id

    def _mcp_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        mcp_url = self._mcp_url()
        with httpx.Client(timeout=self.timeout) as client:
            session_id = self._initialize(client, mcp_url)
            envelope = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params or {},
            }
            response = client.post(mcp_url, headers=self._headers(session_id), json=envelope)
            if response.status_code in (401, 403):
                raise RuntimeError(f"SigNoz MCP auth failed ({response.status_code}).")
            response.raise_for_status()
            result = _decode_mcp_envelope(response)
        if "error" in result:
            raise RuntimeError(f"SigNoz MCP error: {result['error']}")
        return result

    def _call_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        envelope = self._mcp_request(
            "tools/call",
            {"name": tool_name, "arguments": _drop_empty(arguments)},
        )
        result = envelope.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(f"SigNoz tool error: {result}")
        return _extract_tool_payload(result)

    def ready(self) -> dict[str, Any]:
        """Check whether the hosted SigNoz MCP server is reachable and authenticated."""
        try:
            tools = self.tools()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "mcp_url": self._mcp_url(),
            "signoz_url": self._signoz_url(),
            "tool_count": len(tools.get("tools", [])),
        }

    def tools(self) -> dict[str, Any]:
        """List available SigNoz MCP tools."""
        envelope = self._mcp_request("tools/list")
        result = envelope.get("result") or {}
        return {"tools": result.get("tools", [])}

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a SigNoz MCP tool by name with raw arguments."""
        return self._call_mcp_tool(tool_name, arguments or {})

    def search_logs(
        self,
        searchText: str = "",
        timeRange: str = "1h",
        service: str = "",
        severity: str = "",
        filter: str = "",
        limit: int = 100,
        searchContext: str = "",
    ) -> Any:
        """Search SigNoz logs through signoz_search_logs."""
        return self._call_mcp_tool(
            "signoz_search_logs",
            {
                "searchText": searchText,
                "timeRange": timeRange,
                "service": service,
                "severity": severity,
                "filter": filter,
                "limit": max(1, min(limit, 500)),
                "searchContext": searchContext,
            },
        )

    def search_traces(
        self,
        service: str = "",
        operation: str = "",
        timeRange: str = "1h",
        filter: str = "",
        error: bool | None = None,
        limit: int = 100,
        searchContext: str = "",
    ) -> Any:
        """Search SigNoz traces through signoz_search_traces."""
        return self._call_mcp_tool(
            "signoz_search_traces",
            {
                "service": service,
                "operation": operation,
                "timeRange": timeRange,
                "filter": filter,
                "error": error,
                "limit": max(1, min(limit, 500)),
                "searchContext": searchContext,
            },
        )

    def get_field_keys(
        self,
        signal: str = "logs",
        fieldContext: str = "resource",
        searchText: str = "",
        limit: int = 100,
    ) -> Any:
        """List SigNoz field keys for logs, traces, metrics, or meter data."""
        return self._call_mcp_tool(
            "signoz_get_field_keys",
            {
                "signal": signal,
                "fieldContext": fieldContext,
                "searchText": searchText,
                "limit": max(1, min(limit, 500)),
            },
        )

    def get_field_values(
        self,
        fieldKey: str,
        signal: str = "logs",
        fieldContext: str = "resource",
        searchText: str = "",
        limit: int = 100,
    ) -> Any:
        """List SigNoz values for a field key."""
        return self._call_mcp_tool(
            "signoz_get_field_values",
            {
                "signal": signal,
                "fieldContext": fieldContext,
                "fieldKey": fieldKey,
                "searchText": searchText,
                "limit": max(1, min(limit, 500)),
            },
        )

    def aggregate_logs(
        self,
        aggregation: str = "count",
        aggregateOn: str = "",
        requestType: str = "scalar",
        timeRange: str = "1h",
        filter: str = "",
        groupBy: list[str] | None = None,
        limit: int = 20,
        searchContext: str = "",
    ) -> Any:
        """Aggregate SigNoz logs through signoz_aggregate_logs."""
        return self._call_mcp_tool(
            "signoz_aggregate_logs",
            {
                "aggregation": aggregation,
                "aggregateOn": aggregateOn,
                "requestType": requestType,
                "timeRange": timeRange,
                "filter": filter,
                "groupBy": groupBy or [],
                "limit": max(1, min(limit, 200)),
                "searchContext": searchContext,
            },
        )

    # Aliases that match the hosted MCP tool names agents may already know.
    def signoz_search_logs(self, **kwargs: Any) -> Any:
        """Alias for search_logs."""
        return self.search_logs(**kwargs)

    def signoz_search_traces(self, **kwargs: Any) -> Any:
        """Alias for search_traces."""
        return self.search_traces(**kwargs)

    def signoz_get_field_keys(self, **kwargs: Any) -> Any:
        """Alias for get_field_keys."""
        return self.get_field_keys(**kwargs)

    def signoz_get_field_values(self, **kwargs: Any) -> Any:
        """Alias for get_field_values."""
        return self.get_field_values(**kwargs)

    def signoz_aggregate_logs(self, **kwargs: Any) -> Any:
        """Alias for aggregate_logs."""
        return self.aggregate_logs(**kwargs)


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_empty(item)
            for key, item in value.items()
            if item is not None and item != "" and item != []
        }
    if isinstance(value, list):
        return [_drop_empty(item) for item in value]
    return value


def _decode_mcp_envelope(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "text/event-stream" in content_type:
        latest: dict[str, Any] | None = None
        for event_block in text.split("\n\n"):
            data_lines = [
                line[len("data:") :].lstrip(" ")
                for line in event_block.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            try:
                parsed = json.loads("\n".join(data_lines).strip())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                latest = parsed
        if latest is None:
            raise RuntimeError("SigNoz MCP returned an empty SSE stream.")
        return latest
    if not text.strip():
        return {}
    return response.json()


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


def _client() -> SignozClient:
    return SignozClient()
