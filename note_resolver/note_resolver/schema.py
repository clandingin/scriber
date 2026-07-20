"""Load editable field schema from config/fields.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "fields.json"


def load_schema(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with cfg_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if "sections" not in data:
        raise ValueError(f"Invalid schema at {cfg_path}: missing 'sections'")
    return data


def iter_fields(schema: dict[str, Any], field_type: str | None = None):
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            if field_type is None or field.get("type") == field_type:
                yield section, field
