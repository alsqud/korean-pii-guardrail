from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time

from fixtures import CASES
from korean_pii import KoreanPII
from korean_pii.merge import non_overlapping_for_mask


def locate(text: str, spec: dict) -> tuple[int, int]:
    start_at = 0
    if spec.get("anchor"):
        anchor_start = text.index(spec["anchor"])
        start_at = anchor_start + len(spec["anchor"])
    start = text.index(spec["surface"], start_at)
    return start, start + len(spec["surface"])


def overlaps(start: int, end: int, span) -> bool:
    return start < span.end and span.start < end


def span_record(text: str, span) -> dict:
    record = span.to_dict()
    record["substring"] = text[span.start:span.end]
    return record


def evaluate_case(pii: KoreanPII, case: dict) -> dict:
    text = case["text"]
    started = time.perf_counter()
    spans = list(pii.detect(text))
    elapsed_ms = (time.perf_counter() - started) * 1000
    selected = non_overlapping_for_mask(spans, pii.policy)
    masked = pii.mask(text, spans)

    manual_mask = text
    for span in reversed(selected):
        token = pii.policy.mask["token_format"].format(label=span.label)
        manual_mask = manual_mask[:span.start] + token + manual_mask[span.end:]

    expectation_results = []
    for spec in case["expectations"]:
        start, end = locate(text, spec)
        matches = [span for span in spans if span.label == spec["label"] and overlaps(start, end, span)]
        exact = [span for span in matches if span.start == start and span.end == end]
        selected_exact = [span for span in selected if span.label == spec["label"] and span.start == start and span.end == end]
        if spec["present"]:
            source_ok = any(span.source in spec.get("sources", (span.source,)) for span in exact)
            passed = bool(exact and selected_exact and source_ok)
        else:
            source_ok = True
            passed = not matches
        expectation_results.append({
            "id": spec["id"],
            "label": spec["label"],
            "expected_present": spec["present"],
            "expected_range": [start, end],
            "expected_substring": text[start:end],
            "allowed_sources": list(spec.get("sources", ())),
            "overlapping_spans": [span_record(text, span) for span in matches],
            "exact_sources": [span.source for span in exact],
            "selected_for_mask": bool(selected_exact),
            "source_ok": source_ok,
            "passed": passed,
        })

    preserve_results = []
    for spec in case["preserve"]:
        start, end = locate(text, spec)
        collisions = [span for span in selected if overlaps(start, end, span)]
        preserve_results.append({
            "id": spec["id"],
            "range": [start, end],
            "substring": text[start:end],
            "colliding_selected_spans": [span_record(text, span) for span in collisions],
            "passed": not collisions,
        })

    try:
        second_mask = pii.mask(masked)
        idempotent = second_mask == masked
        second_pass_error = None
    except Exception as exc:
        idempotent = False
        second_pass_error = type(exc).__name__

    actual_identity = {
        "chars": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    return {
        "id": case["id"],
        "input_identity": actual_identity,
        "identity_matches_fixture": actual_identity == case["identity"],
        "elapsed_ms": round(elapsed_ms, 3),
        "offsets_valid": all(0 <= span.start < span.end <= len(text) for span in spans),
        "mask_projection_valid": masked == manual_mask,
        "idempotent": idempotent,
        "second_pass_error": second_pass_error,
        "masked_text": masked,
        "masked_sha256": hashlib.sha256(masked.encode("utf-8")).hexdigest(),
        "span_count": len(spans),
        "selected_span_count": len(selected),
        "spans": [span_record(text, span) for span in spans],
        "selected_spans": [span_record(text, span) for span in selected],
        "expectations": expectation_results,
        "preservation": preserve_results,
        "expectations_pass": all(item["passed"] for item in expectation_results),
        "preservation_pass": all(item["passed"] for item in preserve_results),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    pii = KoreanPII()
    cases = [evaluate_case(pii, case) for case in CASES]
    payload = {
        "variant": args.variant,
        "scope": "full pipeline with pinned local models; exact and independent synthetic 669-character inputs",
        "policy_version": pii.policy.policy_version,
        "policy_sha256": pii.policy.sha256,
        "device": pii.device,
        "loaded_models": list(pii.models.loaded_models),
        "case_count": len(cases),
        "median_case_ms_including_lazy_load": round(statistics.median(item["elapsed_ms"] for item in cases), 3),
        "all_offsets_valid": all(item["offsets_valid"] for item in cases),
        "all_mask_projection_valid": all(item["mask_projection_valid"] for item in cases),
        "all_idempotent": all(item["idempotent"] for item in cases),
        "all_expectations_pass": all(item["expectations_pass"] for item in cases),
        "all_preservation_pass": all(item["preservation_pass"] for item in cases),
        "cases": cases,
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
