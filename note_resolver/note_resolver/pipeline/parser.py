"""Stage 1 — Transcript parser.

Input: raw transcript text ("A: ...\\nB: ...")
Output: list of Turn(speaker, index, text)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


TURN_RE = re.compile(
    r"^\s*(?P<speaker>[ABab])\s*[:\-–—]\s*(?P<text>.+?)\s*$"
)


@dataclass(frozen=True)
class Turn:
    speaker: str  # "A" (doctor) or "B" (patient)
    index: int  # 0-based turn index in transcript order
    text: str


def parse_transcript(raw: str) -> list[Turn]:
    """Split an A:/B: transcript into ordered turns.

    Lines that do not match the speaker prefix are appended to the
    previous turn when possible (soft wrap); otherwise they are skipped.
    """
    turns: list[Turn] = []
    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        m = TURN_RE.match(line)
        if m:
            turns.append(
                Turn(
                    speaker=m.group("speaker").upper(),
                    index=len(turns),
                    text=m.group("text").strip(),
                )
            )
        elif turns:
            prev = turns[-1]
            turns[-1] = Turn(
                speaker=prev.speaker,
                index=prev.index,
                text=f"{prev.text} {line.strip()}".strip(),
            )
    return turns


def format_turn(turn: Turn) -> str:
    return f"{turn.speaker}: {turn.text}"
