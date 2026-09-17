from __future__ import annotations

from pathlib import Path

import pytest

from flow_bridge.jobs import InvalidTransitionError, JobState, JobStore


def test_create_or_get_is_idempotent(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    first, created_first = store.create_or_get(
        request_id="req-001",
        kind="video.generate",
        payload={"prompt_rev": "a"},
    )
    second, created_second = store.create_or_get(
        request_id="req-001",
        kind="video.generate",
        payload={"prompt_rev": "b"},
    )

    assert created_first is True
    assert created_second is False
    assert second.job_id == first.job_id
    assert second.payload == {"prompt_rev": "a"}


def test_state_machine_and_events(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job, _ = store.create_or_get(request_id="req-002", kind="canary")

    job = store.assign_account(job.job_id, "alpha")
    assert job.state is JobState.ACCOUNT_ASSIGNED
    job = store.transition(job.job_id, JobState.VALIDATING, event_type="canary.started")
    job = store.transition(job.job_id, JobState.COMPLETED, event_type="canary.passed")

    assert job.terminal is True
    assert [event.event_type for event in store.events(job.job_id)] == [
        "job.created",
        "job.account_assigned",
        "canary.started",
        "canary.passed",
    ]


def test_invalid_transition_fails_closed(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job, _ = store.create_or_get(request_id="req-003", kind="video.generate")

    with pytest.raises(InvalidTransitionError):
        store.transition(job.job_id, JobState.COMPLETED)


def test_unknown_submission_state_is_terminal(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job, _ = store.create_or_get(request_id="req-004", kind="video.generate")
    job = store.assign_account(job.job_id, "alpha")
    job = store.transition(job.job_id, JobState.SUBMITTING, increment_attempt=True)
    job = store.transition(job.job_id, JobState.UNKNOWN_STATE, error_type="AmbiguousSubmission")

    assert job.terminal is True
    assert job.state is JobState.UNKNOWN_STATE
    with pytest.raises(InvalidTransitionError):
        store.transition(job.job_id, JobState.SUBMITTING, increment_attempt=True)


def test_stats_report_unresolved_and_attempts(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    first, _ = store.create_or_get(request_id="stats-a", kind="video.t2v", payload={})
    store.assign_account(first.job_id, "acct-a")
    store.transition(first.job_id, JobState.SUBMITTING, increment_attempt=True)
    second, _ = store.create_or_get(request_id="stats-b", kind="canary.flow_bootstrap", payload={})
    store.assign_account(second.job_id, "acct-b")
    store.transition(second.job_id, JobState.VALIDATING)
    store.transition(second.job_id, JobState.COMPLETED)

    stats = store.stats()
    assert stats["total_jobs"] == 2
    assert stats["total_attempts"] == 1
    assert stats["by_state"]["SUBMITTING"] == 1
    assert stats["by_state"]["COMPLETED"] == 1
    assert stats["by_kind"]["video.t2v"] == 1
    assert stats["by_account"]["acct-a"] == 1
    assert stats["unresolved"] == 1


def test_active_count_excludes_terminal_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    active, _ = store.create_or_get(request_id="req-active", kind="canary")
    done, _ = store.create_or_get(request_id="req-done", kind="canary")
    store.assign_account(active.job_id, "alpha")
    done = store.assign_account(done.job_id, "alpha")
    done = store.transition(done.job_id, JobState.VALIDATING)
    store.transition(done.job_id, JobState.COMPLETED)

    assert store.active_count("alpha") == 1
