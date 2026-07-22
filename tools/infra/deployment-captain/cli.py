"""CLI for guarded CVI and RQH deployment orchestration."""

# ruff: noqa: E402

from dotenv import load_dotenv

load_dotenv()

import json

import typer
from rich.console import Console

from .client import DeploymentCaptainClient

app = typer.Typer(name="deployment-captain", help="Prepare and supervise CVI/RQH releases")
console = Console()


def _print(data: object, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2))
    else:
        console.print_json(json.dumps(data))


@app.command()
def prepare(
    service: str = typer.Argument(..., help="cvi or rqh"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Prepare a read-only release plan without starting anything."""
    with DeploymentCaptainClient() as client:
        _print(client.prepare_release(service), json_output)


@app.command()
def launch(
    service: str = typer.Argument(..., help="cvi or rqh"),
    pr_number: int = typer.Option(..., "--pr"),
    head_sha: str = typer.Option(..., "--head-sha"),
    confirmation: str = typer.Option(..., "--confirmation"),
    slack_channel: str = typer.Option(..., "--slack-channel"),
    slack_thread_ts: str = typer.Option(..., "--slack-thread-ts"),
    soak_minutes: int = typer.Option(10, "--soak-minutes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Launch the durable workflow after the user repeats the exact confirmation."""
    with DeploymentCaptainClient() as client:
        _print(
            client.launch_release(
                service,
                pr_number,
                head_sha,
                confirmation,
                slack_channel,
                slack_thread_ts,
                soak_minutes,
            ),
            json_output,
        )


@app.command()
def status(
    service: str = typer.Argument(..., help="cvi or rqh"),
    merge_commit_sha: str = typer.Option(..., "--merge-sha"),
    run_id: int | None = typer.Option(None, "--run-id"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Inspect one exact release workflow run."""
    with DeploymentCaptainClient() as client:
        _print(client.release_run_status(service, merge_commit_sha, run_id), json_output)


@app.command("cancel")
def cancel_run(
    service: str = typer.Argument(..., help="cvi or rqh"),
    run_id: int = typer.Option(..., "--run-id"),
    confirmation: str = typer.Option(..., "--confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Cancel one exact deployment run after explicit confirmation."""
    with DeploymentCaptainClient() as client:
        _print(client.cancel_release_run(service, run_id, confirmation), json_output)


@app.command("rerun-failed")
def rerun_failed(
    service: str = typer.Argument(..., help="cvi or rqh"),
    run_id: int = typer.Option(..., "--run-id"),
    head_sha: str = typer.Option(..., "--head-sha"),
    confirmation: str = typer.Option(..., "--confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Rerun failed jobs on one exact completed deployment run."""
    with DeploymentCaptainClient() as client:
        _print(
            client.rerun_failed_jobs(service, run_id, head_sha, confirmation),
            json_output,
        )


@app.command("approve")
def approve(
    service: str = typer.Argument(..., help="cvi or rqh"),
    run_id: int = typer.Option(..., "--run-id"),
    environment: list[str] = typer.Option(..., "--environment"),  # noqa: B008
    comment: str = typer.Option(..., "--comment"),
    confirmation: str = typer.Option(..., "--confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Approve exact gates with a distinct eligible GitHub identity."""
    with DeploymentCaptainClient() as client:
        _print(
            client.approve_production_gates(
                service,
                run_id,
                environment,
                comment,
                confirmation,
            ),
            json_output,
        )


@app.command("rollback-cerebrium")
def rollback_cerebrium(
    phoenix3_build_id: str = typer.Option(..., "--phoenix3-build-id"),
    phoenix4_build_id: str = typer.Option(..., "--phoenix4-build-id"),
    incident_url: str = typer.Option(..., "--incident-url"),
    request_id: str = typer.Option(..., "--request-id"),
    confirmation: str = typer.Option(..., "--confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Dispatch exact-build Phoenix 3 then Phoenix 4 emergency rollback."""
    with DeploymentCaptainClient() as client:
        _print(
            client.dispatch_cerebrium_rollback(
                phoenix3_build_id,
                phoenix4_build_id,
                incident_url,
                request_id,
                confirmation,
            ),
            json_output,
        )


@app.command("facade-status")
def facade_status(
    repository_service: str = typer.Argument(..., help="cvi or rqh"),
    workflow_file: str = typer.Option(..., "--workflow-file"),
    request_id: str = typer.Option(..., "--request-id"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output JSON"),
) -> None:
    """Inspect one exact routing or rollback facade run."""
    with DeploymentCaptainClient() as client:
        _print(
            client.workflow_dispatch_status(
                repository_service,
                workflow_file,
                request_id,
            ),
            json_output,
        )


if __name__ == "__main__":
    app()
