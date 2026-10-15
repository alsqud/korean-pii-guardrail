#!/usr/bin/env python3
"""Evaluate protection, false positives, exactness, and span collisions."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import statistics
from pathlib import Path


ACTIVE = (
    "PERSON", "KR_LOCATION", "KR_BANK_ACCOUNT", "DATE_OF_BIRTH", "USERNAME",
    "KR_PASSPORT", "KR_DRIVER_LICENSE", "KR_VEHICLE_PLATE", "CREDIT_CARD",
    "EMAIL_ADDRESS", "IP_ADDRESS", "KR_PHONE_NUMBER", "KR_RRN",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def required_range(row: dict, gold: dict) -> tuple[int, int]:
    if gold["label"] == "KR_LOCATION":
        for detail in row.get("required_detail_spans", []):
            if detail.get("label") == "KR_LOCATION" and detail.get("end") == gold["end"]:
                return detail["start"], detail["end"]
    return gold["start"], gold["end"]


def exact_metrics(gold: set[tuple], predicted: set[tuple]) -> dict:
    tp, fp, fn = len(gold & predicted), len(predicted - gold), len(gold - predicted)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def overlaps(a: dict, b: dict) -> bool:
    return int(a["start"]) < int(b["end"]) and int(b["start"]) < int(a["end"])


def projected_mask(text: str, selected: list[dict]) -> str:
    output = text
    for span in sorted(selected, key=lambda item: (int(item["start"]), int(item["end"])), reverse=True):
        start, end = int(span["start"]), int(span["end"])
        output = output[:start] + f"<{span['label']}>" + output[end:]
    return output


def write_csv(path: Path, data: list[dict]) -> None:
    if not data:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-csv", type=Path, required=True)
    parser.add_argument("--per-type-csv", type=Path, required=True)
    parser.add_argument("--item-csv", type=Path, required=True)
    parser.add_argument("--decoy-csv", type=Path, required=True)
    parser.add_argument("--overlap-csv", type=Path, required=True)
    args = parser.parse_args()
    fixture_list = rows(args.fixture)
    fixture = {row["doc_id"]: row for row in fixture_list}
    run_list = rows(args.run)
    run = {row["doc_id"]: row for row in run_list}
    meta = json.loads(args.run.with_suffix(".meta.json").read_text())
    if set(fixture) != set(run):
        raise ValueError("run/fixture ids differ")
    if meta.get("fixture_sha256") != sha(args.fixture):
        raise ValueError("run fixture hash mismatch")

    totals = collections.Counter()
    per_type = collections.defaultdict(collections.Counter)
    item_rows: list[dict] = []
    decoy_rows: list[dict] = []
    overlap_rows: list[dict] = []
    gold_exact: set[tuple] = set()
    raw_exact: set[tuple] = set()
    selected_exact: set[tuple] = set()
    mask_projection_failures: list[str] = []
    offset_failures: list[str] = []
    all_selected_nonoverlap = True

    for doc_id, truth in fixture.items():
        result = run[doc_id]
        text = truth["text"]
        raw = [item for item in result.get("raw_predictions", []) if item.get("label") in ACTIVE]
        selected = [item for item in result.get("selected_predictions", []) if item.get("label") in ACTIVE]
        for stream_name, stream in (("raw", raw), ("selected", selected)):
            for position, span in enumerate(stream):
                start, end = int(span["start"]), int(span["end"])
                if not 0 <= start < end <= len(text):
                    offset_failures.append(f"{doc_id}:{stream_name}:{position}")
            seen = collections.Counter(
                (item["label"], int(item["start"]), int(item["end"])) for item in stream
            )
            totals[f"{stream_name}_exact_duplicate_items"] += sum(count - 1 for count in seen.values())
            for left_index, left in enumerate(stream):
                for right_index in range(left_index + 1, len(stream)):
                    right = stream[right_index]
                    if not overlaps(left, right):
                        continue
                    if stream_name == "selected":
                        all_selected_nonoverlap = False
                    overlap_rows.append({
                        "doc_id": doc_id, "stream": stream_name,
                        "left_index": left_index, "left_label": left["label"],
                        "left_start": left["start"], "left_end": left["end"],
                        "right_index": right_index, "right_label": right["label"],
                        "right_start": right["start"], "right_end": right["end"],
                        "cross_label": left["label"] != right["label"],
                        "overlap_chars": min(int(left["end"]), int(right["end"])) - max(int(left["start"]), int(right["start"])),
                    })

        projection = projected_mask(text, selected)
        if result.get("masked_text") != projection or result.get("masked_sha256") != hashlib.sha256(projection.encode()).hexdigest():
            mask_projection_failures.append(doc_id)
        mask_offsets = set()
        for span in selected:
            mask_offsets.update(range(int(span["start"]), int(span["end"])))
        allowed_gold = set()
        doc_full = True
        for gold_index, gold in enumerate(truth["gold"]):
            key = (doc_id, gold["label"], gold["start"], gold["end"])
            gold_exact.add(key)
            allowed_gold.update(range(gold["start"], gold["end"]))
            req_start, req_end = required_range(truth, gold)
            required = set(range(req_start, req_end))
            covered = required & mask_offsets
            outcome = "full" if covered == required else "partial" if covered else "miss"
            doc_full &= outcome == "full"
            totals["gold"] += 1
            totals[outcome] += 1
            per_type[gold["label"]]["gold"] += 1
            per_type[gold["label"]][outcome] += 1
            raw_overlaps = [item for item in raw if item["start"] < gold["end"] and gold["start"] < item["end"]]
            selected_overlaps = [item for item in selected if item["start"] < gold["end"] and gold["start"] < item["end"]]
            item_rows.append({
                "doc_id": doc_id, "gold_index": gold_index, "label": gold["label"],
                "gold_start": gold["start"], "gold_end": gold["end"],
                "required_start": req_start, "required_end": req_end,
                "outcome": outcome, "covered_required_chars": len(covered),
                "required_chars": len(required),
                "raw_exact": any(item["label"] == gold["label"] and item["start"] == gold["start"] and item["end"] == gold["end"] for item in raw),
                "selected_exact": any(item["label"] == gold["label"] and item["start"] == gold["start"] and item["end"] == gold["end"] for item in selected),
                "raw_overlap_count": len(raw_overlaps),
                "selected_overlap_count": len(selected_overlaps),
            })
        totals["all_full_documents"] += int(doc_full)
        for decoy_index, decoy in enumerate(truth["decoys"]):
            offsets = set(range(decoy["start"], decoy["end"]))
            covered = offsets & mask_offsets
            hit = bool(covered)
            totals["decoys"] += 1
            totals["decoy_hits"] += int(hit)
            totals["decoy_masked_chars"] += len(covered)
            decoy_rows.append({
                "doc_id": doc_id, "decoy_index": decoy_index,
                "category": decoy["category"], "start": decoy["start"], "end": decoy["end"],
                "hit": hit, "masked_chars": len(covered),
            })
        excluded = set()
        for item in truth.get("excluded_ambiguous", []):
            excluded.update(range(item["start"], item["end"]))
        general = set(range(len(text))) - allowed_gold - excluded
        totals["overmask_chars_outside_gold"] += len(mask_offsets & general)
        totals["failures"] += int(result.get("failure") is not None)
        totals["raw_items"] += len(raw)
        totals["selected_items"] += len(selected)
        raw_exact.update((doc_id, item["label"], int(item["start"]), int(item["end"])) for item in raw)
        selected_exact.update((doc_id, item["label"], int(item["start"]), int(item["end"])) for item in selected)

    raw_overlap_rows = [item for item in overlap_rows if item["stream"] == "raw"]
    selected_overlap_rows = [item for item in overlap_rows if item["stream"] == "selected"]
    summary = {
        "documents": len(fixture),
        "input_chars": sum(len(row["text"]) for row in fixture.values()),
        "gold": totals["gold"],
        "full": totals["full"], "partial": totals["partial"], "miss": totals["miss"],
        "decoys": totals["decoys"], "decoy_hits": totals["decoy_hits"],
        "decoy_masked_chars": totals["decoy_masked_chars"],
        "overmask_chars_outside_gold": totals["overmask_chars_outside_gold"],
        "all_full_documents": totals["all_full_documents"],
        "raw_items": totals["raw_items"], "selected_items": totals["selected_items"],
        "raw_exact_duplicate_items": totals["raw_exact_duplicate_items"],
        "selected_exact_duplicate_items": totals["selected_exact_duplicate_items"],
        "raw_overlap_pairs": len(raw_overlap_rows),
        "raw_cross_label_overlap_pairs": sum(item["cross_label"] for item in raw_overlap_rows),
        "selected_overlap_pairs": len(selected_overlap_rows),
        "selected_nonoverlap": all_selected_nonoverlap,
        "raw_type_boundary_exact": exact_metrics(gold_exact, raw_exact),
        "selected_type_boundary_exact": exact_metrics(gold_exact, selected_exact),
        "mask_projection_failures": mask_projection_failures,
        "offset_failures": offset_failures,
        "runtime_failures": totals["failures"],
        "latency_ms": meta["latency_ms"],
        "throughput": meta["throughput"],
    }
    per_type_payload = {}
    per_type_rows = []
    for label in ACTIVE:
        gold_keys = {item for item in gold_exact if item[1] == label}
        raw_keys = {item for item in raw_exact if item[1] == label}
        selected_keys = {item for item in selected_exact if item[1] == label}
        payload = {
            "gold": per_type[label]["gold"],
            "full": per_type[label]["full"],
            "partial": per_type[label]["partial"],
            "miss": per_type[label]["miss"],
            "raw_exact": exact_metrics(gold_keys, raw_keys),
            "selected_exact": exact_metrics(gold_keys, selected_keys),
        }
        per_type_payload[label] = payload
        per_type_rows.append({
            "label": label, "gold": payload["gold"], "full": payload["full"],
            "partial": payload["partial"], "miss": payload["miss"],
            "raw_tp": payload["raw_exact"]["tp"], "raw_fp": payload["raw_exact"]["fp"], "raw_fn": payload["raw_exact"]["fn"],
            "selected_tp": payload["selected_exact"]["tp"], "selected_fp": payload["selected_exact"]["fp"], "selected_fn": payload["selected_exact"]["fn"],
        })
    output = {
        "schema_version": "long-document-overlap-evaluation-1",
        "fixture_sha256": sha(args.fixture),
        "run_sha256": sha(args.run),
        "definitions": {
            "primary": "actual selected/masked full-partial-miss plus decoy/general false positives",
            "raw_overlap": "any intersecting pair after candidate postprocess and exact dedup, before final overlap selection",
            "selected_overlap": "any intersecting pair in the actual masking stream; must be zero",
        },
        "summary": summary,
        "per_type": per_type_payload,
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    summary_row = {
        "documents": summary["documents"], "gold": summary["gold"],
        "full": summary["full"], "partial": summary["partial"], "miss": summary["miss"],
        "decoys": summary["decoys"], "decoy_hits": summary["decoy_hits"],
        "overmask_chars": summary["overmask_chars_outside_gold"],
        "raw_duplicate_items": summary["raw_exact_duplicate_items"],
        "raw_overlap_pairs": summary["raw_overlap_pairs"],
        "raw_cross_label_overlap_pairs": summary["raw_cross_label_overlap_pairs"],
        "selected_overlap_pairs": summary["selected_overlap_pairs"],
        "selected_tp": summary["selected_type_boundary_exact"]["tp"],
        "selected_fp": summary["selected_type_boundary_exact"]["fp"],
        "selected_fn": summary["selected_type_boundary_exact"]["fn"],
        "mean_ms": summary["latency_ms"]["mean"],
        "p50_ms": summary["latency_ms"]["p50"],
        "p95_ms": summary["latency_ms"]["p95_nearest_rank"],
        "runtime_failures": summary["runtime_failures"],
    }
    write_csv(args.summary_csv, [summary_row])
    write_csv(args.per_type_csv, per_type_rows)
    write_csv(args.item_csv, item_rows)
    write_csv(args.decoy_csv, decoy_rows)
    write_csv(args.overlap_csv, overlap_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
