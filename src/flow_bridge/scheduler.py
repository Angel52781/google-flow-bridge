from __future__ import annotations

from dataclasses import dataclass

from .accounts import AccountSnapshot
from .jobs import JobStore


class NoHealthyAccountError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScheduledAccount:
    name: str
    active_jobs: int


class AccountScheduler:
    """Small deterministic scheduler; richer policies can replace it later."""

    def __init__(self, store: JobStore) -> None:
        self.store = store

    def select(self, accounts: list[AccountSnapshot]) -> ScheduledAccount:
        candidates: list[ScheduledAccount] = []
        for account in accounts:
            if not account.cookies_present:
                continue
            if account.runtime_compatible is not True:
                continue
            candidates.append(
                ScheduledAccount(
                    name=account.name,
                    active_jobs=self.store.active_count(account.name),
                )
            )
        if not candidates:
            raise NoHealthyAccountError("No compatible authenticated Flow account is available")
        return min(candidates, key=lambda item: (item.active_jobs, item.name))
