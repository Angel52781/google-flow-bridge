from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import click

from .accounts import list_account_snapshots
from .generation import VideoGenerationSpec, generate_video_once
from .health import doctor as run_doctor
from .health import run_canary
from .jobs import JobState, JobStore


@click.group()
def main() -> None:
    """Control Google Flow through a local, agent-friendly browser bridge."""


@main.group()
def accounts() -> None:
    """Inspect locally configured Flow accounts/profiles."""


@accounts.command("list")
@click.option(
    "--browser",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="Optional Chromium-family executable used for compatibility checks.",
)
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def accounts_list(browser: Path | None, json_output: bool) -> None:
    snapshots = list_account_snapshots(browser)
    payload = [snapshot.to_dict() for snapshot in snapshots]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not snapshots:
        click.echo("No Flow profiles found.")
        return
    for item in snapshots:
        default = "*" if item.is_default else " "
        compatible = (
            "yes" if item.runtime_compatible is True else "no" if item.runtime_compatible is False else "unknown"
        )
        click.echo(
            f"{default} {item.name}: cookies={item.cookies_present} "
            f"profile={item.profile_version or 'unknown'} runtime={item.runtime_version or 'unknown'} "
            f"compatible={compatible} strategy={item.browser_strategy or 'unset'}"
        )


@main.group()
def generate() -> None:
    """Submit exactly-once generation jobs through Google Flow."""


@generate.command("video")
@click.argument("prompt")
@click.option("--profile", default=None, help="Specific gflow profile; default is scheduler-selected.")
@click.option(
    "--browser",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="Explicit Chromium-family executable.",
)
@click.option("--model", type=click.Choice(["veo-lite"]), default="veo-lite", show_default=True)
@click.option("--aspect", type=click.Choice(["9:16", "16:9"]), default="9:16", show_default=True)
@click.option("--duration", type=click.Choice(["4", "6", "8"]), default=None)
@click.option("--project-id", required=True, help="Existing Google Flow project UUID.")
@click.option("--request-id", default=None, help="Stable idempotency key. Same key never submits twice.")
@click.option("--headless/--headed", default=None, help="Override FLOW_BRIDGE_HEADLESS for this run.")
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def generate_video(
    prompt: str,
    profile: str | None,
    browser: Path | None,
    model: str,
    aspect: str,
    duration: str | None,
    project_id: str,
    request_id: str | None,
    headless: bool | None,
    json_output: bool,
) -> None:
    """Generate one video with no automatic retries after the spend boundary."""
    spec = VideoGenerationSpec(
        prompt=prompt,
        profile=profile,
        model=model,
        aspect=aspect,
        duration=int(duration) if duration is not None else None,
        count=1,
        project_id=project_id,
        request_id=request_id,
    )
    try:
        outcome = asyncio.run(
            generate_video_once(
                spec,
                browser=str(browser) if browser else None,
                headless=headless,
            )
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"status": "fail", "error_type": type(exc).__name__}))
        raise click.ClickException(f"video generation failed before durable classification: {type(exc).__name__}") from exc

    payload = {
        "status": outcome.status,
        "job_id": outcome.job.job_id,
        "state": outcome.job.state.value,
        "account": outcome.job.account,
        "attempt": outcome.job.attempt,
        "error_type": outcome.job.error_type,
        "artifact": str(outcome.artifact) if outcome.artifact else None,
        "media_id": outcome.media_id,
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        click.echo(
            f"FLOW_BRIDGE_VIDEO {outcome.status.upper()} job={outcome.job.job_id} "
            f"state={outcome.job.state.value} attempts={outcome.job.attempt}"
        )
        if outcome.artifact:
            click.echo(f"artifact: {outcome.artifact}")


@main.group()
def jobs() -> None:
    """Inspect durable Flow Bridge jobs."""


@jobs.command("list")
@click.option("--limit", type=click.IntRange(1, 500), default=50, show_default=True)
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def jobs_list(limit: int, json_output: bool) -> None:
    rows = JobStore().list(limit=limit)
    payload = [
        {
            "job_id": row.job_id,
            "request_id": row.request_id,
            "kind": row.kind,
            "state": row.state.value,
            "account": row.account,
            "attempt": row.attempt,
            "error_type": row.error_type,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    for row in payload:
        click.echo(
            f"{row['job_id']} {row['state']} {row['kind']} "
            f"account={row['account'] or '-'} attempts={row['attempt']}"
        )


@jobs.command("unresolved")
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def jobs_unresolved(json_output: bool) -> None:
    rows = JobStore().list(
        states=[JobState.SUBMITTING, JobState.GENERATING, JobState.UNKNOWN_STATE],
        limit=500,
    )
    payload = [
        {
            "job_id": row.job_id,
            "request_id": row.request_id,
            "state": row.state.value,
            "account": row.account,
            "attempt": row.attempt,
            "error_type": row.error_type,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not payload:
        click.echo("No unresolved jobs.")
        return
    for row in payload:
        click.echo(
            f"{row['job_id']} {row['state']} account={row['account'] or '-'} "
            f"attempts={row['attempt']} error={row['error_type'] or '-'}"
        )


@jobs.command("inspect")
@click.argument("job_id")
@click.option("--include-payload", is_flag=True, help="Include stored job payload explicitly.")
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def jobs_inspect(job_id: str, include_payload: bool, json_output: bool) -> None:
    store = JobStore()
    row = store.get(job_id)
    if row is None:
        raise click.ClickException(f"Unknown job: {job_id}")
    payload: dict[str, Any] = {
        "job_id": row.job_id,
        "request_id": row.request_id,
        "kind": row.kind,
        "state": row.state.value,
        "account": row.account,
        "attempt": row.attempt,
        "error_type": row.error_type,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "events": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "state": event.state.value if event.state else None,
                "metadata": event.metadata,
                "created_at": event.created_at,
            }
            for event in store.events(job_id)
        ],
    }
    if include_payload:
        payload["payload"] = row.payload
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    click.echo(f"{row.job_id}: {row.state.value} ({row.kind})")
    click.echo(f"account: {row.account or '-'} | attempts: {row.attempt} | error: {row.error_type or '-'}")
    for event in payload["events"]:
        click.echo(f"  {event['event_id']} {event['event_type']} {event['state'] or '-'}")


@main.command()
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def metrics(json_output: bool) -> None:
    """Summarize durable job/account health without exposing prompts or account emails."""
    store = JobStore()
    payload = {
        **store.stats(),
        "accounts": [snapshot.to_dict() for snapshot in list_account_snapshots()],
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    click.echo(f"jobs={payload['total_jobs']} attempts={payload['total_attempts']} unresolved={payload['unresolved']}")
    for state, count in payload["by_state"].items():
        click.echo(f"  {state}: {count}")


@main.command()
@click.option("--profile", default=None, help="Specific profile; default is scheduler-selected.")
@click.option(
    "--browser",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="Explicit Chromium-family executable.",
)
@click.option("--request-id", default=None, help="Optional idempotency key for this canary.")
@click.option("--headless/--headed", default=None, help="Override FLOW_BRIDGE_HEADLESS for this run.")
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def canary(
    profile: str | None,
    browser: Path | None,
    request_id: str | None,
    headless: bool | None,
    json_output: bool,
) -> None:
    """Run a durable, zero-generation Flow bootstrap canary."""
    request_id = request_id or f"canary-{uuid.uuid4().hex}"
    try:
        result = asyncio.run(
            run_canary(
                profile=profile,
                browser=str(browser) if browser else None,
                request_id=request_id,
                headless=headless,
            )
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"status": "fail", "error_type": type(exc).__name__}))
        raise click.ClickException(f"canary failed: {type(exc).__name__}") from exc
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False))
    else:
        click.echo(f"FLOW_BRIDGE_CANARY {result['status'].upper()} job={result['job_id']} state={result['state']}")


@main.command()
@click.option("--profile", default=None, help="gflow profile name.")
@click.option(
    "--browser",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="Explicit Chromium-family executable. Overrides auto-detection.",
)
@click.option("--headless/--headed", default=None, help="Override FLOW_BRIDGE_HEADLESS for this run.")
@click.option("--json-output", is_flag=True, help="Emit machine-readable JSON.")
def doctor(profile: str | None, browser: Path | None, headless: bool | None, json_output: bool) -> None:
    """Verify browser/profile compatibility and bootstrap Flow without generating."""
    try:
        result = asyncio.run(run_doctor(profile, str(browser) if browser else None, headless=headless))
    except Exception as exc:  # CLI boundary: preserve concrete type without leaking secrets.
        if json_output:
            click.echo(json.dumps({"status": "fail", "error_type": type(exc).__name__}))
        raise click.ClickException(f"doctor failed: {type(exc).__name__}") from exc

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False))
        return

    click.echo("FLOW_BRIDGE_DOCTOR PASS")
    click.echo(f"profile: {result['profile']}")
    click.echo(f"browser: {result['browser_executable']}")
    click.echo(f"profile version: {result['profile_browser_version']}")
    click.echo(f"browser version: {result['runtime_browser_version']}")
    click.echo(f"flow: {result['page_url']}")
    click.echo(f"transport: {result['transport']}")
