#!/usr/bin/env python3
"""Run the hybrid detector and save raw, selected, and masked outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import time
from pathlib import Path

import torch

from korean_pii import KoreanPII
from korean_pii.merge import mask_text, non_overlapping_for_mask


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    documents = load_json_lines(args.fixture)
    if not documents:
        raise ValueError("fixture is empty")
    if args.output.exists() or args.output.with_suffix(".meta.json").exists():
        raise FileExistsError("refusing to overwrite an existing evaluation output")

    torch.set_num_threads(4)
    try:
        torch.set_num_interop_threads(4)
    except RuntimeError:
        pass

    load_started = time.perf_counter()
    engine = KoreanPII()
    engine.address_gazetteer.load()
    load_seconds = time.perf_counter() - load_started

    engine.detect(documents[0]["text"])
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    warmup_started = time.perf_counter()
    engine.detect(documents[0]["text"])
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    warmup_seconds = time.perf_counter() - warmup_started

    records = []
    for document in documents:
        text = document["text"]
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        started = time.perf_counter()
        try:
            raw = list(engine.detect(text))
            selected = non_overlapping_for_mask(raw, engine.policy)
            masked = mask_text(text, raw, engine.policy)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            failure = None
        except Exception as exc:
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            raw, selected, masked = [], [], text
            failure = {"type": type(exc).__name__, "message": str(exc)[:300]}
        elapsed_ms = (time.perf_counter() - started) * 1000
        records.append({
            "doc_id": document["doc_id"],
            "elapsed_ms": round(elapsed_ms, 3),
            "input_chars": len(text),
            "raw_prediction_count": len(raw),
            "selected_prediction_count": len(selected),
            "raw_predictions": [span.to_dict() for span in raw],
            "selected_predictions": [span.to_dict() for span in selected],
            "masked_text": masked,
            "masked_sha256": hashlib.sha256(masked.encode()).hexdigest(),
            "details": {"raw_before_overlap_selection": len(raw)},
            "failure": failure,
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    latencies = [record["elapsed_ms"] for record in records]
    elapsed_seconds = sum(latencies) / 1000
    metadata = {
        "schema_version": "hybrid-pipeline-run-1",
        "mode": "hybrid_pipeline",
        "fixture_sha256": file_sha256(args.fixture),
        "documents": len(records),
        "load_seconds_excluded": load_seconds,
        "warmup_seconds_excluded": warmup_seconds,
        "batch_size": 1,
        "device": os.getenv(engine.policy.runtime["device_env"], engine.policy.runtime["device_default"]),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "latency_ms": {
            "mean": statistics.fmean(latencies),
            "p50": statistics.median(latencies),
            "p95_nearest_rank": sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1],
        },
        "throughput": {
            "documents_per_second": len(records) / elapsed_seconds,
            "characters_per_second": sum(record["input_chars"] for record in records) / elapsed_seconds,
        },
        "runtime": {
            "pipeline_profile": engine.status.get("pipeline_profile"),
            "policy_version": engine.policy.policy_version,
            "policy_sha256": engine.policy.sha256,
            "loaded_models": list(engine.models.loaded_models),
            "address_gazetteer": engine.address_gazetteer.status,
            "raw_prediction_definition": "postprocessed exact-deduplicated spans before overlap selection",
            "selected_prediction_definition": "non-overlapping spans used for masking",
            "masked_text_saved": True,
        },
        "failures": sum(record["failure"] is not None for record in records),
    }
    args.output.with_suffix(".meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
