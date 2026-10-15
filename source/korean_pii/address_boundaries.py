"""Bounded address-detail extension that preserves following prose."""

from __future__ import annotations

import re
from collections.abc import Callable

from korean_pii.postprocess import detailed_location_spans
from korean_pii.types import Span


_HSPACE = r"[ \t]"
_FIELD_START = re.compile(
    rf"(?im)(?:^|[\n\r|;]){_HSPACE}*(?:개인{_HSPACE}*)?(?:상세{_HSPACE}*)?"
    rf"(?:주소|송달지|거주지|배송지|수령지|도착지){_HSPACE}*(?:[:：=]|->|▶){_HSPACE}*"
)
_HARD_BOUNDARY = re.compile(r"[\n\r.!?。！？,，;；|｜]")
_FOLLOWUP_FIELD = re.compile(
    rf"{_HSPACE}+(?:배송|수령|전달|연락|도착|부재|요청|주의|참고|비고)"
    rf"{_HSPACE}*(?:지시|요청|메모|사항|안내)?{_HSPACE}*(?:[:：=]|->|▶)"
)
_ADDRESS_UNIT_TOKEN = re.compile(
    r"(?:"
    r"(?:지하\s*)?\d+(?:층|호|번|번지|동|관|실|열|구역|블록|라인|게이트|부스|좌석|자리)"
    r"|[A-Za-z]\d*(?:열|동|관|구역|블록|라인|게이트|부스)"
    r"|[가-힣A-Za-z0-9]*(?:동|관|실|층|호|열|구역|블록|라인|센터|타워|별관|본관|로비|데스크|출입구|게이트|부스|창구|창고|보관함|작업대|적재대|서가|선반|보관소|좌석|자리)"
    r")"
)


def _field_value_range(text: str, position: int) -> tuple[int, int] | None:
    """Return the explicit field value containing position, capped before prose."""

    chosen = None
    for match in _FIELD_START.finditer(text):
        if match.end() <= position:
            chosen = match
        else:
            break
    if chosen is None:
        return None
    value_start = chosen.end()
    line_end = len(text)
    hard = _HARD_BOUNDARY.search(text, value_start)
    if hard is not None:
        line_end = hard.start()
    followup = _FOLLOWUP_FIELD.search(text, value_start, line_end)
    if followup is not None:
        line_end = followup.start()
    if not (value_start <= position <= line_end):
        return None
    return value_start, line_end


def _token_end(text: str, cursor: int, limit: int) -> int | None:
    while cursor < limit and text[cursor] in " \t":
        cursor += 1
    match = re.match(r"[^ \t\n\r.!?。！？,，;；|｜:：=]+", text[cursor:limit])
    if match is None:
        return None
    return cursor + match.end()


def address_detail_extension_end(text: str, start: int, limit: int) -> int:
    """Extend across consecutive address-unit tokens, never arbitrary prose."""

    cursor = start
    chosen = start
    while cursor < limit:
        token_end = _token_end(text, cursor, limit)
        if token_end is None:
            break
        token_start = cursor
        while token_start < token_end and text[token_start] in " \t":
            token_start += 1
        token = text[token_start:token_end]
        if _ADDRESS_UNIT_TOKEN.fullmatch(token) is None:
            break
        chosen = token_end
        cursor = token_end
    return chosen


def safe_model_suffix(text: str, regex_end: int, model_end: int) -> bool:
    """Compatibility predicate: model suffix must be address-unit evidence."""

    if model_end <= regex_end:
        return False
    limit = model_end
    # A model may stop inside a token (for example the B of B열). Inspect the
    # complete token but preserve only when that complete token is address-like.
    token_end = _token_end(text, regex_end, len(text))
    if token_end is not None and token_end > limit:
        limit = token_end
    return address_detail_extension_end(text, regex_end, limit) >= model_end


def detailed_location_spans_preserve_model_end(
    text: str,
    spans: list[Span],
    gazetteer=None,
    *,
    base_fn: Callable = detailed_location_spans,
) -> list[Span]:
    """Preserve/extend only address-like detail tokens after base acceptance.

    The base policy remains responsible for start selection, official-address
    evidence, and exclusion of administrative-only mentions. This layer cannot
    create a location when the base policy rejected it.
    """

    processed = list(base_fn(text, spans, gazetteer))
    raw_by_range = {
        (span.start, span.end): span for span in spans if span.label == "KR_LOCATION"
    }
    output: list[Span] = []
    for span in processed:
        if span.label != "KR_LOCATION":
            output.append(span)
            continue
        model_range = tuple(span.metadata.get("location_model_span", ()))
        raw = raw_by_range.get(model_range) if len(model_range) == 2 else None
        if raw is None:
            output.append(span)
            continue

        field_range = _field_value_range(text, span.end)
        hard = _HARD_BOUNDARY.search(text, span.end)
        generic_limit = hard.start() if hard is not None else len(text)
        followup = _FOLLOWUP_FIELD.search(text, span.end, generic_limit)
        if followup is not None:
            generic_limit = followup.start()
        limit = field_range[1] if field_range is not None else generic_limit

        chosen_end = address_detail_extension_end(text, span.end, limit)
        if chosen_end == span.end and safe_model_suffix(text, span.end, raw.end):
            token_end = _token_end(text, span.end, limit)
            chosen_end = min(token_end or raw.end, limit)
        chosen_end = max(span.end, chosen_end)

        if chosen_end <= span.end:
            output.append(span)
            continue
        metadata = dict(span.metadata)
        metadata.update({
            "location_regex_end": span.end,
            "location_model_end": raw.end,
            "location_structured_extension_end": chosen_end,
            "location_field_evidence": field_range is not None,
            "location_end_policy": "consecutive-address-unit-tokens-before-prose-boundary",
        })
        output.append(Span(
            label=span.label,
            start=span.start,
            end=chosen_end,
            source=span.source,
            score=span.score,
            native_label=span.native_label,
            metadata=metadata,
        ))
    return output
