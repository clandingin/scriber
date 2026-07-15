"""Append-only session transcript journal under local app data."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .pcm import format_speaker_line


def default_sessions_dir() -> Path:
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        base = Path(local_app) / "tab-transcriber" / "sessions"
    else:
        base = Path.home() / ".local" / "share" / "tab-transcriber" / "sessions"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class JournalEntry:
    text: str
    t0: float
    t1: float
    speaker: str = ""


class SessionJournal:
    def __init__(self, session_id: str, sessions_dir: Path | None = None) -> None:
        self.session_id = session_id
        self.sessions_dir = sessions_dir or default_sessions_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:64]
        self.path = self.sessions_dir / f"{stamp}_{safe_id}.txt"
        self._entries: list[JournalEntry] = []
        self.path.touch(exist_ok=True)

    def append(self, text: str, *, speaker: str = "", t0: float = 0.0, t1: float = 0.0) -> str:
        line = format_speaker_line(speaker, text) if speaker else text.strip()
        if not line:
            return ""
        self._entries.append(JournalEntry(text=line, t0=t0, t1=t1, speaker=speaker))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return line

    def full_text(self) -> str:
        ordered = sorted(self._entries, key=lambda e: (e.t0, e.speaker or "", e.t1))
        return "\n".join(e.text for e in ordered).strip()

    def close(self, retain: bool = True) -> None:
        if not retain and self.path.exists():
            self.path.unlink(missing_ok=True)
