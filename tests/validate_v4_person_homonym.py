from __future__ import annotations

import json
from pathlib import Path

from korean_pii import KoreanPII
from korean_pii.types import Span


CASES = (
    ("food-copula", "김은 도시락 반찬이고 다른 재료도 있습니다.", False),
    ("food-consumed", "김은 반찬으로 먹고 밥을 준비했습니다.", False),
    ("food-used", "김을 김밥 재료로 사용했습니다.", False),
    ("person-predicate", "김은 담당자이고 신청서를 검토합니다.", True),
    ("person-left-cue", "담당자 김은 도시락 반찬을 준비했습니다.", True),
    ("person-honorific", "김 씨가 신청했습니다.", True),
    ("person-customer-honorific", "고객 김님의 서류입니다.", True),
)


def main() -> None:
    pii = KoreanPII()
    results = []
    for case_id, text, expected in CASES:
        start = text.index("김")
        proposed = Span(
            label="PERSON",
            start=start,
            end=start + 1,
            source="model:frame",
            score=0.99,
            native_label="private_person",
            metadata={},
        )
        kept = bool(pii.kiwi.filter_people_context(text, [proposed]))
        results.append(
            {
                "id": case_id,
                "text": text,
                "expected_person": expected,
                "kept_as_person": kept,
                "passed": kept == expected,
            }
        )
    payload = {
        "case_count": len(results),
        "all_passed": all(item["passed"] for item in results),
        "failed": [item for item in results if not item["passed"]],
        "cases": results,
    }
    Path("results/v4-person-homonym.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
