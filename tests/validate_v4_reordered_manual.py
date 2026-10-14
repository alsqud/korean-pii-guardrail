from __future__ import annotations

import hashlib
import json
from pathlib import Path

from diagnose_nhis_mixed_context import MANUAL_FULL
from korean_pii import KoreanPII
from korean_pii.merge import non_overlapping_for_mask
from validate_v4_manual_full import EXPECTATIONS


def build_reordered() -> str:
    parts = MANUAL_FULL.split(". ")
    assert ". ".join(parts) == MANUAL_FULL
    assert len(parts) == 15
    order = (8, 3, 13, 1, 10, 6, 0, 12, 5, 14, 2, 9, 7, 11, 4)
    reordered = ". ".join(parts[index] for index in order)
    assert reordered != MANUAL_FULL
    assert len(reordered) == len(MANUAL_FULL)
    return reordered


def locate(text: str, surface: str, anchor: str) -> tuple[int, int]:
    anchor_start = text.index(anchor) if anchor else 0
    start = text.index(surface, anchor_start + len(anchor))
    return start, start + len(surface)


def main() -> None:
    text = build_reordered()
    pii = KoreanPII()
    spans = list(pii.detect(text))
    selected = non_overlapping_for_mask(spans, pii.policy)
    masked = pii.mask(text, spans)
    checks = []
    for check_id, label, surface, anchor, sensitive in EXPECTATIONS:
        start, end = locate(text, surface, anchor)
        exact = any(
            span.label == label and span.start == start and span.end == end
            for span in selected
        )
        overlap = any(
            span.label == label and span.start < end and start < span.end
            for span in selected
        )
        checks.append(
            {
                "id": check_id,
                "label": label,
                "surface": surface,
                "range": [start, end],
                "sensitive": sensitive,
                "detected_exact": exact,
                "detected_overlap": overlap,
                "passed": exact if sensitive else not overlap,
            }
        )
    payload = {
        "purpose": "same-content same-length sentence-order regression",
        "input_chars": len(text),
        "same_length_as_original": len(text) == len(MANUAL_FULL),
        "original_sha256": hashlib.sha256(MANUAL_FULL.encode()).hexdigest(),
        "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "content_parts_equal": sorted(MANUAL_FULL.split(". ")) == sorted(text.split(". ")),
        "original": MANUAL_FULL,
        "reordered": text,
        "masked": masked,
        "masked_sha256": hashlib.sha256(masked.encode()).hexdigest(),
        "selected_spans": [span.to_dict() for span in selected],
        "all_checks_passed": all(item["passed"] for item in checks),
        "failed_checks": [item for item in checks if not item["passed"]],
        "checks": checks,
        "nhis_trace": list(pii.nhis_verifier.last_trace),
    }
    Path("results/v4-reordered-manual.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
