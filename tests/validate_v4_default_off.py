from __future__ import annotations

import hashlib
import json
from pathlib import Path

from diagnose_nhis_mixed_context import MANUAL_FULL
from dump_masked_outputs import EXPECTATIONS as LONG_EXPECTATIONS
from korean_pii import KoreanPII
from korean_pii.merge import non_overlapping_for_mask
from validate_long_pipeline import CASES as LONG_CASES
from validate_v4_manual_full import EXPECTATIONS as MANUAL_EXPECTATIONS
from validate_v4_reordered_manual import build_reordered


def locate(text: str, surface: str, anchor: str) -> tuple[int, int]:
    anchor_start = text.index(anchor) if anchor else 0
    start = text.index(surface, anchor_start + len(anchor))
    return start, start + len(surface)


def evaluate(pii: KoreanPII, case_id: str, text: str, expectations) -> dict:
    spans = list(pii.detect(text))
    selected = non_overlapping_for_mask(spans, pii.policy)
    masked = pii.mask(text, spans)
    checks = []
    for check_id, label, surface, anchor, default_sensitive in expectations:
        sensitive = False if label == "KR_NHIS" else default_sensitive
        start, end = locate(text, surface, anchor)
        exact = any(
            span.label == label and span.start == start and span.end == end
            for span in selected
        )
        overlap = any(
            span.label == label and span.start < end and start < span.end
            for span in selected
        )
        passed = exact if sensitive else not overlap
        if label == "KR_NHIS" and not sensitive:
            passed = passed and text[start:end] in masked
        checks.append({
            "id": check_id,
            "label": label,
            "expected_sensitive_default_off": sensitive,
            "passed": passed,
        })
    return {
        "id": case_id,
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "check_count": len(checks),
        "all_checks_passed": all(item["passed"] for item in checks),
        "failed_checks": [item for item in checks if not item["passed"]],
        "nhis_span_count": sum(span.label == "KR_NHIS" for span in spans),
        "masked_sha256": hashlib.sha256(masked.encode()).hexdigest(),
    }


def main() -> None:
    Path("results").mkdir(parents=True, exist_ok=True)
    pii = KoreanPII()
    long_by_id = {item["id"]: item["text"] for item in LONG_CASES}
    documents = [
        evaluate(pii, "manual-full-680", MANUAL_FULL, MANUAL_EXPECTATIONS),
        evaluate(pii, "manual-reordered-680", build_reordered(), MANUAL_EXPECTATIONS),
        evaluate(
            pii,
            "exact-original-669",
            long_by_id["exact-original-669"],
            LONG_EXPECTATIONS["exact-original-669"],
        ),
        evaluate(
            pii,
            "natural-diverse-long",
            long_by_id["natural-diverse-long"],
            LONG_EXPECTATIONS["natural-diverse-long"],
        ),
    ]
    payload = {
        "policy_version": pii.policy.policy_version,
        "policy_sha256": pii.policy.sha256,
        "supported_type_count": len(pii.policy.types),
        "enabled_type_count": sum(item.enabled for item in pii.policy.types.values()),
        "nhis_enabled": pii.policy.types["KR_NHIS"].enabled,
        "nhis_verifier_loaded": pii.nhis_verifier.loaded,
        "document_count": len(documents),
        "check_count": sum(item["check_count"] for item in documents),
        "all_checks_passed": all(item["all_checks_passed"] for item in documents),
        "all_nhis_absent": all(item["nhis_span_count"] == 0 for item in documents),
        "documents": documents,
    }
    Path("results/v4-default-off.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
