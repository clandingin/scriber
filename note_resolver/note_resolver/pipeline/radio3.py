"""Stage 4 — RADIO3 resolver.

Maps a mention match to Endorses / Denies / Not selected + citation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .indexer import TranscriptIndex
from .matcher import MentionMatch, match_mention, turn_citation

logger = logging.getLogger(__name__)

Radio3Value = Literal["Endorses", "Denies", "Not selected"]


@dataclass
class Radio3Result:
    field_id: str
    label: str
    section_id: str
    value: Radio3Value
    citation: dict | None
    match: MentionMatch


def resolve_radio3(
    index: TranscriptIndex,
    *,
    field_id: str,
    label: str,
    section_id: str,
    keywords: list[str],
) -> Radio3Result:
    """Resolve one RADIO3 item.

    Contract:
      in  — index + field metadata/keywords
      out — Radio3Result
    """
    match = match_mention(
        index,
        name=label,
        keywords=keywords,
        require_polarity=True,
    )

    if not match.matched:
        value: Radio3Value = "Not selected"
    elif match.polarity == "negated":
        value = "Denies"
    elif match.polarity == "affirmed":
        value = "Endorses"
    else:
        # Mentioned without clear polarity — leave unselected for clinician
        value = "Not selected"

    citation = turn_citation(index.turns, match.turn_index) if match.matched else None
    result = Radio3Result(
        field_id=field_id,
        label=label,
        section_id=section_id,
        value=value,
        citation=citation,
        match=match,
    )
    logger.info(
        "RADIO3 %-24s => %-13s cite=%s",
        label,
        value,
        citation["turn_index"] if citation else None,
    )
    return result
