from __future__ import annotations

import hashlib
import json
from pathlib import Path

from korean_pii import KoreanPII
from korean_pii.merge import non_overlapping_for_mask


INDEPENDENT_LONG_TEXT = (
    "새봄 청소년센터는 지원금 정산과 창고 출고 기록을 함께 검토했습니다. "
    "출고 참조 코드는 CASE-850305-2234564이고, 이것은 주민 식별값이 아니라 물류 시스템의 내부 키입니다. "
    "신청인의 실제 주민등록번호는 850305-2234564로 별도 본인확인 칸에 적었습니다. "
    "비고란에는 사람 이름을 닮은 오지훈 폴더명을 사람으로 처리하지 말라는 안내가 있습니다. "
    "실제 상담 담당자는 강하윤님이며 연락처는 010-3579-2468입니다. "
    "환급 계좌는 푸른은행 451-720-963852이고 제품 배치값 451-720-963은 그대로 두어야 합니다. "
    "거주지는 대전광역시 유성구 별빛동 77-3 202동 804호이고 행사 장소인 대전광역시 유성구는 일반 문맥입니다. "
    "로그인 사용자명은 hana.kim_2이고 장비 모델 DEVICEZ99와 재고 코드 USERBOX77은 계정이 아닙니다. "
    "안내 메일은 hayoon@example.test이고 문서 예시의 a@b는 수학 기호입니다. "
    "접속 주소는 198.51.100.88이며 장치 버전 3.11.7은 IP가 아닙니다. "
    "보험 자격표의 건강보험증 번호는 73456128903이지만 화물 조회 운송장 번호 60987412350은 배송용 숫자입니다. "
    "차량번호 318다7421과 운전면허번호 42-31-765432-19는 보호하고, 선반 표기 318다와 SHIP-42-31-765432-19는 보존해야 합니다. "
    "마지막 검토자는 앞뒤 문맥이 가까워도 각 필드의 경계와 용도를 따로 판단하라고 기록했습니다."
)
assert len(INDEPENDENT_LONG_TEXT) >= 650


CASES = [
    {
        "id": "independent-natural-boundaries",
        "text": INDEPENDENT_LONG_TEXT,
        "checks": [
            ("real-person", "PERSON", "강하윤", "실제 상담 담당자는 ", True),
            ("name-like-folder", "PERSON", "오지훈", "사람 이름을 닮은 ", False),
            ("linked-username", "USERNAME", "hana.kim_2", "로그인 사용자명은 ", True),
            ("equipment-model", "USERNAME", "DEVICEZ99", "장비 모델 ", False),
            ("inventory-code", "USERNAME", "USERBOX77", "재고 코드 ", False),
            ("real-rrn", "KR_RRN", "850305-2234564", "실제 주민등록번호는 ", True),
            ("case-code-rrn", "KR_RRN", "850305-2234564", "출고 참조 코드는 CASE-", False),
            ("real-nhis", "KR_NHIS", "73456128903", "건강보험증 번호는 ", True),
            ("waybill", "KR_NHIS", "60987412350", "운송장 번호 ", False),
            ("driver", "KR_DRIVER_LICENSE", "42-31-765432-19", "운전면허번호 ", True),
            ("shipping-driver", "KR_DRIVER_LICENSE", "42-31-765432-19", "SHIP-", False),
            ("vehicle", "KR_VEHICLE_PLATE", "318다7421", "차량번호 ", True),
            ("shelf", "KR_VEHICLE_PLATE", "318다", "선반 표기 ", False),
        ],
        "ambiguous": [],
    },
    {
        "id": "explicit-prefixed-rrn",
        "text": "민감정보 확인란의 주민등록번호: RRN-850305-2234564입니다.",
        "checks": [
            ("explicit-prefixed-real-rrn", "KR_RRN", "850305-2234564", "RRN-", True),
        ],
        "ambiguous": [],
    },
    {
        "id": "username-positive-and-code-negative",
        "text": "담당 계정 아이디는 agent-72이고 사용자명이 아니라 장비 라벨인 USER-72는 보존합니다.",
        "checks": [
            ("linked-user", "USERNAME", "agent-72", "담당 계정 아이디는 ", True),
            ("device-label", "USERNAME", "USER-72", "장비 라벨인 ", False),
        ],
        "ambiguous": [],
    },
    {
        "id": "free-handle-positive",
        "text": "문의 담당 계정은 @bright_day에게 메시지를 보내면 됩니다.",
        "checks": [
            ("at-handle", "USERNAME", "@bright_day", "계정은 ", True),
        ],
        "ambiguous": [],
    },
    {
        "id": "natural-username-positive",
        "text": "사용자 hana2026이 로그인했고 장비 코드 hana2026은 계정과 무관합니다.",
        "checks": [
            ("natural-linked-user", "USERNAME", "hana2026", "사용자 ", True),
            ("same-shaped-device-code", "USERNAME", "hana2026", "장비 코드 ", False),
        ],
        "ambiguous": [],
    },
    {
        "id": "ambiguous-name-noun",
        "text": "김하늘 파일을 전달했고 담당자 김하늘님이 수신 여부를 확인했습니다.",
        "checks": [
            ("explicit-person", "PERSON", "김하늘", "담당자 ", True),
        ],
        "ambiguous": [
            ("bare-name-before-file", "PERSON", "김하늘", "", None),
        ],
    },
]


def locate(text: str, surface: str, anchor: str) -> tuple[int, int]:
    anchor_start = text.index(anchor) if anchor else 0
    start = text.index(surface, anchor_start + len(anchor))
    return start, start + len(surface)


def main() -> None:
    pii = KoreanPII()
    pii.detect("건강보험증 번호는 73456128903입니다.")
    results = []
    for case in CASES:
        text = case["text"]
        spans = list(pii.detect(text))
        selected = non_overlapping_for_mask(spans, pii.policy)
        masked = pii.mask(text, spans)
        checks = []
        for check_id, label, surface, anchor, sensitive in case["checks"]:
            start, end = locate(text, surface, anchor)
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
        ambiguous = []
        for check_id, label, surface, anchor, _ in case["ambiguous"]:
            start, end = locate(text, surface, anchor)
            ambiguous.append({
                "id": check_id,
                "label": label,
                "surface": surface,
                "range": [start, end],
                "detected_exact": any(s.label == label and s.start == start and s.end == end for s in selected),
                "detected_overlap": any(s.label == label and s.start < end and start < s.end for s in selected),
                "scored": False,
            })
        results.append({
            "id": case["id"],
            "original": text,
            "masked": masked,
            "original_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "masked_sha256": hashlib.sha256(masked.encode()).hexdigest(),
            "checks": checks,
            "ambiguous": ambiguous,
            "all_scored_checks_passed": all(item["passed"] for item in checks),
            "failed_checks": [item for item in checks if not item["passed"]],
            "selected_spans": [
                {**span.to_dict(), "substring": text[span.start:span.end]}
                for span in selected
            ],
        })
    payload = {
        "scope": "fixed boundary/context regression; no threshold or LoRA changes",
        "cases": results,
        "all_scored_checks_passed": all(item["all_scored_checks_passed"] for item in results),
    }
    output = Path("results/v3-independent-regressions.json")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
