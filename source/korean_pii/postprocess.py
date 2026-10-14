from __future__ import annotations

import re

from .candidates import DRIVER_LICENSE_PATTERN, KOREAN_VALUE_END_PATTERN, VEHICLE_PLATE_PATTERN
from .types import Span


_HSPACE = r"[ \t]*"
_VALUE_END = KOREAN_VALUE_END_PATTERN
_DATE_VALUE = (
    r"(?:"
    r"\d{2,4}년[ \t]*\d{1,2}월[ \t]*\d{1,2}일"
    r"|"
    r"\d{4}[./-]\d{1,2}[./-]\d{1,2}"
    r"|"
    r"\d{1,2}월[ \t]*\d{1,2}일"
    r")"
)
_ACCOUNT_DIGITS = r"(?:\d[ -]?){9,15}\d"
_ACCOUNT_VALUE = rf"(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS}{_VALUE_END}"
_USERNAME_VALUE = r"@?[A-Za-z](?:[A-Za-z0-9._-]{1,30}[A-Za-z0-9_])"


# These patterns establish a direct relationship between the cue and the value.
# Horizontal whitespace is intentional: a cue in another line/field cannot leak
# into the candidate merely because it is nearby in character distance.
_DOB_VALUE_PATTERNS = (
    re.compile(
        rf"(?:생년[ \t]*월일|출생일|생일){_HSPACE}"
        rf"(?:은|는|이|가)?{_HSPACE}(?::|：|=)?{_HSPACE}"
        rf"(?P<value>{_DATE_VALUE})"
    ),
    re.compile(
        rf"(?P<value>{_DATE_VALUE}){_HSPACE}(?:에{_HSPACE})?"
        rf"(?:태어났(?:습니다|다)?|출생(?:했습니다|함|이다)?)"
    ),
    re.compile(
        r"(?P<value>(?<!\d)\d{2,4}년)생"
        r"(?=[ \t\n.,!?]|입니다|이에요|예요|임|$)"
    ),
)

_ACCOUNT_VALUE_PATTERNS = (
    re.compile(
        rf"(?:계좌[ \t]*번호|입금[ \t]*계좌|송금[ \t]*계좌|출금[ \t]*계좌|"
        rf"환불[ \t]*계좌|계좌){_HSPACE}(?:은|는|이|가)?{_HSPACE}"
        rf"(?::|：|=)?{_HSPACE}(?:[가-힣A-Za-z]{{1,12}}은행{_HSPACE})?"
        rf"(?P<value>{_ACCOUNT_VALUE})"
    ),
    re.compile(
        rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS}){_HSPACE}(?:번{_HSPACE})?"
        rf"계좌(?:[ \t]*번호)?(?:로|에|입니다|임)?"
    ),
    re.compile(
        rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS}){_HSPACE}"
        rf"[가-힣A-Za-z]{{1,12}}은행(?:{_HSPACE}계좌)?{_HSPACE}"
        rf"(?:(?:으로|로|입니다|이에요|예요|임)(?=[ \t\n.,!?]|$)|(?=[.,!?]|$))"
    ),
)

_USERNAME_VALUE_PATTERNS = (
    re.compile(
        rf"(?:로그인[ \t]*(?:아이디|ID|명)|사용자[ \t]*(?:아이디|ID|명)|"
        rf"계정[ \t]*(?:아이디|ID|명)|아이디|username|user[ \t]*id|login[ \t]*id)"
        rf"{_HSPACE}(?:은|는|이|가)?{_HSPACE}(?::|：|=)?{_HSPACE}"
        rf"(?P<value>{_USERNAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:사용자|계정)[ \t]+(?P<value>{_USERNAME_VALUE})"
        rf"(?=(?:으로|에게|은|는|이|가|을|를|의|로)?(?=[ \t\n.,!?]|$))"
    ),
    re.compile(rf"(?<![A-Za-z0-9._-])(?P<value>@[A-Za-z][A-Za-z0-9._-]{{2,31}})"),
)

_ADDRESS_UNIT_SUFFIX = r"(?:[ \t]*(?:\d{1,4}동|\d{1,4}층|\d{1,4}호))*"
_NO_UNCONSUMED_ADDRESS_UNIT = r"(?![ \t]*\d{1,4}(?:동|층|호))"
_DETAILED_LOCATION_PATTERNS = (
    re.compile(
        rf"(?<![가-힣A-Za-z0-9])"
        rf"(?P<anchor>[가-힣][가-힣0-9]{{0,19}}(?:읍|면|동|리))"
        rf"[ \t]*(?:산[ \t]*)?\d{{1,5}}(?:-\d{{1,5}})?"
        rf"[ \t]*(?:번지)?{_ADDRESS_UNIT_SUFFIX}{_NO_UNCONSUMED_ADDRESS_UNIT}{_VALUE_END}"
    ),
    re.compile(
        rf"(?<![가-힣A-Za-z0-9])"
        rf"(?P<anchor>(?:[가-힣][가-힣0-9]{{1,19}}로[ \t]*\d{{1,4}}(?:번)?길|"
        rf"[가-힣][가-힣0-9]{{1,19}}로\d+번길|"
        rf"[가-힣][가-힣0-9]{{1,29}}(?:대로|로|길)))"
        rf"[ \t]*\d{{1,5}}(?:-\d{{1,5}})?{_ADDRESS_UNIT_SUFFIX}{_NO_UNCONSUMED_ADDRESS_UNIT}"
        rf"{_VALUE_END}"
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?P<anchor>\d{1,4}동[ \t]*"
        rf"(?:\d{{1,4}}층[ \t]*)?\d{{1,4}}호){_VALUE_END}"
    ),
    re.compile(
        rf"(?<![A-Za-z0-9])(?P<anchor>\d{{1,4}}층[ \t]*\d{{1,4}}호)"
        rf"{_VALUE_END}"
    ),
)


def _overlaps(start: int, end: int, span: Span) -> bool:
    return start < span.end and span.start < end


def _linked_value_ranges(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[tuple[int, int]]:
    ranges = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            ranges.add(match.span("value"))
    return sorted(ranges)


def _replace_boundary(span: Span, start: int, end: int, reason: str) -> Span:
    metadata = dict(span.metadata)
    metadata.update({
        "model_span": (span.start, span.end),
        "precision_boundary": reason,
    })
    return Span(
        label=span.label,
        start=start,
        end=end,
        source=span.source,
        score=span.score,
        native_label=span.native_label,
        metadata=metadata,
    )


def detailed_location_spans(text: str, spans: list[Span]) -> list[Span]:
    """Keep exact detailed-address shapes supported by a model span.

    This is deliberately not a nationwide legal-dong/road-name validator. It
    distinguishes a broad place from a location containing a lot/building/unit
    number, and never borrows a number from another model span or field.
    """

    detail_matches = []
    for pattern in _DETAILED_LOCATION_PATTERNS:
        for match in pattern.finditer(text):
            detail_matches.append((match.start(), match.end(), match.span("anchor")))

    output = [span for span in spans if span.label != "KR_LOCATION"]
    for span in spans:
        if span.label != "KR_LOCATION":
            continue
        for start, end, (anchor_start, anchor_end) in detail_matches:
            # The model must cover the address/unit anchor itself.  Merely
            # finding a number elsewhere in the same sentence is insufficient.
            if not _overlaps(anchor_start, anchor_end, span):
                continue
            metadata = dict(span.metadata)
            metadata.update({
                "location_model_span": (span.start, span.end),
                "location_boundary": "exact-detailed-address-shape",
                "location_detail_evidence": (start, end),
                "nationwide_dictionary_validated": False,
            })
            output.append(Span(
                label=span.label,
                start=start,
                end=end,
                source=span.source,
                score=span.score,
                native_label=span.native_label,
                metadata=metadata,
            ))
    return output


def linked_date_of_birth_spans(text: str, spans: list[Span]) -> list[Span]:
    """Keep/expand Frame DOB spans only when tied to a DOB field or phrase."""

    values = _linked_value_ranges(text, _DOB_VALUE_PATTERNS)
    output = []
    for span in spans:
        if span.label != "DATE_OF_BIRTH":
            output.append(span)
            continue
        matches = [(start, end) for start, end in values if _overlaps(start, end, span)]
        if not matches:
            continue
        start, end = max(
            matches,
            key=lambda item: min(item[1], span.end) - max(item[0], span.start),
        )
        output.append(_replace_boundary(span, start, end, "dob-value-linked-to-field"))
    return output


def linked_account_spans(text: str, spans: list[Span]) -> list[Span]:
    """Keep/expand model account spans only when tied to an account field.

    The shape check is a boundary normalizer, not bank-specific validation.
    """

    values = _linked_value_ranges(text, _ACCOUNT_VALUE_PATTERNS)
    output = []
    for span in spans:
        if span.label != "KR_BANK_ACCOUNT":
            output.append(span)
            continue
        matches = [(start, end) for start, end in values if _overlaps(start, end, span)]
        if not matches:
            continue
        start, end = max(
            matches,
            key=lambda item: min(item[1], span.end) - max(item[0], span.start),
        )
        output.append(_replace_boundary(span, start, end, "account-value-linked-to-field"))
    return output


def linked_username_spans(text: str, spans: list[Span]) -> list[Span]:
    """Keep model USERNAME spans only when tied to a username field/handle.

    The Frame model can emit several partial USERNAME spans inside an uppercase
    equipment or product identifier.  Direct field linkage both suppresses
    those fragments and expands a true partial prediction to the complete
    username token.  No global model-score threshold is changed.
    """

    values = _linked_value_ranges(text, _USERNAME_VALUE_PATTERNS)
    output = []
    for span in spans:
        if span.label != "USERNAME":
            output.append(span)
            continue
        matches = [(start, end) for start, end in values if _overlaps(start, end, span)]
        if not matches:
            continue
        start, end = max(
            matches,
            key=lambda item: min(item[1], span.end) - max(item[0], span.start),
        )
        output.append(_replace_boundary(span, start, end, "username-value-linked-to-field"))
    return output


def _shape_linked_spans(
    text: str,
    spans: list[Span],
    *,
    label: str,
    pattern: re.Pattern[str],
    reason: str,
) -> list[Span]:
    """Keep a specialist label only when it overlaps its complete value shape.

    Candidate windows deliberately include surrounding context.  This final
    association step prevents a model label elsewhere in that context from
    being retained, and normalizes partial model boundaries to the exact
    syntactic value.
    """

    values = [match.span() for match in pattern.finditer(text)]
    output = []
    for span in spans:
        if span.label != label:
            output.append(span)
            continue
        matches = [(start, end) for start, end in values if _overlaps(start, end, span)]
        if not matches:
            continue
        start, end = max(
            matches,
            key=lambda item: min(item[1], span.end) - max(item[0], span.start),
        )
        output.append(_replace_boundary(span, start, end, reason))
    return output


def linked_driver_license_spans(text: str, spans: list[Span]) -> list[Span]:
    return _shape_linked_spans(
        text,
        spans,
        label="KR_DRIVER_LICENSE",
        pattern=DRIVER_LICENSE_PATTERN,
        reason="driver-license-complete-shape",
    )


def linked_vehicle_plate_spans(text: str, spans: list[Span]) -> list[Span]:
    return _shape_linked_spans(
        text,
        spans,
        label="KR_VEHICLE_PLATE",
        pattern=VEHICLE_PLATE_PATTERN,
        reason="vehicle-plate-complete-shape",
    )


def apply_precision_policy(text: str, spans: list[Span]) -> list[Span]:
    spans = detailed_location_spans(text, spans)
    spans = linked_date_of_birth_spans(text, spans)
    spans = linked_account_spans(text, spans)
    spans = linked_username_spans(text, spans)
    spans = linked_driver_license_spans(text, spans)
    return linked_vehicle_plate_spans(text, spans)
