#!/usr/bin/env python3
"""Fast rule-level regressions for the hybrid precision policy."""

from __future__ import annotations

from korean_pii.types import Span

from korean_pii.precision_policy import (
    _has_bounded_personal_address_field,
    filter_document_title_people,
    filter_embedded_direct_identifiers,
    filter_process_term_people,
    strict_person_rule_spans,
    strict_username_rule_spans,
)

for address_left in (
    "개인 인수지: ", "복원물 납품지: ", "수리품 받을 곳 = ",
    "장비 회수지 ▶ ", "기기 수거지 -> ", "개인 배송지：",
):
    assert _has_bounded_personal_address_field(address_left), address_left


def span(text: str, surface: str, label: str, source: str) -> Span:
    start = text.index(surface)
    return Span(label, start, start + len(surface), source, 1.0, label, {})


for text, value in (
    ("개인 포털ID: final_member_01", "final_member_01"),
    ("[사용자 아이디] ▶ @sealed.member-03", "@sealed.member-03"),
    ("로그인 ID ::= member.alpha_04", "member.alpha_04"),
    ("계정명 / holdout.user_07", "holdout.user_07"),
    ("사용자 ID\norbit.member_12", "orbit.member_12"),
    ("사용자 @orbit.member_07에게 연결했다", "@orbit.member_07"),
    ("orbit.member_02라는 로그인 아이디를 쓴다", "orbit.member_02"),
):
    found = strict_username_rule_spans(text)
    assert [(item.start, item.end) for item in found] == [(text.index(value), text.index(value) + len(value))], (text, found)

assert not strict_username_rule_spans("제품 아이디: orbit.member_01")
person_text = "개인 담당자 ▶ 백소은입니다."
people = strict_person_rule_spans(person_text)
assert [person_text[item.start:item.end] for item in people] == ["백소은"]

phone_text = "통신모듈 TELX-010-4401-8101과 개인 연락처 010-3301-7201"
phone_false = span(phone_text, "010-4401-8101", "KR_PHONE_NUMBER", "rule:ko-pii")
phone_true = span(phone_text, "010-3301-7201", "KR_PHONE_NUMBER", "rule:ko-pii")
assert filter_embedded_direct_identifiers(phone_text, [phone_false, phone_true]) == [phone_true]

ip_text = "소프트웨어 VER-198.18.1.21, 접속 IP 198.51.100.71"
ip_false = span(ip_text, "198.18.1.21", "IP_ADDRESS", "rule:ipv4-strict")
ip_true = span(ip_text, "198.51.100.71", "IP_ADDRESS", "rule:ipv4-strict")
assert filter_embedded_direct_identifiers(ip_text, [ip_false, ip_true]) == [ip_true]

card_text = "invalid 카드 7884 8545 1514 6900"
phone_inside_card = span(card_text, "1514 6900", "KR_PHONE_NUMBER", "rule:ko-pii")
assert not filter_embedded_direct_identifiers(card_text, [phone_inside_card])

compact_card_text = "invalid 카드 56370120 15538271"
compact_phone = span(compact_card_text, "15538271", "KR_PHONE_NUMBER", "rule:ko-pii")
assert not filter_embedded_direct_identifiers(compact_card_text, [compact_phone])

title_text = "어획 정산 원장\n개인 조합원: 심건우"
title = span(title_text, "어획 정산", "PERSON", "model:seongyeon")
person = span(title_text, "심건우", "PERSON", "model:frame")
assert filter_document_title_people(title_text, [title, person]) == [person]

process_text = "원시 후보와 예측 결과를 비교하고 개인 담당자 김민수를 확인한다"
process_false = span(process_text, "원시", "PERSON", "model:frame")
process_true = span(process_text, "김민수", "PERSON", "model:frame")
assert filter_process_term_people(process_text, [process_false, process_true]) == [process_true]
one_char_text = "제품 식별자 안의 숫자는 보존하고 개인 담당자 김민수를 확인한다"
one_char_false = span(one_char_text, "안", "PERSON", "model:frame")
one_char_true = span(one_char_text, "김민수", "PERSON", "model:frame")
assert filter_process_term_people(one_char_text, [one_char_false, one_char_true]) == [one_char_true]

print({"status": "PASS", "policy": "hybrid precision"})
