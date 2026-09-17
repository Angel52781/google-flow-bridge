from __future__ import annotations

from pathlib import Path

import pytest

from flow_bridge.accounts import AccountSnapshot
from flow_bridge.jobs import JobStore
from flow_bridge.scheduler import AccountScheduler, NoHealthyAccountError


def account(name: str, *, cookies: bool = True, compatible: bool | None = True) -> AccountSnapshot:
    return AccountSnapshot(
        name=name,
        is_default=False,
        cookies_present=cookies,
        profile_version="153.1.0.0",
        runtime_version="153.1.0.0",
        runtime_compatible=compatible,
        browser_strategy="chrome",
    )


def test_scheduler_prefers_lower_active_load(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job, _ = store.create_or_get(request_id="busy", kind="canary")
    store.assign_account(job.job_id, "alpha")

    picked = AccountScheduler(store).select([account("alpha"), account("beta")])

    assert picked.name == "beta"
    assert picked.active_jobs == 0


def test_scheduler_uses_deterministic_name_tiebreak(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    picked = AccountScheduler(store).select([account("beta"), account("alpha")])
    assert picked.name == "alpha"


def test_scheduler_rejects_missing_or_incompatible_profiles(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    with pytest.raises(NoHealthyAccountError):
        AccountScheduler(store).select(
            [account("a", cookies=False), account("b", compatible=False), account("c", compatible=None)]
        )
