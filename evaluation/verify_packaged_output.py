#!/usr/bin/env python3
"""Compare the packaged public API with committed raw and masked evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from korean_pii import KoreanPII
from korean_pii.merge import mask_text, non_overlapping_for_mask


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalized(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixture = rows(args.fixture)
    expected = {row["doc_id"]: row for row in rows(args.expected)}
    engine = KoreanPII()
    engine.address_gazetteer.load()
    mismatches = []
    for row in fixture:
        doc_id, text = row["doc_id"], row["text"]
        raw = list(engine.detect(text))
        selected = list(non_overlapping_for_mask(raw, engine.policy))
        masked = mask_text(text, selected, engine.policy)
        target = expected[doc_id]
        if normalized([span.to_dict() for span in raw]) != target["raw_predictions"]:
            mismatches.append({"doc_id": doc_id, "stream": "raw"})
        if normalized([span.to_dict() for span in selected]) != target["selected_predictions"]:
            mismatches.append({"doc_id": doc_id, "stream": "selected"})
        if masked != target["masked_text"]:
            mismatches.append({"doc_id": doc_id, "stream": "masked"})

    result = {
        "schema_version": "packaged-output-equivalence-1",
        "status": "PASS" if not mismatches else "FAIL",
        "documents": len(fixture),
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "expected_sha256": hashlib.sha256(args.expected.read_bytes()).hexdigest(),
        "pipeline_status": engine.status,
        "mismatches": mismatches,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
