"""CLI entry points for Watch Agent integration tools."""

# ruff: noqa: E402

from dotenv import load_dotenv

load_dotenv()

import json
from typing import Any

import typer

from .client import IntegrationToolsClient


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _health_payload(tool: str, operation) -> dict[str, Any]:
    try:
        details = operation()
        return {"ok": True, "tool": tool, "error": None, "details": details}
    except Exception as exc:
        return {"ok": False, "tool": tool, "error": str(exc), "details": {}}


def _mcp_app(server: str, help_text: str) -> typer.Typer:
    app = typer.Typer(name=server, help=help_text)

    @app.command("health")
    def health() -> None:
        """Assert hosted MCP connectivity, authentication, and discovery."""
        payload = _health_payload(
            server,
            lambda: IntegrationToolsClient().mcp_health(server),
        )
        _print(payload)
        if not payload["ok"]:
            raise typer.Exit(1)

    @app.command("tools")
    def tools() -> None:
        """List the hosted MCP tools currently exposed."""
        _print(IntegrationToolsClient().mcp_tools(server))

    @app.command("call")
    def call(
        tool_name: str = typer.Argument(..., help="Hosted MCP tool name"),
        arguments: str = typer.Argument("{}", help="JSON object of tool arguments"),
    ) -> None:
        """Call one hosted MCP tool with JSON arguments."""
        parsed = json.loads(arguments)
        if not isinstance(parsed, dict):
            raise typer.BadParameter("arguments must decode to a JSON object")
        _print(IntegrationToolsClient().mcp_call(server, tool_name, parsed))

    return app


braintrust_app = _mcp_app("braintrust", "Braintrust hosted MCP tools")
coda_app = _mcp_app("coda", "Superhuman Docs hosted MCP tools")
logrocket_app = _mcp_app("logrocket", "LogRocket hosted MCP tools")

github_app = typer.Typer(name="github", help="GitHub API health and read-only fallback")


@github_app.command("health")
def github_health() -> None:
    """Assert GitHub connectivity and authentication used by gh."""
    payload = _health_payload("github", IntegrationToolsClient().github_health)
    _print(payload)
    if not payload["ok"]:
        raise typer.Exit(1)


@github_app.command("get")
def github_get(path: str = typer.Argument(..., help="GitHub API path beginning with /")) -> None:
    """Make a read-only GET request to GitHub's API."""
    _print(IntegrationToolsClient().github_get(path))
