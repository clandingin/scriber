"""Append-only session transcript journal under local app data."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


def default_sessions_dir() -> Path:
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        base = Path(local_app) / "tab-transcriber" / "sessions"
    else:
        base = Path.home() / ".local" / "share" / "tab-transcriber" / "sessions"
    base.mkdir(parents=True, exist_ok=True)
    return base


class SessionJournal:
    def __init__(self, session_id: str, sessions_dir: Path | None = None) -> None:
        self.session_id = session_id
        self.sessions_dir = sessions_dir or default_sessions_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:64]
        self.path = self.sessions_dir / f"{stamp}_{safe_id}.txt"
        self._lines: list[str] = []
        self.path.touch(exist_ok=True)

    def append(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self._lines.append(cleaned)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(cleaned + "\n")

    def full_text(self) -> str:
        return "\n".join(self._lines).strip()

    def close(self, retain: bool = True) -> None:
        if not retain and self.path.exists():
            self.path.unlink(missing_ok=True)
