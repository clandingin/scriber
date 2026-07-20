"""Optional bridge from the transcription helper to note_resolver."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _ensure_note_resolver_path() -> None:
    """Allow importing sibling note_resolver/ package from a repo checkout."""
    try:
        import note_resolver  # noqa: F401

        return
    except ImportError:
        pass

    # helper/tab_transcriber_helper/note_bridge.py → repo root is parents[2]
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "note_resolver"
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def resolve_note_report(
    transcript: str,
    diagnosis: str,
    *,
    enable_embeddings: bool = False,
) -> str:
    """Run the checkbox pipeline and return the plain-text form report."""
    _ensure_note_resolver_path()
    try:
        from note_resolver.runner import run_pipeline
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "note_resolver is not installed. From the repo root, "
            "`pip install -e note_resolver` (or keep the note_resolver/ folder "
            "next to helper/)."
        ) from exc

    _note, report = run_pipeline(
        transcript or "",
        diagnosis or "",
        enable_embeddings=enable_embeddings,
    )
    return report
