from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gflow_cli import profile_store
from gflow_cli.api.dto import GenerationCheckpoint
from gflow_cli.api.video import (
    Aspect,
    GenerateVideoRequest,
    Mode,
    VideoModel,
    VideoResult,
)
from gflow_cli.errors import (
    AuthExpiredError,
    AuthMissingError,
    BrowserSessionClosedError,
    InsufficientCreditsError,
    UiSelectorDriftError,
)

from .accounts import list_account_snapshots
from .browser_runtime import BrowserRuntime, ExecutableFlowApiClient, resolve_headless
from .jobs import JobRecord, JobState, JobStore
from .scheduler import AccountScheduler
from .state import default_artifacts_root


@dataclass(frozen=True)
class VideoGenerationSpec:
    prompt: str
    aspect: str = "9:16"
    model: str = "veo-lite"
    duration: int | None = None
    count: int = 1
    profile: str | None = None
    project_id: str | None = None
    request_id: str | None = None

    def normalized_payload(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "aspect": self.aspect,
            "model": self.model,
            "duration": self.duration,
            "count": self.count,
            "profile": self.profile,
            "project_id": self.project_id,
        }

    def persisted_payload(self) -> dict[str, Any]:
        payload = self.normalized_payload()
        prompt = str(payload.pop("prompt"))
        payload["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return payload

    def effective_request_id(self) -> str:
        if self.request_id:
            return self.request_id
        body = json.dumps(self.normalized_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]
        return f"video-{digest}"


@dataclass(frozen=True)
class VideoGenerationOutcome:
    status: str
    job: JobRecord
    artifact: Path | None = None
    media_id: str | None = None


def _validate_artifact(path: Path | None) -> Path:
    if path is None:
        raise RuntimeError("generation completed without a downloaded artifact")
    resolved = path.resolve()
    if not resolved.is_file():
        raise RuntimeError("downloaded artifact does not exist")
    if resolved.stat().st_size <= 0:
        raise RuntimeError("downloaded artifact is empty")
    header = resolved.read_bytes()[:32]
    if b"ftyp" not in header:
        raise RuntimeError("downloaded artifact is not an ISO BMFF/MP4 file")
    return resolved


def _transition_if(store: JobStore, job_id: str, from_states: set[JobState], target: JobState, **kwargs: Any) -> JobRecord:
    current = store.get(job_id)
    if current is None:
        raise KeyError(job_id)
    if current.state in from_states:
        return store.transition(job_id, target, **kwargs)
    return current


def _classify_failure(store: JobStore, job_id: str, exc: Exception, *, submitted: bool) -> JobRecord:
    current = store.get(job_id)
    if current is None:
        raise KeyError(job_id)

    if isinstance(exc, InsufficientCreditsError):
        target = JobState.INSUFFICIENT_CREDITS
    elif isinstance(exc, (AuthExpiredError, AuthMissingError)):
        target = JobState.AUTH_REQUIRED
    elif isinstance(exc, UiSelectorDriftError):
        target = JobState.UI_CHANGED
    elif submitted or isinstance(exc, BrowserSessionClosedError) and current.state in {JobState.SUBMITTING, JobState.GENERATING}:
        target = JobState.UNKNOWN_STATE
    else:
        target = JobState.FAILED_RETRYABLE

    return store.transition(
        job_id,
        target,
        error_type=type(exc).__name__,
        event_type="video.failed",
        metadata={"submitted": submitted, "phase": current.state.value},
    )


def _existing_outcome(store: JobStore, job: JobRecord) -> VideoGenerationOutcome:
    artifact: Path | None = None
    media_id: str | None = None
    for event in reversed(store.events(job.job_id)):
        if event.event_type != "video.completed":
            continue
        raw_artifact = event.metadata.get("artifact")
        raw_media_id = event.metadata.get("media_id")
        if isinstance(raw_artifact, str):
            artifact = Path(raw_artifact)
        if isinstance(raw_media_id, str):
            media_id = raw_media_id
        break
    return VideoGenerationOutcome(status="existing", job=job, artifact=artifact, media_id=media_id)


async def generate_video_once(
    spec: VideoGenerationSpec,
    *,
    store: JobStore | None = None,
    browser: str | Path | None = None,
    headless: bool | None = None,
) -> VideoGenerationOutcome:
    if spec.count != 1:
        raise ValueError("Flow Bridge v0 only permits count=1 to bound credit spend")

    store = store or JobStore()
    request_id = spec.effective_request_id()
    job, created = store.create_or_get(
        request_id=request_id,
        kind="video.t2v",
        payload=spec.persisted_payload(),
    )
    if not created:
        return _existing_outcome(store, job)

    snapshots = list_account_snapshots(browser)
    if spec.profile:
        snapshots = [item for item in snapshots if item.name == spec.profile]
    selected = AccountScheduler(store).select(snapshots)
    job = store.assign_account(job.job_id, selected.name)

    runtime = BrowserRuntime.auto(browser)
    meta = next((item for item in profile_store.list_profiles() if item.name == selected.name), None)
    if meta is None:
        raise RuntimeError(f"selected profile disappeared: {selected.name}")

    output_dir = default_artifacts_root() / job.job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    request = GenerateVideoRequest(
        prompt=spec.prompt,
        mode=Mode.T2V,
        aspect=Aspect.from_cli(spec.aspect),
        model=VideoModel.from_cli(spec.model),
        duration=spec.duration,
        count=1,
    )

    submitted = False

    def on_checkpoint(checkpoint: GenerationCheckpoint) -> None:
        nonlocal submitted
        if checkpoint.phase == "submit_attempted":
            submitted = True
            _transition_if(
                store,
                job.job_id,
                {JobState.ACCOUNT_ASSIGNED},
                JobState.SUBMITTING,
                increment_attempt=True,
                event_type="video.submit_attempted",
                metadata={"model": spec.model, "aspect": spec.aspect, "count": 1},
            )
            return
        if checkpoint.phase == "remote_started":
            _transition_if(
                store,
                job.job_id,
                {JobState.SUBMITTING},
                JobState.GENERATING,
                event_type="video.remote_started",
                metadata={
                    "operation_id": checkpoint.operation_id,
                    "media_ids": list(checkpoint.media_ids),
                },
            )

    try:
        async with ExecutableFlowApiClient(
            profile_dir=meta.profile_dir,
            headless=resolve_headless(headless),
            browser_executable=runtime.executable,
        ) as client:
            result: VideoResult = await client.generate_video(
                req=request,
                project_id=spec.project_id,
                out_dir=output_dir,
                poll_timeout_s=600.0,
                download=True,
                on_checkpoint=on_checkpoint,
            )
    except Exception as exc:  # noqa: BLE001 - durable recovery boundary after potential spend.
        failed = _classify_failure(store, job.job_id, exc, submitted=submitted)
        return VideoGenerationOutcome(status="failed", job=failed)

    current = store.get(job.job_id)
    if current is None:
        raise KeyError(job.job_id)

    if not result.status.succeeded:
        failed = store.transition(
            job.job_id,
            JobState.FAILED_TERMINAL,
            error_type="RemoteGenerationFailed",
            event_type="video.remote_failed",
            metadata={"remote_status": result.status.status},
        )
        return VideoGenerationOutcome(status="failed", job=failed, media_id=result.status.media_id)

    current = _transition_if(
        store,
        job.job_id,
        {JobState.SUBMITTING, JobState.GENERATING},
        JobState.OUTPUT_AVAILABLE,
        event_type="video.output_available",
        metadata={"media_id": result.status.media_id},
    )
    current = _transition_if(
        store,
        job.job_id,
        {JobState.OUTPUT_AVAILABLE},
        JobState.VALIDATING,
        event_type="video.validating",
    )
    try:
        artifact = _validate_artifact(result.local_path)
    except (OSError, RuntimeError) as exc:
        failed = store.transition(
            job.job_id,
            JobState.FAILED_TERMINAL,
            error_type=type(exc).__name__,
            event_type="video.validation_failed",
        )
        return VideoGenerationOutcome(status="failed", job=failed, media_id=result.status.media_id)

    completed = store.transition(
        job.job_id,
        JobState.COMPLETED,
        event_type="video.completed",
        metadata={
            "media_id": result.status.media_id,
            "artifact": str(artifact),
            "bytes": artifact.stat().st_size,
        },
    )
    return VideoGenerationOutcome(
        status="pass",
        job=completed,
        artifact=artifact,
        media_id=result.status.media_id,
    )
