"""CLI for the Tavus API tool."""

# ruff: noqa: E402

from dotenv import load_dotenv

load_dotenv()

import json

import typer
from rich.console import Console

from .client import TavusApiClient

app = typer.Typer(name="tavus-api", help="Read-only Tavus public API client")
console = Console()


def _print(data: object, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2))
    else:
        console.print_json(json.dumps(data))


@app.command()
def get(
    path: str = typer.Argument(..., help="Public API path, e.g. /v2/conversations"),
    env: str = typer.Option("prod", "--env", "-e", help="prod, staging/test, or stg"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Read an arbitrary Tavus public API path."""
    with TavusApiClient() as client:  # type: ignore[attr-defined]
        _print(client.get(path, env=env), json_output)


@app.command()
def conversation(
    conversation_id: str = typer.Argument(..., help="Conversation ID"),
    env: str = typer.Option("prod", "--env", "-e", help="prod, staging/test, or stg"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Fetch one conversation."""
    client = TavusApiClient()
    try:
        _print(client.get_conversation(conversation_id, env=env), json_output)
    finally:
        client.close()


@app.command()
def persona(
    persona_id: str = typer.Argument(..., help="Persona ID"),
    env: str = typer.Option("prod", "--env", "-e", help="prod, staging/test, or stg"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Fetch one persona."""
    client = TavusApiClient()
    try:
        _print(client.get_persona(persona_id, env=env), json_output)
    finally:
        client.close()


if __name__ == "__main__":
    app()
