from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from fixtures import EXACT_669_TEXT
from korean_pii import KoreanPII
from korean_pii.merge import non_overlapping_for_mask


NATURAL_LONG_TEXT = (
    "해오름 복지센터는 가을 지원 신청서를 검토하면서 접수 기록과 물류 메모를 한 문서에 정리했습니다. "
    "신청인 박서윤님의 거주지는 부산광역시 수영구 새봄동 284-7 305동 1204호이고, 연락처는 010-2468-1357입니다. "
    "담당자는 이름과 비슷한 서윤형 보관함이나 박스 표기를 사람 이름으로 처리하지 말라고 남겼습니다. "
    "환급 계좌는 한빛은행 260-441-982731이며 제품 규격표에는 260-441-982라는 부품 치수도 함께 적혀 있습니다. "
    "안내 이메일은 seoyun@test.example이고 교육 자료에서는 x@y를 변수 표기로 사용했습니다. "
    "내부 접속 IP는 203.0.113.44이지만 장비 펌웨어 버전은 2.7.14라서 서로 구분해야 합니다. "
    "결제 확인 카드번호는 5555-5555-5555-4444이고 상품 라벨은 ITEM-5555-4444입니다. "
    "주민등록번호는 900101-1234568로 기재됐고 주문 참조값은 ORDER-900101-1234568입니다. "
    "생년월일은 1990년 1월 1일이며 행정 회의일은 2026년 11월 3일입니다. "
    "로그인 아이디는 sypark27이고 장비 모델은 SYPARK27입니다. 여권번호는 N87654321이며 부품 상자에는 PART-N87654321이 인쇄됐습니다. "
    "운전면허번호는 27-18-654321-44이고 배송 묶음의 관리표시는 SHIP-27-18-654321-44입니다. "
    "차량번호는 264나8080이고 창고 선반 표시는 264나입니다. 건강보험증 번호는 56123478901이며 자격 확인 서류에 기록했습니다. "
    "반면 화물 위치 조회용 운송장 번호 74125896300은 고객의 보험 식별값이 아니라 배송 흐름을 추적하는 숫자입니다. "
    "마지막으로 주소 주변의 날씨, 행사 장소, 일반 문서 번호는 원래 문맥을 유지한 채 민감값만 보호해야 합니다."
)
assert len(NATURAL_LONG_TEXT) >= 650


CASES = [
    {
        "id": "exact-original-669",
        "text": EXACT_669_TEXT,
        "targets": [
            {"id": "nhis-positive", "label": "KR_NHIS", "surface": "12345678901", "anchor": "건강보험증 번호는 ", "sensitive": True},
            {"id": "waybill-negative", "label": "KR_NHIS", "surface": "98765432109", "anchor": "택배 운송장 번호는 ", "sensitive": False},
            {"id": "driver-positive", "label": "KR_DRIVER_LICENSE", "surface": "11-20-123456-78", "anchor": "운전면허번호는 ", "sensitive": True},
            {"id": "shipping-driver-negative", "label": "KR_DRIVER_LICENSE", "surface": "11-20-123456-78", "anchor": "배송관리번호는 SHIP-", "sensitive": False},
        ],
    },
    {
        "id": "natural-diverse-long",
        "text": NATURAL_LONG_TEXT,
        "targets": [
            {"id": "nhis-positive", "label": "KR_NHIS", "surface": "56123478901", "anchor": "건강보험증 번호는 ", "sensitive": True},
            {"id": "waybill-negative", "label": "KR_NHIS", "surface": "74125896300", "anchor": "운송장 번호 ", "sensitive": False},
            {"id": "driver-positive", "label": "KR_DRIVER_LICENSE", "surface": "27-18-654321-44", "anchor": "운전면허번호는 ", "sensitive": True},
            {"id": "shipping-driver-negative", "label": "KR_DRIVER_LICENSE", "surface": "27-18-654321-44", "anchor": "SHIP-", "sensitive": False},
            {"id": "vehicle-positive", "label": "KR_VEHICLE_PLATE", "surface": "264나8080", "anchor": "차량번호는 ", "sensitive": True},
            {"id": "warehouse-negative", "label": "KR_VEHICLE_PLATE", "surface": "264나", "anchor": "창고 선반 표시는 ", "sensitive": False},
        ],
    },
]


def locate(text: str, item: dict) -> tuple[int, int]:
    anchor_start = text.index(item["anchor"])
    start = text.index(item["surface"], anchor_start + len(item["anchor"]))
    return start, start + len(item["surface"])


def span_record(text: str, span) -> dict:
    value = span.to_dict()
    value["substring"] = text[span.start:span.end]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    pii = KoreanPII()
    # Load every existing model; integrated variant also loads the frozen NHIS verifier.
    pii.detect("건강보험증 번호는 56123478901입니다.")
    results = []
    for case in CASES:
        text = case["text"]
        started = time.perf_counter()
        spans = list(pii.detect(text))
        elapsed_ms = (time.perf_counter() - started) * 1000
        selected = non_overlapping_for_mask(spans, pii.policy)
        masked = pii.mask(text, spans)
        target_results = []
        for item in case["targets"]:
            start, end = locate(text, item)
            exact = [span for span in spans if span.label == item["label"] and span.start == start and span.end == end]
            overlapping = [span for span in spans if span.label == item["label"] and span.start < end and start < span.end]
            selected_exact = [span for span in selected if span.label == item["label"] and span.start == start and span.end == end]
            detected = bool(exact and selected_exact)
            target_results.append({
                **item,
                "range": [start, end],
                "detected_exact": detected,
                "semantic_correct": detected == item["sensitive"],
                "exact_spans": [span_record(text, span) for span in exact],
                "overlapping_spans": [span_record(text, span) for span in overlapping],
                "preserved_in_mask": text[start:end] in masked if not item["sensitive"] else None,
            })
        trace = list(getattr(getattr(pii, "nhis_verifier", None), "last_trace", ()))
        non_nhis_records = [span_record(text, span) for span in spans if span.label != "KR_NHIS"]
        results.append({
            "id": case["id"],
            "identity": {"chars": len(text), "utf8_bytes": len(text.encode()), "sha256": hashlib.sha256(text.encode()).hexdigest()},
            "elapsed_ms_warm": elapsed_ms,
            "offsets_valid": all(0 <= span.start < span.end <= len(text) for span in spans),
            "masked_sha256": hashlib.sha256(masked.encode()).hexdigest(),
            "target_results": target_results,
            "targets_all_semantic_correct": all(item["semantic_correct"] for item in target_results),
            "nhis_verifier_trace": trace,
            "span_counts": {label: sum(span.label == label for span in spans) for label in sorted({span.label for span in spans})},
            "non_nhis_span_sha256": hashlib.sha256(
                json.dumps(non_nhis_records, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
        })
    payload = {
        "variant": args.variant,
        "scope": "full pipeline, warm models, exact original 669 and new natural diverse long synthetic document",
        "policy_sha256": pii.policy.sha256,
        "status": pii.status,
        "median_warm_ms": statistics.median(item["elapsed_ms_warm"] for item in results),
        "all_offsets_valid": all(item["offsets_valid"] for item in results),
        "all_targets_semantic_correct": all(item["targets_all_semantic_correct"] for item in results),
        "cases": results,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
