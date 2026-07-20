"""Orchestrate all pipeline stages end-to-end."""

from __future__ import annotations

import logging
from typing import Any

from .pipeline.assembler import NoteResolution, assemble, format_text_report
from .pipeline.indexer import build_index
from .pipeline.multi_tag import MultiTagResult, resolve_multi_tag
from .pipeline.parser import parse_transcript
from .pipeline.radio3 import Radio3Result, resolve_radio3
from .pipeline.rollup import RollupResult, resolve_rollup
from .schema import iter_fields, load_schema

logger = logging.getLogger(__name__)


def run_pipeline(
    transcript: str,
    diagnosis: str,
    *,
    schema_path: str | None = None,
    enable_embeddings: bool = True,
) -> tuple[NoteResolution, str]:
    """Run parser → index → resolvers → assemble.

    Returns (structured NoteResolution, plain-text report).
    """
    schema = load_schema(schema_path)
    turns = parse_transcript(transcript)
    logger.info("Parsed %d transcript turns", len(turns))

    index = build_index(turns, enable_embeddings=enable_embeddings)

    radio3: dict[str, Radio3Result] = {}
    multi_tag: dict[str, MultiTagResult] = {}
    rollups: dict[str, RollupResult] = {}

    # Pass 1: RADIO3 + MULTI_TAG (need transcript)
    for section, field in iter_fields(schema):
        ftype = field["type"]
        sid = section["id"]
        if ftype == "RADIO3":
            radio3[field["id"]] = resolve_radio3(
                index,
                field_id=field["id"],
                label=field.get("label", field["id"]),
                section_id=sid,
                keywords=list(field.get("keywords") or []),
            )
        elif ftype == "MULTI_TAG":
            multi_tag[field["id"]] = resolve_multi_tag(
                index,
                field_id=field["id"],
                label=field.get("label", field["id"]),
                section_id=sid,
                default_tag=field["default_tag"],
                tags=list(field.get("tags") or []),
                match_polarity=bool(field.get("match_polarity", True)),
            )

    # Pass 2: ROLLUP (pure over children)
    for section, field in iter_fields(schema, field_type="ROLLUP"):
        rollups[field["id"]] = resolve_rollup(
            field_id=field["id"],
            label=field.get("label", field["id"]),
            section_id=section["id"],
            rule=field["rule"],
            child_ids=list(field.get("children") or []),
            radio3=radio3,
            multi_tag=multi_tag,
        )

    note = assemble(
        diagnosis=diagnosis,
        schema_sections=list(schema.get("sections") or []),
        radio3=radio3,
        multi_tag=multi_tag,
        rollups=rollups,
    )
    report = format_text_report(note)
    return note, report
