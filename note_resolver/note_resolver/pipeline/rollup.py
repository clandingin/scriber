"""Stage 6 — Rollup resolver.

Pure functions over already-resolved RADIO3 / MULTI_TAG results.
No transcript access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .multi_tag import MultiTagResult
from .radio3 import Radio3Result

logger = logging.getLogger(__name__)


@dataclass
class RollupResult:
    field_id: str
    label: str
    section_id: str
    value: bool
    rule: str
    children: list[dict]  # justification from child field results


def resolve_rollup(
    *,
    field_id: str,
    label: str,
    section_id: str,
    rule: str,
    child_ids: list[str],
    radio3: dict[str, Radio3Result],
    multi_tag: dict[str, MultiTagResult],
) -> RollupResult:
    """Resolve one ROLLUP field from child results.

    Supported rules:
      - all_denies: every child RADIO3 == Denies
      - all_default_only: every child MULTI_TAG is default-only
    """
    child_summaries: list[dict[str, Any]] = []
    ok = True

    if rule == "all_denies":
        for cid in child_ids:
            child = radio3.get(cid)
            if child is None:
                ok = False
                child_summaries.append({"field_id": cid, "status": "missing"})
                continue
            child_summaries.append(
                {
                    "field_id": cid,
                    "label": child.label,
                    "value": child.value,
                }
            )
            if child.value != "Denies":
                ok = False

    elif rule == "all_default_only":
        for cid in child_ids:
            child = multi_tag.get(cid)
            if child is None:
                ok = False
                child_summaries.append({"field_id": cid, "status": "missing"})
                continue
            child_summaries.append(
                {
                    "field_id": cid,
                    "label": child.label,
                    "selected_tags": child.selected_tags,
                    "is_default_only": child.is_default_only,
                }
            )
            if not child.is_default_only:
                ok = False

    else:
        raise ValueError(f"Unknown rollup rule: {rule}")

    result = RollupResult(
        field_id=field_id,
        label=label,
        section_id=section_id,
        value=ok,
        rule=rule,
        children=child_summaries,
    )
    logger.info("ROLLUP %-40s => %s (rule=%s)", label, ok, rule)
    return result
