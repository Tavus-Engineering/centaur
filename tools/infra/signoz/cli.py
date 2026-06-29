"""CLI for the SigNoz MCP-backed tool."""

# ruff: noqa: E402

from dotenv import load_dotenv

load_dotenv()

import json

import typer
from rich.console import Console

from .client import SignozClient

app = typer.Typer(name="signoz", help="SigNoz MCP-backed observability queries")
console = Console()


def _print(data: object, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2))
    else:
        console.print_json(json.dumps(data))


@app.command()
def ready(json_output: bool = typer.Option(False, "--json", "-j")) -> None:
    """Check MCP connectivity."""
    _print(SignozClient().ready(), json_output)


@app.command()
def search_logs(
    query: str = typer.Argument("", help="Text to search in log bodies"),
    time_range: str = typer.Option("1h", "--time-range", "-t"),
    service: str = typer.Option("", "--service", "-s"),
    json_output: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Search logs."""
    _print(
        SignozClient().search_logs(searchText=query, timeRange=time_range, service=service),
        json_output,
    )


if __name__ == "__main__":
    app()
