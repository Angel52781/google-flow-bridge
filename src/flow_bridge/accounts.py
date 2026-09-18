from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from gflow_cli import profile_store
from gflow_cli.browser_manager import profile_last_version

from .browser_runtime import BrowserRuntime, BrowserRuntimeError, browser_version
from .state import default_db_path


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AccountHealth(StrEnum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True)
class AccountPolicy:
    name: str
    enabled: bool = True
    max_concurrency: int = 1
    priority: int = 100
    health_state: AccountHealth = AccountHealth.UNKNOWN
    health_updated_at: str | None = None
    last_error_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AccountRegistry:
    """Operational policy for gflow profiles without storing Google identity data."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS account_policies (
                    name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    max_concurrency INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    health_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    health_updated_at TEXT,
                    last_error_type TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(account_policies)").fetchall()
            }
            if "health_state" not in columns:
                connection.execute(
                    "ALTER TABLE account_policies ADD COLUMN health_state TEXT NOT NULL DEFAULT 'UNKNOWN'"
                )
            if "health_updated_at" not in columns:
                connection.execute("ALTER TABLE account_policies ADD COLUMN health_updated_at TEXT")
            if "last_error_type" not in columns:
                connection.execute("ALTER TABLE account_policies ADD COLUMN last_error_type TEXT")

    @staticmethod
    def _policy(row: sqlite3.Row) -> AccountPolicy:
        return AccountPolicy(
            name=str(row["name"]),
            enabled=bool(row["enabled"]),
            max_concurrency=int(row["max_concurrency"]),
            priority=int(row["priority"]),
            health_state=AccountHealth(str(row["health_state"])),
            health_updated_at=row["health_updated_at"],
            last_error_type=row["last_error_type"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get(self, name: str) -> AccountPolicy | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM account_policies WHERE name = ?",
                (name,),
            ).fetchone()
        return self._policy(row) if row is not None else None

    def effective(self, name: str) -> AccountPolicy:
        return self.get(name) or AccountPolicy(name=name)

    def upsert(
        self,
        name: str,
        *,
        enabled: bool = True,
        max_concurrency: int = 1,
        priority: int = 100,
    ) -> AccountPolicy:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        now = _now()
        current = self.get(name)
        health_state = current.health_state if current else AccountHealth.UNKNOWN
        health_updated_at = current.health_updated_at if current else None
        last_error_type = current.last_error_type if current else None
        created_at = current.created_at if current and current.created_at else now
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_policies(
                    name, enabled, max_concurrency, priority,
                    health_state, health_updated_at, last_error_type,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    enabled = excluded.enabled,
                    max_concurrency = excluded.max_concurrency,
                    priority = excluded.priority,
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    int(enabled),
                    max_concurrency,
                    priority,
                    health_state.value,
                    health_updated_at,
                    last_error_type,
                    created_at,
                    now,
                ),
            )
        policy = self.get(name)
        assert policy is not None
        return policy

    def set_enabled(self, name: str, enabled: bool) -> AccountPolicy:
        current = self.effective(name)
        return self.upsert(
            name,
            enabled=enabled,
            max_concurrency=current.max_concurrency,
            priority=current.priority,
        )

    def record_health(
        self,
        name: str,
        health: AccountHealth,
        *,
        error_type: str | None = None,
    ) -> AccountPolicy:
        current = self.effective(name)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_policies(
                    name, enabled, max_concurrency, priority,
                    health_state, health_updated_at, last_error_type,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    health_state = excluded.health_state,
                    health_updated_at = excluded.health_updated_at,
                    last_error_type = excluded.last_error_type,
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    int(current.enabled),
                    current.max_concurrency,
                    current.priority,
                    health.value,
                    now,
                    error_type,
                    current.created_at or now,
                    now,
                ),
            )
        policy = self.get(name)
        assert policy is not None
        return policy

    def list(self) -> list[AccountPolicy]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM account_policies ORDER BY priority, name"
            ).fetchall()
        return [self._policy(row) for row in rows]


@dataclass(frozen=True)
class AccountSnapshot:
    name: str
    is_default: bool
    cookies_present: bool
    profile_version: str | None
    runtime_version: str | None
    runtime_compatible: bool | None
    browser_strategy: str | None
    enabled: bool = True
    max_concurrency: int = 1
    priority: int = 100
    health_state: AccountHealth = AccountHealth.UNKNOWN
    health_updated_at: str | None = None
    last_error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _major(value: str | None) -> int | None:
    if not value:
        return None
    head = value.split(".", 1)[0]
    return int(head) if head.isdigit() else None


def _strategy(profile_dir: Path) -> str | None:
    marker = profile_dir / ".gflow_browser_strategy"
    if not marker.is_file():
        return None
    try:
        value = marker.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return value or None


def list_account_snapshots(
    browser: str | Path | None = None,
    *,
    registry: AccountRegistry | None = None,
) -> list[AccountSnapshot]:
    registry = registry or AccountRegistry()
    runtime_version: str | None = None
    try:
        runtime = BrowserRuntime.auto(browser)
        runtime_version = browser_version(runtime.executable)
    except BrowserRuntimeError:
        runtime = None

    snapshots: list[AccountSnapshot] = []
    for meta in profile_store.list_profiles():
        policy = registry.effective(meta.name)
        profile_version = profile_last_version(meta.profile_dir)
        profile_major = _major(profile_version)
        runtime_major = _major(runtime_version)
        compatible: bool | None
        if runtime is None or profile_major is None or runtime_major is None:
            compatible = None
        else:
            compatible = runtime_major >= profile_major
        snapshots.append(
            AccountSnapshot(
                name=meta.name,
                is_default=meta.is_default,
                cookies_present=meta.cookies_present,
                profile_version=profile_version,
                runtime_version=runtime_version,
                runtime_compatible=compatible,
                browser_strategy=_strategy(meta.profile_dir),
                enabled=policy.enabled,
                max_concurrency=policy.max_concurrency,
                priority=policy.priority,
                health_state=policy.health_state,
                health_updated_at=policy.health_updated_at,
                last_error_type=policy.last_error_type,
            )
        )
    return snapshots
