#!/usr/bin/env python3
"""Audit the sealed long-document evaluation bundle without loading models."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent / "long_document_generalization"
LABELS = {
    "PERSON", "KR_LOCATION", "KR_BANK_ACCOUNT", "DATE_OF_BIRTH", "USERNAME",
    "KR_PASSPORT", "KR_DRIVER_LICENSE", "KR_VEHICLE_PLATE", "CREDIT_CARD",
    "EMAIL_ADDRESS", "IP_ADDRESS", "KR_PHONE_NUMBER", "KR_RRN",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    fixture = ROOT / "long_document_test_set.jsonl"
    predictions = ROOT / "raw_and_masked_predictions.jsonl"
    seal = load(ROOT / "test_set_seal.json")
    run = load(ROOT / "run_metadata.json")
    evaluation = load(ROOT / "evaluation_summary.json")
    summary = evaluation["summary"]

    assert seal["sealed_before_model_output"] is True
    assert seal["truth_and_criteria_changes_after_seal_forbidden"] is True
    assert seal["preexisting_model_outputs"] == []
    assert seal["fixture_sha256"] == sha256(fixture)
    assert run["fixture_sha256"] == sha256(fixture)
    assert evaluation["fixture_sha256"] == sha256(fixture)
    assert evaluation["run_sha256"] == sha256(predictions)

    assert summary["gold"] == summary["full"] == 156
    for field in (
        "partial", "miss", "decoy_hits", "decoy_masked_chars",
        "overmask_chars_outside_gold", "raw_exact_duplicate_items",
        "selected_exact_duplicate_items", "raw_overlap_pairs",
        "raw_cross_label_overlap_pairs", "selected_overlap_pairs", "runtime_failures",
    ):
        assert summary[field] == 0, (field, summary[field])
    assert summary["selected_nonoverlap"] is True
    assert summary["mask_projection_failures"] == []
    assert summary["offset_failures"] == []
    assert summary["selected_type_boundary_exact"]["tp"] == 156
    assert summary["selected_type_boundary_exact"]["fp"] == 0
    assert summary["selected_type_boundary_exact"]["fn"] == 0

    assert set(evaluation["per_type"]) == LABELS
    for label, metrics in evaluation["per_type"].items():
        assert metrics["gold"] == metrics["full"] == 12, label
        assert metrics["partial"] == metrics["miss"] == 0, label
        assert metrics["selected_exact"]["tp"] == 12, label
        assert metrics["selected_exact"]["fp"] == metrics["selected_exact"]["fn"] == 0, label

    for phase in ("pre_deployment", "post_deployment"):
        result = load(ROOT / f"{phase}_equivalence.json")
        assert result["status"] == "PASS"
        assert result["documents"] == 12
        assert result["mismatches"] == []

    packaged = load(ROOT / "packaged_output_equivalence.json")
    assert packaged["status"] == "PASS"
    assert packaged["documents"] == 12
    assert packaged["pipeline_profile"] == "hybrid-long-document-guardrails"
    assert packaged["policy_version"] == "hybrid-long-document-guardrails-2026-10-15"
    assert packaged["policy_sha256"] == "a34cd7154c542862ea461540323f7247aa1ca80875df49b50be7c1e70c83f5cc"
    assert packaged["mismatches"] == []

    historical = load(ROOT.parent / "historical_regression_summary.json")
    assert historical["totals"]["gold"] == historical["totals"]["full"] == 1014
    for field in (
        "partial", "miss", "general_information_false_positives",
        "selected_exact_fp", "selected_exact_fn", "selected_overlap_pairs",
    ):
        assert historical["totals"][field] == 0, field

    existing = load(ROOT.parent / "existing_suite_regression.json")
    assert existing["check_count"] == 115
    assert existing["all_checks_passed"] is True
    assert existing["all_nhis_absent"] is True

    manifest = load(ROOT.parent.parent / "release_manifest.json")
    assert manifest["package_version"] == "0.3.0rc1"
    assert manifest["policy_sha256"] == packaged["policy_sha256"]
    assert manifest["sealed_evaluation"]["fixture_sha256"] == sha256(fixture)
    assert manifest["sealed_evaluation"]["expected_predictions_sha256"] == sha256(predictions)
    assert manifest["verification"]["readiness_status"] == "ready"
    assert manifest["verification"]["raw_selected_masked_equivalence"] == "PASS"

    print(
        "PASS: 156/156 full protection; 13 labels; no partial, miss, false-positive, "
        "over-mask, duplicate, or overlap; 1014 historical and 115 existing checks passed; "
        "deployment equivalence confirmed"
    )


if __name__ == "__main__":
    main()
