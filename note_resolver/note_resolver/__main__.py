"""CLI entry: resolve checkboxes from transcript/diagnosis text files."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from note_resolver.runner import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve clinical note checkbox fields")
    parser.add_argument("--transcript", "-t", required=True, help="Path to A:/B: transcript .txt")
    parser.add_argument("--diagnosis", "-d", default="", help="Diagnosis code + label")
    parser.add_argument("--diagnosis-file", help="Optional file containing diagnosis text")
    parser.add_argument("--schema", help="Optional path to fields.json")
    parser.add_argument("--no-embeddings", action="store_true", help="Keyword-only matching")
    parser.add_argument("-o", "--output", help="Write text report to this path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    transcript = Path(args.transcript).read_text(encoding="utf-8")
    diagnosis = args.diagnosis
    if args.diagnosis_file:
        diagnosis = Path(args.diagnosis_file).read_text(encoding="utf-8").strip()

    _note, report = run_pipeline(
        transcript,
        diagnosis,
        schema_path=args.schema,
        enable_embeddings=not args.no_embeddings,
    )
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
