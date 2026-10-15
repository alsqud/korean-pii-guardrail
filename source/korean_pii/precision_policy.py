#!/usr/bin/env python3
"""Precision and completeness policy for the production hybrid pipeline."""

from __future__ import annotations

import re
import sqlite3

from korean_pii.merge import outside_existing_mask_tokens
from korean_pii.postprocess import (
    _EXPLICIT_GENERAL_LOCATION,
    _PERSONAL_ADDRESS_CUE,
    context_validated_repeated_identifier_spans,
    filter_explicit_nonperson_titles,
    linked_date_of_birth_spans,
    linked_driver_license_spans,
    linked_username_spans,
    linked_vehicle_plate_spans,
)
from korean_pii.types import Span

from .address_boundaries import (
    _ADDRESS_UNIT_TOKEN,
    _field_value_range,
    address_detail_extension_end,
    detailed_location_spans_preserve_model_end,
)
from .bank_account_linking import link_bank_account_spans


_USERNAME_VALUE = r"@?[A-Za-z](?:[A-Za-z0-9._-]{1,30}[A-Za-z0-9_])"
_USERNAME_CUE = (
    r"(?:개인[ \t]*)?(?:포털[ \t]*ID|사용자[ \t]*(?:아이디|ID|명)|"
    r"로그인[ \t]*(?:아이디|ID|명)|계정명|사용자명|username|user[ \t]*id|login[ \t]*id)"
)
_BOUNDED_DELIMITER = r"(?:::?=|=>|[-–—][ \t]*>|▶|→|:|：|=|\||;|/|[-–—])"
_USERNAME_FIELD = re.compile(
    rf"(?im)(?:^|[\n\r|;])[ \t\[\({{〈<]*"
    rf"(?P<cue>{_USERNAME_CUE})[ \t\]\)\}}〉>]*"
    rf"(?:은|는|이|가|을|를|에|로|인)?[ \t]*(?:{_BOUNDED_DELIMITER})?[ \t]*"
    rf"(?:\r?\n[ \t]*(?:값|기재값)?[ \t]*(?:{_BOUNDED_DELIMITER})?[ \t]*)?"
    rf"(?P<value>{_USERNAME_VALUE})"
    rf"(?=(?:에게|으로|로|은|는|이|가|을|를|의)?(?=[ \t\n\r,.;!?]|$))",
    re.IGNORECASE,
)
_USERNAME_NARRATIVE = (
    re.compile(
        rf"(?:사용자|계정)[ \t]+(?P<value>{_USERNAME_VALUE})"
        rf"(?=(?:에게|으로|로|은|는|이|가|을|를|의)?(?=[ \t\n\r,.;!?]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?<![A-Za-z0-9._-])(?P<value>{_USERNAME_VALUE})[ \t]*"
        rf"(?:라는|이라고[ \t]*(?:하는|쓴|사용하는)?)[ \t]*(?:로그인[ \t]*)?"
        rf"(?:아이디|ID|계정|사용자명)",
        re.IGNORECASE,
    ),
)
_NONPERSONAL_USERNAME_LEFT = re.compile(
    r"(?:제품|부품|장치|모델|운송장|물류|포장)[ \t]*(?:코드|번호|참조|계정|아이디|ID)?[ \t]*(?:[:：=|;/▶→—-])?[ \t]*$",
    re.IGNORECASE,
)
_STRICT_PERSON_FIELD = re.compile(
    rf"(?im)(?:^|[\n\r|;])[ \t\[\({{〈<]*"
    rf"(?P<cue>개인[ \t]*(?:신청인|담당자|책임자|소유자|운전자|고객|대표|검토자|접수자|승인자)"
    rf"(?:[ \t]*(?:성명|이름))?)[ \t\]\)\}}〉>]*"
    rf"(?:은|는|이|가|을|를|의)?[ \t]*(?:{_BOUNDED_DELIMITER})[ \t]*"
    rf"(?P<value>[가-힣]{{2,5}})(?=[ \t\n\r,.;!?]|입니다|이다|$)"
)
_ASCII_IDENTIFIER_PREFIX = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]{1,31}-$")
_CARD_SHAPE = re.compile(r"(?<!\d)(?:\d[ -]?){15}\d(?!\d)")
_DOCUMENT_TITLE_SUFFIX = re.compile(
    r"(?:원장|기록|기록지|보고서|확인서|신청서|정산서|작업지|점검표|통지|계약서|인계서|목록)"
)
_NONPERSON_PROCESS_FOLLOWING = re.compile(
    r"^[ \t]*(?:후보|예측|출력|결과|데이터|응답|텍스트|문장|구간|스팬|라벨|값)"
    r"(?:와|과|를|을|가|이|는|은|의|로)?(?=[ \t\n\r,.;!?]|$)"
)
_RAW_FULL_ROAD_PREFIX = re.compile(
    r"^(?P<province>[가-힣]+(?:특별자치도|특별시|광역시|도))[ \t]+"
    r"(?P<district>(?:[가-힣]+시[ \t]+[가-힣]+구|[가-힣]+(?:시|군|구)))[ \t]+"
    r"(?P<dong>[가-힣0-9]+(?:동(?:\d+가)?|가))[ \t]+"
    r"(?P<road>[가-힣0-9·]+(?:대로|로|길))[ \t]+"
    r"\d{1,5}(?:-\d{1,5})?(?:번지|번)?"
)
_SEJONG_ROAD_PREFIX = re.compile(
    r"^세종특별자치시[ \t]+(?P<dong>[가-힣0-9]+동(?:\d+가)?)[ \t]+"
    r"(?P<road>[가-힣0-9·]+(?:대로|로|길))[ \t]+\d{1,5}(?:-\d{1,5})?(?:번지|번)?"
)
_PERSONAL_ADDRESS_FIELD_LEFT = re.compile(
    r"(?:개인[ \t]*)?(?:주소|송달지|거주지|배송지|수령지|도착지|인수지|"
    r"받을[ \t]*곳|회수지|수거지|납품지)[ \t]*(?:[:：=]|->|▶)[ \t]*$"
)


def _has_bounded_personal_address_field(left: str) -> bool:
    return (
        _PERSONAL_ADDRESS_CUE.search(left) is not None
        or _PERSONAL_ADDRESS_FIELD_LEFT.search(left) is not None
    )


def _official_districtless_sejong(gazetteer, dong: str, road: str) -> bool:
    """Validate a Sejong 동/로 pair omitted by the legacy nonempty-district cache."""

    path = getattr(gazetteer, "index_path", None)
    if path is None:
        return False
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            """
            SELECT 1 FROM road_name AS r
            JOIN legal_dong AS l
              ON r.province=l.province AND r.district=l.district
             AND r.admin_dong<>'' AND (r.admin_dong=l.town OR r.admin_dong=l.village)
            WHERE r.abolished='0' AND l.abolished='' AND r.province=?
              AND r.district='' AND r.admin_dong=? AND r.road_name=? LIMIT 1
            """,
            ("세종특별자치시", dong, road),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def _rule_span(label: str, start: int, end: int, reason: str) -> Span:
    return Span(
        label=label, start=start, end=end, source="rule:" + reason,
        score=1.0, native_label=label,
        metadata={"precision_boundary": reason, "deterministic_bounded_relation": True},
    )


def strict_username_rule_spans(text: str) -> list[Span]:
    """Create USERNAME only from bounded explicit field/narrative relations."""

    ranges = set()
    for pattern in (_USERNAME_FIELD,) + _USERNAME_NARRATIVE:
        for match in pattern.finditer(text):
            start, end = match.span("value")
            left = text[max(0, start - 48):start]
            if _NONPERSONAL_USERNAME_LEFT.search(left):
                continue
            ranges.add((start, end))
    return [_rule_span("USERNAME", start, end, "strict-explicit-username-relation") for start, end in sorted(ranges)]


def strict_person_rule_spans(text: str) -> list[Span]:
    """Create PERSON only for a field explicitly marked as a personal role."""

    return [
        _rule_span("PERSON", *match.span("value"), "strict-explicit-person-role-field")
        for match in _STRICT_PERSON_FIELD.finditer(text)
    ]


def filter_document_title_people(text: str, spans: list[Span]) -> list[Span]:
    """Drop a spaced PERSON fragment inside a document/process title."""

    first_line_end = text.find("\n")
    if first_line_end < 0:
        first_line_end = len(text)
    output = []
    for span in spans:
        surface = text[span.start:span.end]
        suffix = text[span.end:first_line_end]
        if (
            span.label == "PERSON" and span.start < first_line_end
            and (" " in surface or "\t" in surface)
            and _DOCUMENT_TITLE_SUFFIX.search(suffix)
        ):
            continue
        output.append(span)
    return output


def filter_process_term_people(text: str, spans: list[Span]) -> list[Span]:
    """Drop a PERSON fragment used as a modifier of a processing noun.

    This is deliberately contextual rather than a surface blacklist: a short
    Hangul span is rejected only when it directly modifies an unambiguously
    non-person processing/result noun.
    """

    output = []
    for span in spans:
        surface = text[span.start:span.end]
        right = text[span.end:min(len(text), span.end + 24)]
        if (
            span.label == "PERSON"
            and len(surface) == 1
            and re.fullmatch(r"[가-힣]", surface) is not None
        ):
            continue
        if (
            span.label == "PERSON"
            and re.fullmatch(r"[가-힣]{2,5}", surface) is not None
            and _NONPERSON_PROCESS_FOLLOWING.search(right) is not None
        ):
            continue
        output.append(span)
    return output


def _ascii_prefixed(text: str, start: int) -> bool:
    return _ASCII_IDENTIFIER_PREFIX.search(text[max(0, start - 40):start]) is not None


def filter_embedded_direct_identifiers(text: str, spans: list[Span]) -> list[Span]:
    """Reject phone/IP substrings embedded in explicit ASCII product identifiers."""

    card_ranges = [match.span() for match in _CARD_SHAPE.finditer(text)]
    output = []
    for span in spans:
        if span.label in {"KR_PHONE_NUMBER", "IP_ADDRESS"} and _ascii_prefixed(text, span.start):
            continue
        if span.label == "KR_PHONE_NUMBER" and any(
            start <= span.start and span.end <= end and (start, end) != (span.start, span.end)
            for start, end in card_ranges
        ):
            continue
        output.append(span)
    return output


def _official_full_raw_location(text: str, span: Span, gazetteer) -> bool:
    if span.label != "KR_LOCATION" or gazetteer is None or not gazetteer.configured:
        return False
    surface = text[span.start:span.end]
    if "\n" in surface or any(char in surface for char in ",;|.!?。！？"):
        return False
    prefix = _RAW_FULL_ROAD_PREFIX.match(surface)
    if prefix is None:
        return False
    detail = surface[prefix.end():].strip()
    tokens = detail.split()
    if not tokens or any(_ADDRESS_UNIT_TOKEN.fullmatch(token) is None for token in tokens):
        return False
    left = text[max(0, span.start - 80):span.start]
    around = text[max(0, span.start - 64):min(len(text), span.end + 64)]
    if not _has_bounded_personal_address_field(left) or _EXPLICIT_GENERAL_LOCATION.search(around):
        return False
    return gazetteer.contains_road_combination(
        prefix.group("province"), prefix.group("district"),
        prefix.group("dong"), prefix.group("road"),
    )


def recover_detailed_location_spans(text: str, spans: list[Span], gazetteer=None) -> list[Span]:
    """Recover an exact model span for an official numeric/punctuated road name."""

    processed = list(detailed_location_spans_preserve_model_end(text, spans, gazetteer))
    recoveries = [span for span in spans if _official_full_raw_location(text, span, gazetteer)]
    if gazetteer is not None and gazetteer.configured:
        for partial in spans:
            if partial.label != "KR_LOCATION":
                continue
            field = _field_value_range(text, partial.start)
            if field is None:
                line_start = text.rfind("\n", 0, partial.start) + 1
                line_end = text.find("\n", partial.end)
                if line_end < 0:
                    line_end = len(text)
                value_start = text.rfind("세종특별자치시", line_start, partial.start + 1)
                left = text[max(line_start, value_start - 48):value_start] if value_start >= 0 else ""
                if value_start < 0 or not _has_bounded_personal_address_field(left):
                    continue
                boundary = re.search(r"[,;|.!?。！？]", text[value_start:line_end])
                limit = line_end if boundary is None else value_start + boundary.start()
            else:
                value_start, limit = field
            match = _SEJONG_ROAD_PREFIX.match(text[value_start:limit])
            if match is None:
                continue
            regex_end = value_start + match.end()
            chosen_end = address_detail_extension_end(text, regex_end, limit)
            if chosen_end < regex_end:
                chosen_end = regex_end
            if not (value_start <= partial.start < chosen_end):
                continue
            if not _official_districtless_sejong(
                gazetteer, match.group("dong"), match.group("road")
            ):
                continue
            recoveries.append(_rule_span(
                "KR_LOCATION", value_start, chosen_end,
                "official-districtless-sejong-address",
            ))
    for raw in recoveries:
        # The existing structured address policy may already have extended a
        # shorter model span through a final unit token (for example "부스").
        # Never replace that longer accepted boundary with the shorter raw span.
        if any(
            span.label == "KR_LOCATION"
            and span.start <= raw.start and raw.end <= span.end
            for span in processed
        ):
            continue
        processed = [
            span for span in processed
            if not (span.label == "KR_LOCATION" and span.start < raw.end and raw.start < span.end)
        ]
        metadata = dict(raw.metadata)
        metadata.update({
            "location_boundary": "exact-model-full-official-road-address",
            "nationwide_dictionary_validated": True,
        })
        processed.append(Span(
            label=raw.label, start=raw.start, end=raw.end, source=raw.source,
            score=raw.score, native_label=raw.native_label, metadata=metadata,
        ))
    return processed


def _append_nonoverlapping_same_label(spans: list[Span], additions: list[Span]) -> list[Span]:
    output = list(spans)
    for addition in additions:
        overlaps = [
            existing for existing in output
            if existing.label == addition.label
            and existing.start < addition.end and addition.start < existing.end
        ]
        if any(
            existing.start <= addition.start and addition.end <= existing.end
            for existing in overlaps
        ):
            continue
        if any(
            not (addition.start <= existing.start and existing.end <= addition.end)
            for existing in overlaps
        ):
            continue
        output = [
            existing for existing in output
            if existing not in overlaps
        ]
        if any(
            existing.label == addition.label
            and existing.start < addition.end and addition.start < existing.end
            for existing in output
        ):
            continue
        output.append(addition)
    return output


def recover_districtless_sejong_after_policy(text: str, spans: list[Span], gazetteer) -> list[Span]:
    """Final exact-boundary recovery for official Sejong addresses without a district."""

    output = list(spans)
    for partial in list(spans):
        if partial.label != "KR_LOCATION":
            continue
        line_start = text.rfind("\n", 0, partial.start) + 1
        line_end = text.find("\n", partial.end)
        if line_end < 0:
            line_end = len(text)
        value_start = text.rfind("세종특별자치시", line_start, partial.start + 1)
        left = text[max(line_start, value_start - 48):value_start] if value_start >= 0 else ""
        if value_start < 0 or not _has_bounded_personal_address_field(left):
            continue
        boundary = re.search(r"[,;|.!?。！？]", text[value_start:line_end])
        limit = line_end if boundary is None else value_start + boundary.start()
        match = _SEJONG_ROAD_PREFIX.match(text[value_start:limit])
        if match is None or not _official_districtless_sejong(
            gazetteer, match.group("dong"), match.group("road")
        ):
            continue
        regex_end = value_start + match.end()
        chosen_end = max(regex_end, address_detail_extension_end(text, regex_end, limit))
        if not (value_start <= partial.start < chosen_end):
            continue
        output = [
            item for item in output
            if not (item.label == "KR_LOCATION" and item.start < chosen_end and value_start < item.end)
        ]
        output.append(_rule_span(
            "KR_LOCATION", value_start, chosen_end,
            "official-districtless-sejong-address-final",
        ))
    return output


def apply_hybrid_precision_policy(engine, text: str, spans: list[Span]) -> list[Span]:
    spans = engine.kiwi.filter_people_context(text, spans)
    spans = outside_existing_mask_tokens(text, spans, engine.policy)
    spans = filter_explicit_nonperson_titles(text, spans)
    spans = filter_document_title_people(text, spans)
    spans = filter_process_term_people(text, spans)
    spans = recover_detailed_location_spans(text, spans, engine.address_gazetteer)
    spans = linked_date_of_birth_spans(text, spans)
    spans = link_bank_account_spans(text, spans)
    spans = linked_username_spans(text, spans)
    spans = linked_driver_license_spans(text, spans)
    spans = linked_vehicle_plate_spans(text, spans)
    spans = _append_nonoverlapping_same_label(spans, strict_username_rule_spans(text))
    spans = _append_nonoverlapping_same_label(spans, strict_person_rule_spans(text))
    spans = filter_embedded_direct_identifiers(text, spans)
    spans = recover_districtless_sejong_after_policy(text, spans, engine.address_gazetteer)
    return context_validated_repeated_identifier_spans(text, spans)
