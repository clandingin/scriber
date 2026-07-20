"""Stage 5 — MULTI_TAG resolver.

Matches each tag in a category; if no specific (non-default) tags match,
selects the default / WNL tag.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .indexer import TranscriptIndex
from .matcher import MentionMatch, match_mention, turn_citation

logger = logging.getLogger(__name__)


@dataclass
class TagResult:
    tag_id: str
    label: str
    selected: bool
    citation: dict | None
    match: MentionMatch | None = None


@dataclass
class MultiTagResult:
    field_id: str
    label: str
    section_id: str
    default_tag: str
    selected_tags: list[str]
    tags: list[TagResult] = field(default_factory=list)

    @property
    def is_default_only(self) -> bool:
        return self.selected_tags == [self.default_tag]


def resolve_multi_tag(
    index: TranscriptIndex,
    *,
    field_id: str,
    label: str,
    section_id: str,
    default_tag: str,
    tags: list[dict],
    match_polarity: bool = True,
) -> MultiTagResult:
    """Resolve one MULTI_TAG category.

    Contract:
      in  — index + category metadata (tags with keywords, default_tag id)
      out — MultiTagResult
    """
    tag_results: list[TagResult] = []
    selected: list[str] = []
    generic_labels = {"other", "none", "none identified", "none endorsed / not indicated"}

    for tag in tags:
        tag_id = tag["id"]
        tag_label = tag.get("label", tag_id)
        keywords = list(tag.get("keywords") or [])
        is_default = tag_id == default_tag

        # Default/WNL tags are chosen by absence of specifics, not matched
        if is_default:
            tag_results.append(
                TagResult(
                    tag_id=tag_id,
                    label=tag_label,
                    selected=False,  # filled below
                    citation=None,
                    match=None,
                )
            )
            continue

        search_keywords = list(keywords)
        if tag_label.strip().lower() not in generic_labels and len(tag_label.strip()) > 3:
            search_keywords = search_keywords + [tag_label]

        match = match_mention(
            index,
            name=f"{label}: {tag_label}",
            keywords=search_keywords,
            require_polarity=match_polarity,
            skip_negated=match_polarity,
        )
        if match.matched:
            selected.append(tag_id)
            citation = turn_citation(index.turns, match.turn_index)
            tag_results.append(
                TagResult(
                    tag_id=tag_id,
                    label=tag_label,
                    selected=True,
                    citation=citation,
                    match=match,
                )
            )
            logger.info(
                "MULTI_TAG %-20s / %-24s SELECTED cite=%s",
                label,
                tag_label,
                citation["turn_index"] if citation else None,
            )
        else:
            tag_results.append(
                TagResult(
                    tag_id=tag_id,
                    label=tag_label,
                    selected=False,
                    citation=None,
                    match=match,
                )
            )

    # If nothing specific matched, select default
    if not selected:
        selected = [default_tag]
        for tr in tag_results:
            if tr.tag_id == default_tag:
                tr.selected = True
        logger.info("MULTI_TAG %-20s => DEFAULT %s", label, default_tag)
    else:
        for tr in tag_results:
            if tr.tag_id == default_tag:
                tr.selected = False

    return MultiTagResult(
        field_id=field_id,
        label=label,
        section_id=section_id,
        default_tag=default_tag,
        selected_tags=selected,
        tags=tag_results,
    )
