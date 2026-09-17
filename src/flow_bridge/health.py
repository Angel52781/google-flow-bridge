from __future__ import annotations

from pathlib import Path
from typing import Any

from gflow_cli import profile_store
from gflow_cli.api.transports._common import flow_landing_kind, raise_if_known_landing
from gflow_cli.errors import AuthMissingError, FlowAppError

from .accounts import list_account_snapshots
from .browser_runtime import (
    BrowserRuntime,
    ExecutableFlowApiClient,
    assert_profile_compatible,
    resolve_headless,
)
from .jobs import JobState, JobStore
from .scheduler import AccountScheduler


def _profile_meta(name: str) -> profile_store.ProfileMeta:
    for meta in profile_store.list_profiles():
        if meta.name == name:
            return meta
    raise LookupError(f"Unknown gflow profile: {name}")


async def doctor(
    profile: str | None = None,
    browser: str | Path | None = None,
    *,
    headless: bool | None = None,
) -> dict[str, Any]:
    resolved = profile_store.resolve_profile(profile)
    meta = _profile_meta(resolved)
    runtime = BrowserRuntime.auto(browser)
    profile_version, runtime_version = assert_profile_compatible(meta.profile_dir, runtime.executable)

    async with ExecutableFlowApiClient(
        profile_dir=meta.profile_dir,
        headless=resolve_headless(headless),
        browser_executable=runtime.executable,
    ) as client:
        page = client._pages[0]
        cookies = await page.context.cookies()
        cookie_names = {str(cookie.get("name") or "") for cookie in cookies}
        if "SAPISID" not in cookie_names:
            raise AuthMissingError(
                detail="The browser profile has no active Google SAPISID session cookie."
            )
        landing: str | None = None
        try:
            await raise_if_known_landing(
                page,
                requested="the authenticated Google Flow app",
                at="flow_bridge.doctor",
            )
        except FlowAppError:
            # Migrated Flow can leave a healthy authenticated session on /about.
            # Generation with an explicit project can still navigate into the editor,
            # so this landing is diagnostic rather than an authentication failure.
            if flow_landing_kind(page.url) != "public":
                raise
            landing = "public"
        return {
            "status": "pass",
            "authenticated": True,
            "landing": landing,
            "profile": resolved,
            "profile_dir": str(meta.profile_dir),
            "browser_executable": str(runtime.executable),
            "profile_browser_version": profile_version,
            "runtime_browser_version": runtime_version,
            "page_url": page.url,
            "page_title": await page.title(),
            "webdriver": await page.evaluate("navigator.webdriver"),
            "transport": type(client.transport).__name__,
        }


async def run_canary(
    *,
    profile: str | None,
    browser: str | Path | None,
    request_id: str,
    store: JobStore | None = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    store = store or JobStore()
    snapshots = list_account_snapshots(browser)
    if profile:
        selected_snapshot = next((item for item in snapshots if item.name == profile), None)
        if selected_snapshot is None:
            raise LookupError(f"Unknown gflow profile: {profile}")
        selected = AccountScheduler(store).select([selected_snapshot])
    else:
        selected = AccountScheduler(store).select(snapshots)

    job, created = store.create_or_get(
        request_id=request_id,
        kind="canary.flow_bootstrap",
        payload={"profile": selected.name},
    )
    if not created:
        return {
            "status": "existing",
            "job_id": job.job_id,
            "state": job.state.value,
            "account": job.account,
        }

    job = store.assign_account(job.job_id, selected.name)
    job = store.transition(job.job_id, JobState.VALIDATING, event_type="canary.started")
    try:
        result = await doctor(selected.name, browser, headless=headless)
    except Exception as exc:
        store.transition(
            job.job_id,
            JobState.FAILED_RETRYABLE,
            error_type=type(exc).__name__,
            event_type="canary.failed",
            metadata={"phase": "flow_bootstrap"},
        )
        raise

    job = store.transition(
        job.job_id,
        JobState.COMPLETED,
        event_type="canary.passed",
        metadata={"transport": result["transport"]},
    )
    return {
        "status": "pass",
        "job_id": job.job_id,
        "state": job.state.value,
        "account": selected.name,
        "doctor": result,
    }
