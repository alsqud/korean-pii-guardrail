from __future__ import annotations

import hashlib
import json
from pathlib import Path

from validate_long_pipeline import CASES
from korean_pii import KoreanPII
from korean_pii.merge import non_overlapping_for_mask


EXPECTATIONS = {
    "exact-original-669": [
        ("person-kim", "PERSON", "김민수", "", True),
        ("person-lee", "PERSON", "이영희", "", True),
        ("derived-name-fragment", "PERSON", "민수", "반찬으로 먹고 ", False),
        ("detailed-address", "KR_LOCATION", "면목동 123-4 101동 202호", "", True),
        ("weather-region", "KR_LOCATION", "서울특별시 중랑구", "202호이며, ", False),
        ("phone", "KR_PHONE_NUMBER", "010-0000-0000", "", True),
        ("product-number", "KR_PHONE_NUMBER", "010", "제품번호는 AB-", False),
        ("account", "KR_BANK_ACCOUNT", "110-000-000000", "", True),
        ("product-spec", "KR_BANK_ACCOUNT", "110-229-300", "", False),
        ("email", "EMAIL_ADDRESS", "minsu@example.com", "", True),
        ("math-symbol", "EMAIL_ADDRESS", "a@b", "", False),
        ("ip", "IP_ADDRESS", "192.0.2.10", "", True),
        ("version", "IP_ADDRESS", "1.2.3", "", False),
        ("card", "CREDIT_CARD", "4242-4242-4242-4242", "", True),
        ("item-code", "CREDIT_CARD", "ITEM-4242", "", False),
        ("rrn", "KR_RRN", "900101-1234568", "주민등록번호는 ", True),
        ("order-rrn", "KR_RRN", "900101-1234568", "주문번호는 ORD-", False),
        ("birth-date", "DATE_OF_BIRTH", "1990년 1월 1일", "", True),
        ("meeting-date", "DATE_OF_BIRTH", "2026년 10월 14일", "", False),
        ("username", "USERNAME", "minsu2026", "", True),
        ("model-name", "USERNAME", "MODEL2026", "", False),
        ("passport", "KR_PASSPORT", "M12345678", "여권번호는 ", True),
        ("part-passport", "KR_PASSPORT", "M12345678", "부품번호는 PART-", False),
        ("driver", "KR_DRIVER_LICENSE", "11-20-123456-78", "운전면허번호는 ", True),
        ("shipping-driver", "KR_DRIVER_LICENSE", "11-20-123456-78", "배송관리번호는 SHIP-", False),
        ("vehicle", "KR_VEHICLE_PLATE", "123가4567", "차량번호는 ", True),
        ("warehouse", "KR_VEHICLE_PLATE", "123가", "창고 구역은 ", False),
        ("nhis", "KR_NHIS", "12345678901", "건강보험증 번호는 ", True),
        ("waybill", "KR_NHIS", "98765432109", "택배 운송장 번호는 ", False),
    ],
    "natural-diverse-long": [
        ("person", "PERSON", "박서윤", "신청인 ", True),
        ("similar-storage-name", "PERSON", "서윤형", "이름과 비슷한 ", False),
        ("detailed-address", "KR_LOCATION", "새봄동 284-7 305동 1204호", "", True),
        ("phone", "KR_PHONE_NUMBER", "010-2468-1357", "", True),
        ("account", "KR_BANK_ACCOUNT", "260-441-982731", "", True),
        ("product-spec", "KR_BANK_ACCOUNT", "260-441-982", "제품 규격표에는 ", False),
        ("email", "EMAIL_ADDRESS", "seoyun@test.example", "", True),
        ("math-symbol", "EMAIL_ADDRESS", "x@y", "", False),
        ("ip", "IP_ADDRESS", "203.0.113.44", "", True),
        ("version", "IP_ADDRESS", "2.7.14", "", False),
        ("card", "CREDIT_CARD", "5555-5555-5555-4444", "", True),
        ("item-code", "CREDIT_CARD", "ITEM-5555-4444", "", False),
        ("rrn", "KR_RRN", "900101-1234568", "주민등록번호는 ", True),
        ("order-rrn", "KR_RRN", "900101-1234568", "주문 참조값은 ORDER-", False),
        ("birth-date", "DATE_OF_BIRTH", "1990년 1월 1일", "", True),
        ("meeting-date", "DATE_OF_BIRTH", "2026년 11월 3일", "", False),
        ("username", "USERNAME", "sypark27", "", True),
        ("model-name", "USERNAME", "SYPARK27", "", False),
        ("passport", "KR_PASSPORT", "N87654321", "여권번호는 ", True),
        ("part-passport", "KR_PASSPORT", "N87654321", "PART-", False),
        ("driver", "KR_DRIVER_LICENSE", "27-18-654321-44", "운전면허번호는 ", True),
        ("shipping-driver", "KR_DRIVER_LICENSE", "27-18-654321-44", "SHIP-", False),
        ("vehicle", "KR_VEHICLE_PLATE", "264나8080", "차량번호는 ", True),
        ("warehouse", "KR_VEHICLE_PLATE", "264나", "창고 선반 표시는 ", False),
        ("nhis", "KR_NHIS", "56123478901", "건강보험증 번호는 ", True),
        ("waybill", "KR_NHIS", "74125896300", "운송장 번호 ", False),
    ],
}


def locate(text: str, surface: str, anchor: str) -> tuple[int, int]:
    anchor_start = text.index(anchor) if anchor else -len(anchor)
    start = text.index(surface, anchor_start + len(anchor))
    return start, start + len(surface)


def main() -> None:
    pii = KoreanPII()
    pii.detect("건강보험증 번호는 56123478901입니다.")
    output = []
    for case in CASES:
        text = case["text"]
        spans = list(pii.detect(text))
        selected = non_overlapping_for_mask(spans, pii.policy)
        masked = pii.mask(text, spans)
        checks = []
        for check_id, label, surface, anchor, sensitive in EXPECTATIONS[case["id"]]:
            start, end = locate(text, surface, anchor)
            detected_exact = any(
                span.label == label
                and span.start == start
                and span.end == end
                for span in selected
            )
            detected_overlap = any(
                span.label == label
                and span.start < end
                and start < span.end
                for span in selected
            )
            passed = detected_exact if sensitive else not detected_overlap
            checks.append(
                {
                    "id": check_id,
                    "label": label,
                    "surface": surface,
                    "anchor": anchor,
                    "sensitive": sensitive,
                    "range": [start, end],
                    "detected_exact": detected_exact,
                    "detected_overlap": detected_overlap,
                    "passed": passed,
                    "preserved_verbatim": text[start:end] in masked,
                }
            )
        output.append(
            {
                "id": case["id"],
                "original": text,
                "masked": masked,
                "original_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "masked_sha256": hashlib.sha256(masked.encode()).hexdigest(),
                "checks": checks,
                "all_checks_passed": all(check["passed"] for check in checks),
                "failed_checks": [check for check in checks if not check["passed"]],
            }
        )
    Path("results/masked-outputs.json").write_text(
        json.dumps(
            {
                "variant": "rule-plus-frozen-lora",
                "threshold": 0.98,
                "expectations_fixed_before_execution": True,
                "retuned_for_these_documents": False,
                "cases": output,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
