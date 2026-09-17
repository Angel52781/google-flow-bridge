from __future__ import annotations

from dataclasses import dataclass

from .accounts import AccountHealth, AccountSnapshot
from .jobs import JobStore


class NoHealthyAccountError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScheduledAccount:
    name: str
    active_jobs: int
    max_concurrency: int
    priority: int


class AccountScheduler:
    """Small deterministic scheduler; richer policies can replace it later."""

    def __init__(self, store: JobStore) -> None:
        self.store = store

    def select(
        self,
        accounts: list[AccountSnapshot],
        *,
        require_healthy: bool = True,
    ) -> ScheduledAccount:
        candidates: list[ScheduledAccount] = []
        for account in accounts:
            if not account.enabled:
                continue
            if require_healthy and account.health_state is not AccountHealth.HEALTHY:
                continue
            if not account.cookies_present:
                continue
            if account.runtime_compatible is not True:
                continue
            active_jobs = self.store.active_count(account.name)
            if active_jobs >= account.max_concurrency:
                continue
            candidates.append(
                ScheduledAccount(
                    name=account.name,
                    active_jobs=active_jobs,
                    max_concurrency=account.max_concurrency,
                    priority=account.priority,
                )
            )
        if not candidates:
            raise NoHealthyAccountError(
                "No enabled, compatible Flow account with a passing health canary is available"
            )
        return min(
            candidates,
            key=lambda item: (
                item.active_jobs / item.max_concurrency,
                item.priority,
                item.name,
            ),
        )
