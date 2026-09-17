from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gflow_cli.api.client import FlowApiClient
from gflow_cli.browser_manager import profile_last_version

_VERSION_RE = re.compile(r"^(\d+)")


class BrowserRuntimeError(RuntimeError):
    pass


def _major(version: str | None) -> int | None:
    if not version:
        return None
    match = _VERSION_RE.match(str(version).strip())
    return int(match.group(1)) if match else None


def _windows_file_version(executable: Path) -> str | None:
    escaped = str(executable).replace("'", "''")
    command = f"(Get-Item -LiteralPath '{escaped}').VersionInfo.FileVersion"
    try:
        value = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None


def browser_version(executable: Path) -> str | None:
    if sys.platform == "win32":
        return _windows_file_version(executable)
    try:
        value = subprocess.check_output(
            [str(executable), "--version"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+(?:\.\d+)+)", value)
    return match.group(1) if match else None


def _playwright_cache_candidates() -> list[Path]:
    root = Path.home() / ".cache" / "ms-playwright"
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    candidates.extend(sorted(root.glob("chromium-*/chrome-linux64/chrome"), reverse=True))
    candidates.extend(sorted(root.glob("chromium_headless_shell-*/chrome-linux/headless_shell"), reverse=True))
    return candidates


def _candidate_paths() -> list[Path]:
    explicit = os.environ.get("FLOW_BRIDGE_BROWSER_EXECUTABLE")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates.extend(
            [
                program_files / "BraveSoftware/Brave-Browser/Application/brave.exe",
                program_files / "Google/Chrome/Application/chrome.exe",
                local_app_data / "Google/Chrome/Application/chrome.exe",
                program_files / "Microsoft/Edge/Application/msedge.exe",
            ]
        )
    elif sys.platform == "darwin":
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/brave-browser"),
                Path("/usr/bin/chromium"),
                Path("/usr/bin/chromium-browser"),
            ]
        )
        candidates.extend(_playwright_cache_candidates())
    return candidates


def resolve_browser_executable(explicit: str | Path | None = None) -> Path:
    candidates = [Path(explicit).expanduser()] if explicit else _candidate_paths()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        version = browser_version(candidate)
        if _major(version) not in (None, 0):
            return candidate.resolve()
    rendered = ", ".join(str(path) for path in candidates)
    raise BrowserRuntimeError(f"No compatible Chromium browser found. Checked: {rendered}")


def assert_profile_compatible(profile_dir: Path, executable: Path) -> tuple[str | None, str | None]:
    profile_version = profile_last_version(profile_dir)
    executable_version = browser_version(executable)
    profile_major = _major(profile_version)
    executable_major = _major(executable_version)
    if profile_major is not None and executable_major is not None and executable_major < profile_major:
        raise BrowserRuntimeError(
            "Refusing to open a profile written by newer Chromium "
            f"{profile_version} with browser {executable_version}."
        )
    return profile_version, executable_version


@dataclass(frozen=True)
class BrowserRuntime:
    executable: Path

    @classmethod
    def auto(cls, explicit: str | Path | None = None) -> BrowserRuntime:
        return cls(resolve_browser_executable(explicit))


def env_flag(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_headless(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return env_flag("FLOW_BRIDGE_HEADLESS", default=False)


class ExecutableFlowApiClient(FlowApiClient):
    """gflow client using an explicit Chromium executable instead of a fixed channel.

    gflow-cli already exposes `_persistent_context_kwargs` as an out-of-core
    customization seam. The additional launch guard is necessary until gflow's
    own compatibility guard understands `executable_path`.
    """

    def __init__(self, *args: Any, browser_executable: str | Path, **kwargs: Any) -> None:
        self._flow_bridge_browser = Path(browser_executable).expanduser().resolve()
        super().__init__(*args, **kwargs)

    def _persistent_context_kwargs(self) -> dict[str, Any]:
        kwargs = dict(super()._persistent_context_kwargs())
        kwargs.pop("channel", None)
        kwargs["executable_path"] = str(self._flow_bridge_browser)
        if env_flag("FLOW_BRIDGE_BROWSER_NO_SANDBOX"):
            args = list(kwargs.get("args") or [])
            if "--no-sandbox" not in args:
                args.append("--no-sandbox")
            kwargs["args"] = args
            ignored = [
                item for item in list(kwargs.get("ignore_default_args") or []) if item != "--no-sandbox"
            ]
            kwargs["ignore_default_args"] = ignored
        return kwargs

    def _log_and_guard_launch(self, kwargs: dict[str, Any]) -> None:
        assert_profile_compatible(self.profile_dir, self._flow_bridge_browser)
