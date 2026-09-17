from pathlib import Path

import pytest
from gflow_cli.errors import (
    BrowserSessionClosedError,
    InsufficientCreditsError,
    UiSelectorDriftError,
)

from flow_bridge.generation import (
    VideoGenerationSpec,
    _classify_failure,
    _existing_outcome,
    _validate_artifact,
)
from flow_bridge.jobs import JobState, JobStore


def _store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.sqlite3")


def _assigned_job(store: JobStore):
    job, created = store.create_or_get(request_id="req-1", kind="video.t2v", payload={})
    assert created
    return store.assign_account(job.job_id, "acct")


def test_request_id_is_deterministic() -> None:
    left = VideoGenerationSpec(prompt="hello", model="veo-lite")
    right = VideoGenerationSpec(prompt="hello", model="veo-lite")
    assert left.effective_request_id() == right.effective_request_id()


def test_explicit_request_id_wins() -> None:
    spec = VideoGenerationSpec(prompt="hello", request_id="shot-7-r2")
    assert spec.effective_request_id() == "shot-7-r2"


def test_persisted_payload_hashes_prompt() -> None:
    spec = VideoGenerationSpec(prompt="private prompt", project_id="project-1")
    payload = spec.persisted_payload()
    assert "prompt" not in payload
    assert payload["prompt_sha256"] == "6fe06b970bb77bb96bee521acbebf7e932c2bbc684494ad299a7e1851347fc8e"


def test_browser_close_after_submit_becomes_unknown_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = _assigned_job(store)
    store.transition(job.job_id, JobState.SUBMITTING, increment_attempt=True)
    failed = _classify_failure(
        store,
        job.job_id,
        BrowserSessionClosedError("closed"),
        submitted=True,
    )
    assert failed.state is JobState.UNKNOWN_STATE
    assert failed.attempt == 1


def test_insufficient_credits_is_terminal_without_retry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = _assigned_job(store)
    failed = _classify_failure(
        store,
        job.job_id,
        InsufficientCreditsError("short"),
        submitted=False,
    )
    assert failed.state is JobState.INSUFFICIENT_CREDITS
    assert failed.attempt == 0


def test_ui_drift_before_submit_is_diagnosed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = _assigned_job(store)
    failed = _classify_failure(
        store,
        job.job_id,
        UiSelectorDriftError("moved"),
        submitted=False,
    )
    assert failed.state is JobState.UI_CHANGED


def test_validate_artifact_rejects_non_mp4(tmp_path: Path) -> None:
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"not-an-mp4")
    with pytest.raises(RuntimeError, match="ISO BMFF"):
        _validate_artifact(path)


def test_validate_artifact_accepts_ftyp(tmp_path: Path) -> None:
    path = tmp_path / "ok.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom00000000")
    assert _validate_artifact(path) == path.resolve()


def test_existing_completed_job_returns_prior_artifact_and_media(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = _assigned_job(store)
    store.transition(job.job_id, JobState.SUBMITTING, increment_attempt=True)
    store.transition(job.job_id, JobState.GENERATING)
    store.transition(job.job_id, JobState.OUTPUT_AVAILABLE)
    store.transition(job.job_id, JobState.VALIDATING)
    artifact = tmp_path / "clip.mp4"
    store.transition(
        job.job_id,
        JobState.COMPLETED,
        event_type="video.completed",
        metadata={"artifact": str(artifact), "media_id": "media-1"},
    )
    completed = store.get(job.job_id)
    assert completed is not None
    outcome = _existing_outcome(store, completed)
    assert outcome.artifact == artifact
    assert outcome.media_id == "media-1"
