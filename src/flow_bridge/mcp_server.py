from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .accounts import list_account_snapshots
from .generation import VideoGenerationSpec, generate_video_once
from .health import doctor, run_canary
from .jobs import JobState, JobStore

server = MCPServer(
    name="flow-bridge",
    title="Flow Bridge",
    description="Semantic MCP control plane for Google Flow using a local authenticated browser profile.",
    version="0.1.0.dev0",
    instructions=(
        "Use health/status tools before generation. flow_video_generate may spend Google Flow credits. "
        "Generation is idempotent by request_id and v0 permits only one Veo Lite output per request. "
        "flow_canary never submits a generation but records a durable local canary job."
    ),
)


def _public_doctor(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"profile_dir", "browser_executable"}
    }


def _jobs_payload(*, states: list[JobState] | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return [
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
        for row in JobStore().list(states=states, limit=limit)
    ]


def _job_payload(job_id: str) -> dict[str, Any]:
    store = JobStore()
    row = store.get(job_id)
    if row is None:
        return {"status": "not_found", "job_id": job_id}
    return {
        "status": "ok",
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
            for event in store.events(row.job_id)
        ],
    }


@server.tool(
    name="flow_accounts_status",
    description="List local Flow profiles and browser compatibility without exposing Google account emails.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
)
def flow_accounts_status(browser: str | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "accounts": [snapshot.to_dict() for snapshot in list_account_snapshots(browser)],
    }


@server.tool(
    name="flow_doctor",
    description="Bootstrap Google Flow without generating and return a privacy-safe browser/session health report.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True),
)
async def flow_doctor(
    profile: str | None = None,
    browser: str | None = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    return _public_doctor(await doctor(profile, browser, headless=headless))


@server.tool(
    name="flow_canary",
    description="Run a durable no-generation Flow bootstrap canary. This does not spend generation credits.",
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True),
)
async def flow_canary(
    request_id: str,
    profile: str | None = None,
    browser: str | None = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    result = await run_canary(
        profile=profile,
        browser=browser,
        request_id=request_id,
        headless=headless,
    )
    if isinstance(result.get("doctor"), dict):
        result = {**result, "doctor": _public_doctor(result["doctor"])}
    return result


@server.tool(
    name="flow_metrics",
    description="Return durable Flow Bridge job metrics and unresolved job count.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
)
def flow_metrics() -> dict[str, Any]:
    store = JobStore()
    return {
        "status": "ok",
        **store.stats(),
        "accounts": [snapshot.to_dict() for snapshot in list_account_snapshots()],
    }


@server.tool(
    name="flow_jobs_list",
    description="List durable Flow Bridge jobs without returning stored prompt payloads.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
)
def flow_jobs_list(limit: int = 50) -> dict[str, Any]:
    bounded = max(1, min(limit, 500))
    return {"status": "ok", "jobs": _jobs_payload(limit=bounded)}


@server.tool(
    name="flow_jobs_unresolved",
    description="List jobs whose submission or remote state still needs reconciliation.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
)
def flow_jobs_unresolved() -> dict[str, Any]:
    states = [JobState.SUBMITTING, JobState.GENERATING, JobState.UNKNOWN_STATE]
    return {"status": "ok", "jobs": _jobs_payload(states=states, limit=500)}


@server.tool(
    name="flow_job_status",
    description="Inspect one durable Flow Bridge job and its event journal. Payload/prompt content is not returned.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
)
def flow_job_status(job_id: str) -> dict[str, Any]:
    return _job_payload(job_id)


@server.tool(
    name="flow_video_generate",
    description=(
        "Generate exactly one Veo Lite video in an existing Google Flow project. "
        "This may spend Flow credits. Reusing the same request_id never submits twice."
    ),
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True),
)
async def flow_video_generate(
    prompt: str,
    project_id: str,
    request_id: str,
    profile: str | None = None,
    aspect: str = "9:16",
    browser: str | None = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    spec = VideoGenerationSpec(
        prompt=prompt,
        project_id=project_id,
        request_id=request_id,
        profile=profile,
        model="veo-lite",
        aspect=aspect,
        count=1,
    )
    outcome = await generate_video_once(spec, browser=browser, headless=headless)
    return {
        "status": outcome.status,
        "job_id": outcome.job.job_id,
        "state": outcome.job.state.value,
        "account": outcome.job.account,
        "attempt": outcome.job.attempt,
        "error_type": outcome.job.error_type,
        "artifact": str(outcome.artifact) if outcome.artifact else None,
        "media_id": outcome.media_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Flow Bridge MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.environ.get("FLOW_BRIDGE_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("FLOW_BRIDGE_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FLOW_BRIDGE_MCP_PORT", "8765")))
    parser.add_argument("--path", default=os.environ.get("FLOW_BRIDGE_MCP_PATH", "/mcp"))
    args = parser.parse_args()

    if args.transport == "stdio":
        server.run("stdio")
        return
    server.run(
        "streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        stateless_http=False,
        session_idle_timeout=1800,
    )


if __name__ == "__main__":
    main()
