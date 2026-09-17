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
