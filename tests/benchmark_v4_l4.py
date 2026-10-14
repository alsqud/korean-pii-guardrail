from __future__ import annotations

import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

import torch
import transformers

from diagnose_nhis_mixed_context import MANUAL_FULL
from korean_pii import KoreanPII
from validate_long_pipeline import CASES
from validate_v4_reordered_manual import build_reordered


REPEATS_SEQUENTIAL = 5
REPEATS_QUEUE_BATCH = 3
QUEUE_BATCH_SIZES = (1, 2, 4, 8)
REPEATS_NHIS_INCREMENT = 5


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def stats(values: list[float]) -> dict:
    return {
        "sample_count": len(values),
        "mean": round(statistics.fmean(values), 3),
        "p50": round(percentile(values, 0.50), 3),
        "p95": round(percentile(values, 0.95), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def memory() -> dict:
    return {
        "allocated_mib": round(torch.cuda.memory_allocated() / 2**20, 3),
        "reserved_mib": round(torch.cuda.memory_reserved() / 2**20, 3),
        "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 2**20, 3),
        "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 2**20, 3),
    }


def timed_mask(pii: KoreanPII, text: str) -> tuple[float, str]:
    torch.cuda.synchronize()
    started = time.perf_counter()
    masked = pii.mask(text)
    torch.cuda.synchronize()
    return (time.perf_counter() - started) * 1000, sha256_text(masked)


def source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    total_started = time.perf_counter()
    docs = [
        (CASES[0]["id"], CASES[0]["text"]),
        (CASES[1]["id"], CASES[1]["text"]),
        ("manual-full-680", MANUAL_FULL),
        ("manual-reordered-680", build_reordered()),
    ]
    assert all(669 <= len(text) <= 900 for _, text in docs)

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    constructor_started = time.perf_counter()
    pii = KoreanPII()
    constructor_ms = (time.perf_counter() - constructor_started) * 1000
    before_cold = memory()
    cold_ms, cold_mask_sha = timed_mask(pii, docs[0][1])
    cold = {
        "constructor_ms": round(constructor_ms, 3),
        "first_request_including_lazy_model_load_ms": round(cold_ms, 3),
        "document_id": docs[0][0],
        "document_chars": len(docs[0][1]),
        "masked_sha256": cold_mask_sha,
        "memory_before": before_cold,
        "memory_after": memory(),
        "loaded_models_after": list(pii.models.loaded_models),
        "kiwi_loaded_after": pii.kiwi.loaded,
        "nhis_verifier_loaded_after": pii.nhis_verifier.loaded,
    }

    torch.cuda.reset_peak_memory_stats()
    sequential_values = []
    sequential_failures = []
    sequential_outputs = []
    sequential_started = time.perf_counter()
    for repeat in range(REPEATS_SEQUENTIAL):
        for document_id, text in docs:
            try:
                elapsed_ms, masked_sha = timed_mask(pii, text)
                sequential_values.append(elapsed_ms)
                sequential_outputs.append(
                    {"document_id": document_id, "repeat": repeat, "masked_sha256": masked_sha}
                )
            except Exception as exc:
                sequential_failures.append({"document_id": document_id, "error": type(exc).__name__})
    sequential_total_s = time.perf_counter() - sequential_started
    sequential = {
        "request_latency_ms": stats(sequential_values),
        "throughput_docs_per_second": round(len(sequential_values) / sequential_total_s, 4),
        "total_seconds": round(sequential_total_s, 3),
        "failure_count": len(sequential_failures),
        "failures": sequential_failures,
        "unique_output_hash_count": len({item["masked_sha256"] for item in sequential_outputs}),
        "memory": memory(),
    }

    queue_results = {}
    for batch_size in QUEUE_BATCH_SIZES:
        torch.cuda.reset_peak_memory_stats()
        completion_values = []
        service_values = []
        failures = []
        batch_durations = []
        request_count = 0
        for repeat in range(REPEATS_QUEUE_BATCH):
            batch = [docs[(repeat * batch_size + index) % len(docs)] for index in range(batch_size)]
            torch.cuda.synchronize()
            batch_started = time.perf_counter()
            for request_index, (document_id, text) in enumerate(batch):
                service_started = time.perf_counter()
                try:
                    pii.mask(text)
                    torch.cuda.synchronize()
                    ended = time.perf_counter()
                    service_values.append((ended - service_started) * 1000)
                    completion_values.append((ended - batch_started) * 1000)
                except Exception as exc:
                    failures.append(
                        {
                            "repeat": repeat,
                            "request_index": request_index,
                            "document_id": document_id,
                            "error": type(exc).__name__,
                        }
                    )
            batch_ended = time.perf_counter()
            batch_durations.append(batch_ended - batch_started)
            request_count += len(batch)
        queue_results[str(batch_size)] = {
            "execution_mode": "single-worker FIFO queue; simultaneous batch arrival simulated; no parallel GPU forwards",
            "batch_repeats": REPEATS_QUEUE_BATCH,
            "request_count": request_count,
            "completion_latency_ms_including_queue_wait": stats(completion_values),
            "service_latency_ms": stats(service_values),
            "throughput_docs_per_second": round(
                (request_count - len(failures)) / sum(batch_durations), 4
            ),
            "total_seconds": round(sum(batch_durations), 3),
            "failure_count": len(failures),
            "failures": failures,
            "memory": memory(),
        }

    rule_ms = []
    filter_ms = []
    forward_ms = []
    nhis_failures = []
    for repeat in range(REPEATS_NHIS_INCREMENT):
        for document_id, text in docs:
            try:
                started = time.perf_counter()
                direct = pii.rules.detect(text)
                rule_ms.append((time.perf_counter() - started) * 1000)
                torch.cuda.synchronize()
                started = time.perf_counter()
                pii.nhis_verifier.filter(text, direct)
                torch.cuda.synchronize()
                filter_ms.append((time.perf_counter() - started) * 1000)
                forward_ms.append(pii.nhis_verifier.last_inference_ms)
            except Exception as exc:
                nhis_failures.append({"document_id": document_id, "error": type(exc).__name__})
    nhis_increment = {
        "sample_count": len(filter_ms),
        "direct_rule_detection_ms": stats(rule_ms),
        "verifier_total_increment_ms": stats(filter_ms),
        "verifier_model_forward_ms": stats(forward_ms),
        "failure_count": len(nhis_failures),
        "failures": nhis_failures,
        "note": "Verifier total includes field-link parsing, tokenization, transfer, frozen LoRA forward, and decision; model forward is the instrumented raw forward only.",
    }

    package_root = Path(__file__).resolve().parent / "followup-v4" / "korean_pii"
    model_manifest = json.loads((package_root / "model-manifest.json").read_text(encoding="utf-8"))
    payload = {
        "scope": "L4 synthetic long-document performance; not a 28K benchmark and not a production SLA",
        "method": {
            "same_reused_pipeline_instance": True,
            "unsafe_parallel_gpu_forwards_used": False,
            "queue_semantics": "single worker, FIFO, simultaneous arrivals represented by a batch timestamp",
            "sequential_repeats_per_document": REPEATS_SEQUENTIAL,
            "queue_batch_repeats": REPEATS_QUEUE_BATCH,
            "nhis_increment_repeats_per_document": REPEATS_NHIS_INCREMENT,
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "cuda_runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(),
            "gpu_total_mib": round(torch.cuda.get_device_properties(0).total_memory / 2**20, 3),
        },
        "source_identity": {
            "korean_pii_tree_sha256": source_tree_sha256(package_root),
            "policy_version": pii.policy.policy_version,
            "policy_sha256": pii.policy.sha256,
            "nhis_adapter_sha256": pii.nhis_verifier.status["adapter_sha256"],
            "model_manifest": model_manifest,
        },
        "documents": [
            {"id": document_id, "chars": len(text), "sha256": sha256_text(text)}
            for document_id, text in docs
        ],
        "cold": cold,
        "warm_sequential": sequential,
        "queue_batches": queue_results,
        "nhis_recheck_increment": nhis_increment,
        "total_runtime_seconds": round(time.perf_counter() - total_started, 3),
        "limitations": [
            "Four synthetic 669-900 character documents; no real PII and no full 28K run.",
            "Queue batches measure one shared model instance and include FIFO wait; they do not claim thread-safe parallel inference.",
            "CUDA allocator figures are process-local allocated/reserved peaks, not whole-device nvidia-smi utilization.",
            "Small samples make p95 directional rather than an SLA bound.",
        ],
    }
    Path("results/v4-l4-performance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
