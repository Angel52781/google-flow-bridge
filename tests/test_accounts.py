from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from gflow_cli.profile_store import ProfileMeta

from flow_bridge import accounts


def test_list_account_snapshots_redacts_email_and_checks_runtime(monkeypatch, tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile_alpha"
    profile_dir.mkdir()
    (profile_dir / ".gflow_browser_strategy").write_text("chrome", encoding="utf-8")

    monkeypatch.setattr(
        accounts.profile_store,
        "list_profiles",
        lambda: [
            ProfileMeta(
                name="alpha",
                profile_dir=profile_dir,
                cookies_present=True,
                last_used_at=None,
                is_default=True,
                google_account="private@example.com",
            )
        ],
    )
    monkeypatch.setattr(accounts, "profile_last_version", lambda _: "153.1.95.101")
    monkeypatch.setattr(
        accounts.BrowserRuntime,
        "auto",
        classmethod(lambda cls, browser=None: SimpleNamespace(executable=Path("browser.exe"))),
    )
    monkeypatch.setattr(accounts, "browser_version", lambda _: "153.2.0.0")

    snapshots = accounts.list_account_snapshots()

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.name == "alpha"
    assert snapshot.runtime_compatible is True
    assert snapshot.browser_strategy == "chrome"
    assert "google_account" not in snapshot.to_dict()


def test_account_registry_persists_policy(tmp_path: Path) -> None:
    registry = accounts.AccountRegistry(tmp_path / "accounts.sqlite3")
    policy = registry.upsert(
        "alpha",
        enabled=False,
        max_concurrency=3,
        priority=20,
    )

    assert policy.name == "alpha"
    assert policy.enabled is False
    assert policy.max_concurrency == 3
    assert policy.priority == 20
    assert registry.effective("alpha") == policy


def test_account_registry_defaults_are_safe(tmp_path: Path) -> None:
    registry = accounts.AccountRegistry(tmp_path / "accounts.sqlite3")
    policy = registry.effective("new-profile")
    assert policy.enabled is True
    assert policy.max_concurrency == 1
    assert policy.priority == 100
    assert policy.health_state is accounts.AccountHealth.UNKNOWN


def test_account_registry_records_health_without_changing_policy(tmp_path: Path) -> None:
    registry = accounts.AccountRegistry(tmp_path / "accounts.sqlite3")
    registry.upsert("alpha", max_concurrency=3, priority=20)
    policy = registry.record_health(
        "alpha",
        accounts.AccountHealth.HEALTHY,
    )
    assert policy.health_state is accounts.AccountHealth.HEALTHY
    assert policy.health_updated_at is not None
    assert policy.last_error_type is None
    assert policy.max_concurrency == 3
    assert policy.priority == 20
