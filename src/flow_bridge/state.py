from __future__ import annotations

import os
import sys
from pathlib import Path


def default_state_root() -> Path:
    override = os.environ.get("FLOW_BRIDGE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return (base / "flow-bridge").resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library/Application Support/flow-bridge").resolve()
    return (Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "flow-bridge").resolve()


def default_db_path() -> Path:
    return default_state_root() / "flow-bridge.sqlite3"


def default_artifacts_root() -> Path:
    return default_state_root() / "artifacts"
