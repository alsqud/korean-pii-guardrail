from __future__ import annotations

import hashlib


EXACT_669_SHA256 = "8f9c54cb9532d93d90b59c122ff7cdc682d7ca93b24a54aa726ccea531534143"
EXACT_669_TEXT = (
    "김민수님과 이영희님이 신청했습니다. 김은 반찬으로 먹고 민수용 장비는 따로 보관합니다. "
    "거주지는 서울특별시 중랑구 면목동 123-4 101동 202호이며, 서울특별시 중랑구의 날씨도 확인했습니다. "
    "연락처는 010-0000-0000이고 제품번호는 AB-010-XYZ입니다. 입금 계좌는 신한은행 110-000-000000이며, "
    "제품 규격은 110-229-300입니다. 이메일은 minsu@example.com이고 수학에서는 a@b라는 기호를 사용했습니다. "
    "접속 IP는 192.0.2.10이며 프로그램 버전은 1.2.3입니다. 결제 카드번호는 4242-4242-4242-4242이고 "
    "상품코드는 ITEM-4242입니다. 주민등록번호는 900101-1234568이고 주문번호는 ORD-900101-1234568입니다. "
    "생년월일은 1990년 1월 1일이며 회의일은 2026년 10월 14일입니다. 로그인 아이디는 minsu2026이고 "
    "제품 모델명은 MODEL2026입니다. 여권번호는 M12345678이고 부품번호는 PART-M12345678입니다. "
    "운전면허번호는 11-20-123456-78이고 배송관리번호는 SHIP-11-20-123456-78입니다. "
    "차량번호는 123가4567이고 창고 구역은 123가입니다. 건강보험증 번호는 12345678901이고 "
    "택배 운송장 번호는 98765432109입니다."
)


def _independent_669_text() -> str:
    sections = [
        "독립 장문 점검입니다. 배송 식별자는 BOX-31-42-654321-09이며 창고 구역은 418다입니다. ",
        "일반 운영 기록을 확인하고 비민감 항목을 정리했습니다. " * 5,
        "입금 계좌는 새봄은행 330-481-726590이고 담당자는 고하린이며 연구용 장비를 확인했습니다. ",
        "검토 메모와 처리 순서를 다시 확인했습니다. " * 5,
        "접속 IP는 198.51.100.27이고 거주지는 가람동 731-8 104동 905호이며 "
        "차량번호는 418다7625이고 운전면허번호는 31-42-654321-09입니다. ",
    ]
    text = "".join(sections)
    filler = " 독립 회귀용 일반 문장입니다."
    while len(text) < 669:
        text += filler
    return text[:669]


INDEPENDENT_669_TEXT = _independent_669_text()


def _identity(text: str) -> dict:
    return {
        "chars": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


assert _identity(EXACT_669_TEXT) == {
    "chars": 669,
    "utf8_bytes": 1245,
    "sha256": EXACT_669_SHA256,
}
assert len(INDEPENDENT_669_TEXT) == 669


CASES = (
    {
        "id": "exact-original-669",
        "text": EXACT_669_TEXT,
        "identity": _identity(EXACT_669_TEXT),
        "expectations": (
            {"id": "person-one", "label": "PERSON", "surface": "김민수", "present": True, "sources": ("model:frame", "model:seongyeon")},
            {"id": "person-two", "label": "PERSON", "surface": "이영희", "present": True, "sources": ("model:frame", "model:seongyeon")},
            {"id": "derived-noun-not-person", "label": "PERSON", "surface": "민수", "anchor": "반찬으로 먹고 ", "present": False},
            {"id": "complete-address", "label": "KR_LOCATION", "surface": "면목동 123-4 101동 202호", "present": True, "sources": ("model:koredact",)},
            {"id": "weather-region-preserved", "label": "KR_LOCATION", "surface": "서울특별시 중랑구", "anchor": "202호이며, ", "present": False},
            {"id": "complete-account", "label": "KR_BANK_ACCOUNT", "surface": "110-000-000000", "present": True, "sources": ("model:atonlee",)},
            {"id": "test-net-ip", "label": "IP_ADDRESS", "surface": "192.0.2.10", "present": True, "sources": ("rule:ko-pii", "rule:ipv4-strict")},
            {"id": "real-driver", "label": "KR_DRIVER_LICENSE", "surface": "11-20-123456-78", "anchor": "운전면허번호는 ", "present": True, "sources": ("rule:kr_driver_license", "model:seongyeon")},
            {"id": "shipping-not-driver", "label": "KR_DRIVER_LICENSE", "surface": "11-20-123456-78", "anchor": "배송관리번호는 SHIP-", "present": False},
            {"id": "real-vehicle", "label": "KR_VEHICLE_PLATE", "surface": "123가4567", "present": True, "sources": ("model:seongyeon",)},
            {"id": "warehouse-not-vehicle", "label": "KR_VEHICLE_PLATE", "surface": "123가", "anchor": "창고 구역은 ", "present": False},
        ),
        "preserve": (
            {"id": "derived-phrase", "surface": "민수용 장비"},
            {"id": "shipping-id", "surface": "SHIP-11-20-123456-78"},
            {"id": "warehouse-region", "surface": "창고 구역은 123가"},
            {"id": "software-version", "surface": "프로그램 버전은 1.2.3"},
            {"id": "weather-region", "surface": "서울특별시 중랑구의 날씨"},
            {"id": "product-shape", "surface": "제품 규격은 110-229-300"},
        ),
    },
    {
        "id": "independent-variant-669",
        "text": INDEPENDENT_669_TEXT,
        "identity": _identity(INDEPENDENT_669_TEXT),
        "expectations": (
            {"id": "derived-noun-not-person", "label": "PERSON", "surface": "연구", "anchor": "고하린이며 ", "present": False},
            {"id": "synthetic-person", "label": "PERSON", "surface": "고하린", "present": True, "sources": ("model:frame", "model:seongyeon")},
            {"id": "complete-account", "label": "KR_BANK_ACCOUNT", "surface": "330-481-726590", "present": True, "sources": ("model:atonlee",)},
            {"id": "complete-address", "label": "KR_LOCATION", "surface": "가람동 731-8 104동 905호", "present": True, "sources": ("model:koredact",)},
            {"id": "test-net-ip", "label": "IP_ADDRESS", "surface": "198.51.100.27", "present": True, "sources": ("rule:ko-pii", "rule:ipv4-strict")},
            {"id": "real-driver", "label": "KR_DRIVER_LICENSE", "surface": "31-42-654321-09", "anchor": "운전면허번호는 ", "present": True, "sources": ("rule:kr_driver_license", "model:seongyeon")},
            {"id": "shipping-not-driver", "label": "KR_DRIVER_LICENSE", "surface": "31-42-654321-09", "anchor": "BOX-", "present": False},
            {"id": "real-vehicle", "label": "KR_VEHICLE_PLATE", "surface": "418다7625", "present": True, "sources": ("model:seongyeon",)},
            {"id": "warehouse-not-vehicle", "label": "KR_VEHICLE_PLATE", "surface": "418다", "anchor": "창고 구역은 ", "present": False},
        ),
        "preserve": (
            {"id": "derived-phrase", "surface": "연구용 장비"},
            {"id": "shipping-id", "surface": "BOX-31-42-654321-09"},
            {"id": "warehouse-region", "surface": "창고 구역은 418다"},
        ),
    },
)
