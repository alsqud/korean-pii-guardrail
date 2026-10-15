#!/usr/bin/env python3
"""Focused positive and negative tests for bounded address extension."""

from korean_pii.types import Span
from korean_pii.address_boundaries import (
    address_detail_extension_end,
    detailed_location_spans_preserve_model_end,
    safe_model_suffix,
)


def loc(start, end, *, metadata=None):
    return Span(
        label="KR_LOCATION", start=start, end=end, source="model:koredact",
        score=0.99, native_label="ADDRESS", metadata=metadata or {},
    )


def apply(text, base_end, raw_end=None):
    start = text.index("강원특별자치도")
    raw_end = raw_end if raw_end is not None else base_end
    raw = loc(start, raw_end)

    def accepted(_text, _spans, _gazetteer):
        return [loc(start, base_end, metadata={"location_model_span": (start, raw_end)})]

    return detailed_location_spans_preserve_model_end(text, [raw], base_fn=accepted)[0]


text = "배송지: 강원특별자치도 철원군 동송읍 오대로 32 다온창고 B열 7번 선반"
base_end = text.index("B열") - 1
raw_end = text.index("B열") + 1  # raw model stopped after the B
result = apply(text, base_end, raw_end)
assert text[result.start:result.end].endswith("B열 7번 선반")
assert safe_model_suffix(text, base_end, raw_end)

text = "거주지：강원특별자치도 철원군 동송읍 오대로 32 기록관 2층 14번 보관함. 배송 요청: 문 앞에 놓아주세요"
base_end = text.index("14번") - 1
result = apply(text, base_end)
assert text[result.start:result.end].endswith("기록관 2층 14번 보관함")
assert "배송 요청" not in text[result.start:result.end]

text = "수령지 = 강원특별자치도 철원군 동송읍 오대로 32 정비동 A열 8번 작업대 | 연락 안내: 도착 후 전화"
base_end = text.index("A열") - 1
result = apply(text, base_end)
assert text[result.start:result.end].endswith("정비동 A열 8번 작업대")
assert "연락 안내" not in text[result.start:result.end]

text = "주소: 강원특별자치도 철원군 동송읍 오대로 32 음원관 4층 사용료창구 배송 메모: 벨을 누르지 마세요"
base_end = text.index("사용료창구") - 1
result = apply(text, base_end)
assert text[result.start:result.end].endswith("음원관 4층 사용료창구")
assert "배송 메모" not in text[result.start:result.end]

text = "본문 중 강원특별자치도 철원군 동송읍 오대로 32 공방동 1층 108호, 다음 문장은 공개 안내입니다"
base_end = text.index("108호") - 1
result = apply(text, base_end)
assert text[result.start:result.end].endswith("공방동 1층 108호")
assert "다음 문장" not in text[result.start:result.end]

particle = "강원특별자치도 철원군 동송읍 오대로 32에서 회의를 열었다"
base_end = particle.index("에서")
assert address_detail_extension_end(particle, base_end, len(particle)) == base_end
assert not safe_model_suffix(particle, base_end, len(particle))

admin = "서울시 노원구"
raw = loc(0, len(admin))
assert detailed_location_spans_preserve_model_end(
    admin, [raw], base_fn=lambda _t, _s, _g: []
) == []

print("PASS")
