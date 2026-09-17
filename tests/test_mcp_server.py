from __future__ import annotations

import asyncio

from flow_bridge.mcp_server import server


def test_mcp_surface_has_semantic_tools() -> None:
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "flow_accounts_status",
        "flow_doctor",
        "flow_canary",
        "flow_metrics",
        "flow_jobs_list",
        "flow_jobs_unresolved",
        "flow_job_status",
        "flow_video_generate",
    }


def test_generation_tool_is_marked_non_read_only_and_idempotent() -> None:
    tools = asyncio.run(server.list_tools())
    tool = next(item for item in tools if item.name == "flow_video_generate")
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.idempotent_hint is True


def test_canary_is_non_read_only_but_idempotent() -> None:
    tools = asyncio.run(server.list_tools())
    tool = next(item for item in tools if item.name == "flow_canary")
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.idempotent_hint is True


def test_status_tools_are_read_only() -> None:
    tools = asyncio.run(server.list_tools())
    names = {
        "flow_accounts_status",
        "flow_doctor",
        "flow_metrics",
        "flow_jobs_list",
        "flow_jobs_unresolved",
        "flow_job_status",
    }
    read_only = {
        item.name: item.annotations.read_only_hint if item.annotations else None
        for item in tools
        if item.name in names
    }
    assert read_only == {name: True for name in names}
