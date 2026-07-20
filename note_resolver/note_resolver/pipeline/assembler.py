"""Stage 7 — Output assembler.

Produces a structured note payload + a plain-text form dump for review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .multi_tag import MultiTagResult
from .radio3 import Radio3Result
from .rollup import RollupResult


@dataclass
class NoteResolution:
    diagnosis: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    radio3: dict[str, Radio3Result] = field(default_factory=dict)
    multi_tag: dict[str, MultiTagResult] = field(default_factory=dict)
    rollups: dict[str, RollupResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis": self.diagnosis,
            "sections": self.sections,
        }


def _cite_line(citation: dict | None) -> str:
    if not citation:
        return "(no citation)"
    return f'[turn {citation["turn_index"]}] {citation["speaker"]}: {citation["text"]}'


def assemble(
    *,
    diagnosis: str,
    schema_sections: list[dict],
    radio3: dict[str, Radio3Result],
    multi_tag: dict[str, MultiTagResult],
    rollups: dict[str, RollupResult],
) -> NoteResolution:
    """Assemble template-oriented section payloads from resolver outputs."""
    sections_out: list[dict[str, Any]] = []

    for section in schema_sections:
        sid = section["id"]
        fields_out: list[dict[str, Any]] = []
        for fdef in section.get("fields", []):
            fid = fdef["id"]
            ftype = fdef["type"]
            if ftype == "RADIO3" and fid in radio3:
                r = radio3[fid]
                fields_out.append(
                    {
                        "id": fid,
                        "label": r.label,
                        "type": "RADIO3",
                        "value": r.value,
                        "citation": r.citation,
                        "method": r.match.method,
                    }
                )
            elif ftype == "MULTI_TAG" and fid in multi_tag:
                m = multi_tag[fid]
                fields_out.append(
                    {
                        "id": fid,
                        "label": m.label,
                        "type": "MULTI_TAG",
                        "selected_tags": m.selected_tags,
                        "tags": [
                            {
                                "id": t.tag_id,
                                "label": t.label,
                                "selected": t.selected,
                                "citation": t.citation,
                            }
                            for t in m.tags
                            if t.selected
                        ],
                    }
                )
            elif ftype == "ROLLUP" and fid in rollups:
                u = rollups[fid]
                fields_out.append(
                    {
                        "id": fid,
                        "label": u.label,
                        "type": "ROLLUP",
                        "value": u.value,
                        "rule": u.rule,
                        "children": u.children,
                    }
                )

        sections_out.append(
            {
                "id": sid,
                "label": section.get("label", sid),
                "fields": fields_out,
            }
        )

    return NoteResolution(
        diagnosis=diagnosis,
        sections=sections_out,
        radio3=radio3,
        multi_tag=multi_tag,
        rollups=rollups,
    )


def format_text_report(note: NoteResolution) -> str:
    """Human-readable text representation of resolved form answers."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("CLINICAL SESSION NOTE — CHECKBOX RESOLUTION")
    lines.append("=" * 72)
    lines.append(f"Diagnosis: {note.diagnosis.strip() or '(none provided)'}")
    lines.append("")

    for section in note.sections:
        lines.append("-" * 72)
        lines.append(section["label"].upper())
        lines.append("-" * 72)

        for field in section["fields"]:
            ftype = field["type"]
            if ftype == "RADIO3":
                lines.append(f"  [{field['value']:^13}]  {field['label']}")
                lines.append(f"      citation: {_cite_line(field.get('citation'))}")
                if field.get("method") and field["method"] != "none":
                    lines.append(f"      method:   {field['method']}")
            elif ftype == "MULTI_TAG":
                selected = field.get("tags") or []
                tag_labels = ", ".join(t["label"] for t in selected) or "(none)"
                lines.append(f"  [MULTI_TAG]  {field['label']}: {tag_labels}")
                for t in selected:
                    lines.append(
                        f"      • {t['label']}: {_cite_line(t.get('citation'))}"
                    )
            elif ftype == "ROLLUP":
                mark = "X" if field["value"] else " "
                lines.append(f"  [{mark}] ROLLUP  {field['label']}  (rule={field['rule']})")
                for child in field.get("children") or []:
                    if "value" in child:
                        lines.append(
                            f"      ← {child.get('label', child['field_id'])}: {child['value']}"
                        )
                    elif "selected_tags" in child:
                        lines.append(
                            f"      ← {child.get('label', child['field_id'])}: "
                            f"{child['selected_tags']} "
                            f"(default_only={child.get('is_default_only')})"
                        )
                    else:
                        lines.append(f"      ← {child}")
            lines.append("")

        lines.append("")

    lines.append("=" * 72)
    lines.append("END OF REPORT")
    lines.append("=" * 72)
    return "\n".join(lines)
