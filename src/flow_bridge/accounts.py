from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from gflow_cli import profile_store
from gflow_cli.browser_manager import profile_last_version

from .browser_runtime import BrowserRuntime, BrowserRuntimeError, browser_version


@dataclass(frozen=True)
class AccountSnapshot:
    name: str
    is_default: bool
    cookies_present: bool
    profile_version: str | None
    runtime_version: str | None
    runtime_compatible: bool | None
    browser_strategy: str | None

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


def list_account_snapshots(browser: str | Path | None = None) -> list[AccountSnapshot]:
    runtime_version: str | None = None
    try:
        runtime = BrowserRuntime.auto(browser)
        runtime_version = browser_version(runtime.executable)
    except BrowserRuntimeError:
        runtime = None

    snapshots: list[AccountSnapshot] = []
    for meta in profile_store.list_profiles():
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
            )
        )
    return snapshots
