from __future__ import annotations

import hashlib
import json
from pathlib import Path

from korean_pii import KoreanPII


MANUAL_FULL = (
    "차량번호는 234나5678이고 창고 구역은 234나입니다. 박서연님과 정지훈님이 신청했습니다. "
    "김은 도시락 반찬이고 민수용 장비는 별도 선반에 보관합니다. "
    "택배 운송장 번호는 87654321098이고 건강보험증 번호는 23456789012입니다. "
    "거주지는 서울특별시 도봉구 창동 234-5 102동 303호이며, 서울특별시 도봉구의 날씨도 확인했습니다. "
    "이메일은 seoyeon@example.net이고 수학에서는 x@y라는 기호를 사용했습니다. "
    "연락처는 010-1111-2222이고 제품번호는 CD-010-ABC입니다. "
    "입금 계좌는 신한은행 110-111-111111이며, 제품 규격은 110-338-400입니다. "
    "접속 IP는 198.51.100.20이며 프로그램 버전은 2.3.4입니다. "
    "결제 카드번호는 5555-5555-5555-4444이고 상품코드는 ITEM-5555입니다. "
    "주민등록번호는 900101-1234568이고 주문번호는 ORD-900101-1234568입니다. "
    "회의일은 2026년 11월 18일이며 생년월일은 1992년 3월 4일입니다. "
    "로그인 아이디는 seoyeon2026이고 제품 모델명은 MODEL2027입니다. "
    "여권번호는 M87654321이고 부품번호는 PART-M87654321입니다. "
    "운전면허번호는 12-21-654321-87이고 배송관리번호는 SHIP-12-21-654321-87입니다."
)


CASES = [
    ("manual-full", MANUAL_FULL, {"87654321098": False, "23456789012": True}),
    ("negative-then-positive", "택배 운송장 번호는 87654321098이고 건강보험증 번호는 23456789012입니다.", {"87654321098": False, "23456789012": True}),
    ("positive-then-negative", "건강보험증 번호는 23456789012이고 택배 운송장 번호는 87654321098입니다.", {"23456789012": True, "87654321098": False}),
    ("comma-negative-positive", "택배 운송장 번호는 87654321098, 건강보험증 번호는 23456789012입니다.", {"87654321098": False, "23456789012": True}),
    ("semicolon-negative-positive", "택배 운송장 번호는 87654321098; 건강보험증 번호는 23456789012입니다.", {"87654321098": False, "23456789012": True}),
    ("period-negative-positive", "택배 운송장 번호는 87654321098입니다. 건강보험증 번호는 23456789012입니다.", {"87654321098": False, "23456789012": True}),
    ("distant-negative-positive", "택배 운송장 번호는 87654321098이고 배송 상태를 확인한 뒤 담당자가 별도 문서를 열었습니다. 건강보험증 번호는 23456789012입니다.", {"87654321098": False, "23456789012": True}),
    ("standalone-negative", "화물 조회용 택배 운송장 번호는 87654321098입니다.", {"87654321098": False}),
    ("standalone-positive", "고객의 건강보험증 번호는 23456789012입니다.", {"23456789012": True}),
    ("logistics-near-true-positive", "택배 서류를 확인한 뒤 고객의 건강보험증 번호는 23456789012입니다.", {"23456789012": True}),
    ("health-near-true-negative", "건강보험증 서류를 동봉한 택배 운송장 번호는 87654321098입니다.", {"87654321098": False}),
    ("ambiguous-number", "검토 대상 번호는 87654321098입니다.", {"87654321098": None}),
]


def main() -> None:
    pii = KoreanPII()
    pii.detect("건강보험증 번호는 23456789012입니다.")
    results = []
    for case_id, text, labels in CASES:
        direct = [
            span for span in pii.rules.detect(text)
            if span.label == "KR_NHIS" and span.source == "rule:nhis-shape"
        ]
        spans = list(pii.detect(text))
        traces = {
            (item["start"], item["end"]): item
            for item in pii.nhis_verifier.last_trace
        }
        candidates = []
        for span in direct:
            value = text[span.start:span.end]
            model_input, window_start, window_end = pii.nhis_verifier._model_input(text, span)
            trace = traces.get((span.start, span.end), {})
            final_exact = any(
                item.label == "KR_NHIS" and item.start == span.start and item.end == span.end
                for item in spans
            )
            label = labels[value]
            candidates.append({
                "value": value,
                "range": [span.start, span.end],
                "label": label,
                "left_32": text[max(0, span.start - 32):span.start],
                "right_32": text[span.end:min(len(text), span.end + 32)],
                "window": [window_start, window_end],
                "model_input": model_input,
                "raw_score": trace.get("raw_score"),
                "accepted": trace.get("accepted"),
                "final_exact": final_exact,
                "correct": None if label is None else final_exact == label,
            })
        results.append({
            "id": case_id,
            "text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "masked": pii.mask(text, spans),
            "candidates": candidates,
        })
    payload = {
        "variant": "v3-pre-fix-diagnostic",
        "threshold": 0.98,
        "retuned": False,
        "cases": results,
    }
    Path("results/v3-nhis-diagnostic.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
