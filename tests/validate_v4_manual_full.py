from __future__ import annotations

import hashlib
import json
from pathlib import Path

from diagnose_nhis_mixed_context import MANUAL_FULL
from korean_pii import KoreanPII
from korean_pii.merge import non_overlapping_for_mask


EXPECTATIONS = [
    ("vehicle", "KR_VEHICLE_PLATE", "234나5678", "차량번호는 ", True),
    ("warehouse", "KR_VEHICLE_PLATE", "234나", "창고 구역은 ", False),
    ("person-one", "PERSON", "박서연", "", True),
    ("person-two", "PERSON", "정지훈", "", True),
    ("food-kim", "PERSON", "김", "", False),
    ("derived-minsu", "PERSON", "민수", "", False),
    ("waybill", "KR_NHIS", "87654321098", "택배 운송장 번호는 ", False),
    ("nhis", "KR_NHIS", "23456789012", "건강보험증 번호는 ", True),
    ("address", "KR_LOCATION", "창동 234-5 102동 303호", "", True),
    ("weather-region", "KR_LOCATION", "서울특별시 도봉구", "303호이며, ", False),
    ("email", "EMAIL_ADDRESS", "seoyeon@example.net", "", True),
    ("math", "EMAIL_ADDRESS", "x@y", "", False),
    ("phone", "KR_PHONE_NUMBER", "010-1111-2222", "", True),
    ("product-phone", "KR_PHONE_NUMBER", "010", "제품번호는 CD-", False),
    ("account", "KR_BANK_ACCOUNT", "110-111-111111", "", True),
    ("product-spec", "KR_BANK_ACCOUNT", "110-338-400", "", False),
    ("ip", "IP_ADDRESS", "198.51.100.20", "", True),
    ("version", "IP_ADDRESS", "2.3.4", "", False),
    ("card", "CREDIT_CARD", "5555-5555-5555-4444", "", True),
    ("item", "CREDIT_CARD", "ITEM-5555", "", False),
    ("rrn", "KR_RRN", "900101-1234568", "주민등록번호는 ", True),
    ("order-rrn", "KR_RRN", "900101-1234568", "주문번호는 ORD-", False),
    ("meeting", "DATE_OF_BIRTH", "2026년 11월 18일", "", False),
    ("dob", "DATE_OF_BIRTH", "1992년 3월 4일", "", True),
    ("username", "USERNAME", "seoyeon2026", "", True),
    ("model", "USERNAME", "MODEL2027", "", False),
    ("passport", "KR_PASSPORT", "M87654321", "여권번호는 ", True),
    ("part-passport", "KR_PASSPORT", "M87654321", "부품번호는 PART-", False),
    ("driver", "KR_DRIVER_LICENSE", "12-21-654321-87", "운전면허번호는 ", True),
    ("shipping-driver", "KR_DRIVER_LICENSE", "12-21-654321-87", "배송관리번호는 SHIP-", False),
]


def locate(surface: str, anchor: str) -> tuple[int, int]:
    anchor_start = MANUAL_FULL.index(anchor) if anchor else 0
    start = MANUAL_FULL.index(surface, anchor_start + len(anchor))
    return start, start + len(surface)


def main() -> None:
    pii = KoreanPII()
    spans = list(pii.detect(MANUAL_FULL))
    selected = non_overlapping_for_mask(spans, pii.policy)
    masked = pii.mask(MANUAL_FULL, spans)
    checks = []
    for check_id, label, surface, anchor, sensitive in EXPECTATIONS:
        start, end = locate(surface, anchor)
        exact = any(s.label == label and s.start == start and s.end == end for s in selected)
        overlap = any(s.label == label and s.start < end and start < s.end for s in selected)
        checks.append({
            "id": check_id,
            "label": label,
            "surface": surface,
            "range": [start, end],
            "sensitive": sensitive,
            "detected_exact": exact,
            "detected_overlap": overlap,
            "passed": exact if sensitive else not overlap,
        })
    payload = {
        "input_chars": len(MANUAL_FULL),
        "input_sha256": hashlib.sha256(MANUAL_FULL.encode()).hexdigest(),
        "original": MANUAL_FULL,
        "masked": masked,
        "masked_sha256": hashlib.sha256(masked.encode()).hexdigest(),
        "all_checks_passed": all(item["passed"] for item in checks),
        "failed_checks": [item for item in checks if not item["passed"]],
        "checks": checks,
        "nhis_trace": list(pii.nhis_verifier.last_trace),
    }
    Path("results/v4-manual-full.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
