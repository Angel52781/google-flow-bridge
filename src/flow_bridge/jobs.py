from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .state import default_db_path


class JobState(StrEnum):
    CREATED = "CREATED"
    ACCOUNT_ASSIGNED = "ACCOUNT_ASSIGNED"
    SUBMITTING = "SUBMITTING"
    GENERATING = "GENERATING"
    OUTPUT_AVAILABLE = "OUTPUT_AVAILABLE"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UI_CHANGED = "UI_CHANGED"
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"
    UNKNOWN_STATE = "UNKNOWN_STATE"


TERMINAL_STATES = {
    JobState.COMPLETED,
    JobState.FAILED_TERMINAL,
    JobState.AUTH_REQUIRED,
    JobState.UI_CHANGED,
    JobState.INSUFFICIENT_CREDITS,
    JobState.UNKNOWN_STATE,
}


_ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.CREATED: {JobState.ACCOUNT_ASSIGNED, JobState.FAILED_TERMINAL},
    JobState.ACCOUNT_ASSIGNED: {
        JobState.SUBMITTING,
        JobState.VALIDATING,
        JobState.AUTH_REQUIRED,
        JobState.UI_CHANGED,
        JobState.INSUFFICIENT_CREDITS,
        JobState.FAILED_RETRYABLE,
        JobState.FAILED_TERMINAL,
    },
    JobState.SUBMITTING: {
        JobState.GENERATING,
        JobState.OUTPUT_AVAILABLE,
        JobState.AUTH_REQUIRED,
        JobState.UI_CHANGED,
        JobState.INSUFFICIENT_CREDITS,
        JobState.FAILED_RETRYABLE,
        JobState.FAILED_TERMINAL,
        JobState.UNKNOWN_STATE,
    },
    JobState.GENERATING: {
        JobState.OUTPUT_AVAILABLE,
        JobState.FAILED_RETRYABLE,
        JobState.FAILED_TERMINAL,
        JobState.UNKNOWN_STATE,
    },
    JobState.OUTPUT_AVAILABLE: {JobState.DOWNLOADING, JobState.VALIDATING, JobState.FAILED_RETRYABLE},
    JobState.DOWNLOADING: {JobState.VALIDATING, JobState.FAILED_RETRYABLE, JobState.FAILED_TERMINAL},
    JobState.VALIDATING: {JobState.COMPLETED, JobState.FAILED_RETRYABLE, JobState.FAILED_TERMINAL},
    JobState.FAILED_RETRYABLE: {JobState.ACCOUNT_ASSIGNED, JobState.SUBMITTING, JobState.VALIDATING, JobState.FAILED_TERMINAL},
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    request_id: str
    kind: str
    state: JobState
    account: str | None
    attempt: int
    payload: dict[str, Any]
    error_type: str | None
    created_at: str
    updated_at: str

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


@dataclass(frozen=True)
class EventRecord:
    event_id: int
    job_id: str
    event_type: str
    state: JobState | None
    metadata: dict[str, Any]
    created_at: str


class InvalidTransitionError(RuntimeError):
    pass


class JobStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    account TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    error_type TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE INDEX IF NOT EXISTS idx_jobs_account_state ON jobs(account, state);

                CREATE TABLE IF NOT EXISTS job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    state TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, event_id);
                """
            )

    @staticmethod
    def _job(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            request_id=row["request_id"],
            kind=row["kind"],
            state=JobState(row["state"]),
            account=row["account"],
            attempt=int(row["attempt"]),
            payload=json.loads(row["payload_json"]),
            error_type=row["error_type"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_or_get(self, *, request_id: str, kind: str, payload: dict[str, Any] | None = None) -> tuple[JobRecord, bool]:
        now = _now()
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        payload_json = _json(payload)
        with self._connect() as connection:
            existing = connection.execute("SELECT * FROM jobs WHERE request_id = ?", (request_id,)).fetchone()
            if existing is not None:
                return self._job(existing), False
            connection.execute(
                """
                INSERT INTO jobs(job_id, request_id, kind, state, account, attempt, payload_json, error_type, created_at, updated_at)
                VALUES(?, ?, ?, ?, NULL, 0, ?, NULL, ?, ?)
                """,
                (job_id, request_id, kind, JobState.CREATED.value, payload_json, now, now),
            )
            connection.execute(
                "INSERT INTO job_events(job_id, event_type, state, metadata_json, created_at) VALUES(?, ?, ?, ?, ?)",
                (job_id, "job.created", JobState.CREATED.value, "{}", now),
            )
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            assert row is not None
            return self._job(row), True

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            return self._job(row) if row is not None else None

    def by_request(self, request_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE request_id = ?", (request_id,)).fetchone()
            return self._job(row) if row is not None else None

    def list(self, *, states: Iterable[JobState] | None = None, limit: int = 50) -> list[JobRecord]:
        params: list[Any] = []
        where = ""
        values = list(states or [])
        if values:
            where = f"WHERE state IN ({','.join('?' for _ in values)})"
            params.extend(state.value for state in values)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._job(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            by_state = {
                str(row["state"]): int(row["n"])
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state ORDER BY state"
                ).fetchall()
            }
            by_kind = {
                str(row["kind"]): int(row["n"])
                for row in connection.execute(
                    "SELECT kind, COUNT(*) AS n FROM jobs GROUP BY kind ORDER BY kind"
                ).fetchall()
            }
            by_account = {
                str(row["account"]): int(row["n"])
                for row in connection.execute(
                    "SELECT account, COUNT(*) AS n FROM jobs WHERE account IS NOT NULL GROUP BY account ORDER BY account"
                ).fetchall()
            }
            total = int(connection.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"])
            attempts = int(connection.execute("SELECT COALESCE(SUM(attempt), 0) AS n FROM jobs").fetchone()["n"])
        return {
            "total_jobs": total,
            "total_attempts": attempts,
            "by_state": by_state,
            "by_kind": by_kind,
            "by_account": by_account,
            "unresolved": sum(
                by_state.get(state.value, 0)
                for state in (JobState.SUBMITTING, JobState.GENERATING, JobState.UNKNOWN_STATE)
            ),
        }

    def active_count(self, account: str) -> int:
        terminal = tuple(state.value for state in TERMINAL_STATES)
        placeholders = ",".join("?" for _ in terminal)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS n FROM jobs WHERE account = ? AND state NOT IN ({placeholders})",
                (account, *terminal),
            ).fetchone()
            return int(row["n"])

    def assign_account(self, job_id: str, account: str) -> JobRecord:
        return self.transition(job_id, JobState.ACCOUNT_ASSIGNED, account=account, event_type="job.account_assigned")

    def transition(
        self,
        job_id: str,
        target: JobState,
        *,
        account: str | None = None,
        error_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        event_type: str = "job.state_changed",
        increment_attempt: bool = False,
    ) -> JobRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            current = JobState(row["state"])
            allowed = _ALLOWED_TRANSITIONS.get(current, set())
            if target not in allowed:
                raise InvalidTransitionError(f"{current.value} -> {target.value} is not allowed")
            now = _now()
            next_account = account if account is not None else row["account"]
            next_attempt = int(row["attempt"]) + (1 if increment_attempt else 0)
            connection.execute(
                "UPDATE jobs SET state = ?, account = ?, attempt = ?, error_type = ?, updated_at = ? WHERE job_id = ?",
                (target.value, next_account, next_attempt, error_type, now, job_id),
            )
            connection.execute(
                "INSERT INTO job_events(job_id, event_type, state, metadata_json, created_at) VALUES(?, ?, ?, ?, ?)",
                (job_id, event_type, target.value, _json(metadata), now),
            )
            updated = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            assert updated is not None
            return self._job(updated)

    def record_event(self, job_id: str, event_type: str, *, metadata: dict[str, Any] | None = None) -> None:
        if self.get(job_id) is None:
            raise KeyError(job_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO job_events(job_id, event_type, state, metadata_json, created_at) VALUES(?, ?, NULL, ?, ?)",
                (job_id, event_type, _json(metadata), _now()),
            )

    def events(self, job_id: str) -> list[EventRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? ORDER BY event_id ASC",
                (job_id,),
            ).fetchall()
        return [
            EventRecord(
                event_id=int(row["event_id"]),
                job_id=row["job_id"],
                event_type=row["event_type"],
                state=JobState(row["state"]) if row["state"] else None,
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
