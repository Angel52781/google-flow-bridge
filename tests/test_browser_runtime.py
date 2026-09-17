from __future__ import annotations

from pathlib import Path

import pytest

from flow_bridge import browser_runtime as runtime


def test_major_parses_chromium_versions() -> None:
    assert runtime._major("153.1.95.101") == 153
    assert runtime._major("149.0.7827.55") == 149
    assert runtime._major(None) is None
    assert runtime._major("invalid") is None


def test_resolve_explicit_browser_rejects_zero_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "chrome.exe"
    fake.write_bytes(b"stub")
    monkeypatch.setattr(runtime, "browser_version", lambda _: "0.0.0.0")
    with pytest.raises(runtime.BrowserRuntimeError):
        runtime.resolve_browser_executable(fake)


def test_resolve_explicit_browser_accepts_real_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "brave.exe"
    fake.write_bytes(b"real")
    monkeypatch.setattr(runtime, "browser_version", lambda _: "153.1.95.101")
    assert runtime.resolve_browser_executable(fake) == fake.resolve()


def test_profile_guard_rejects_major_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "browser.exe"
    fake.write_bytes(b"real")
    monkeypatch.setattr(runtime, "profile_last_version", lambda _: "153.1.95.101")
    monkeypatch.setattr(runtime, "browser_version", lambda _: "149.0.7827.55")
    with pytest.raises(runtime.BrowserRuntimeError, match="newer Chromium"):
        runtime.assert_profile_compatible(tmp_path, fake)


def test_profile_guard_accepts_same_major(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "browser.exe"
    fake.write_bytes(b"real")
    monkeypatch.setattr(runtime, "profile_last_version", lambda _: "153.1.95.101")
    monkeypatch.setattr(runtime, "browser_version", lambda _: "153.2.0.0")
    assert runtime.assert_profile_compatible(tmp_path, fake) == ("153.1.95.101", "153.2.0.0")


def test_resolve_headless_uses_explicit_then_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLOW_BRIDGE_HEADLESS", raising=False)
    assert runtime.resolve_headless() is False
    monkeypatch.setenv("FLOW_BRIDGE_HEADLESS", "true")
    assert runtime.resolve_headless() is True
    assert runtime.resolve_headless(False) is False


def test_client_uses_explicit_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = tmp_path / "browser.exe"
    executable.write_bytes(b"real")
    monkeypatch.setattr(runtime.FlowApiClient, "_persistent_context_kwargs", lambda self: {"channel": "chrome", "headless": False})

    client = runtime.ExecutableFlowApiClient(
        profile_dir=tmp_path,
        headless=False,
        browser_executable=executable,
    )
    kwargs = client._persistent_context_kwargs()
    assert "channel" not in kwargs
    assert kwargs["executable_path"] == str(executable.resolve())


def test_client_can_opt_into_no_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = tmp_path / "browser"
    executable.write_bytes(b"real")
    monkeypatch.setenv("FLOW_BRIDGE_BROWSER_NO_SANDBOX", "1")
    monkeypatch.setattr(
        runtime.FlowApiClient,
        "_persistent_context_kwargs",
        lambda self: {"channel": "chrome", "args": ["--password-store=basic"]},
    )
    client = runtime.ExecutableFlowApiClient(
        profile_dir=tmp_path,
        headless=True,
        browser_executable=executable,
    )
    kwargs = client._persistent_context_kwargs()
    assert "--no-sandbox" in kwargs["args"]
    assert "--no-sandbox" not in kwargs["ignore_default_args"]
