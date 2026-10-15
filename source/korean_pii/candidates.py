from __future__ import annotations

import re
from collections import defaultdict

from .config import Policy
from .types import RoutedWindow, Span


DRIVER_LICENSE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])\d{2}[- ]\d{2}[- ]\d{6}[- ]\d{2}(?![A-Za-z0-9-])"
)
VEHICLE_PLATE_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9-])"
    r"(?:(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|"
    r"전북|전남|경북|경남|제주)\s*)?"
    r"\d{2,3}[가-힣]\s*\d{4}(?![A-Za-z0-9-])"
)
KOREAN_POSTPOSITION_PATTERN = (
    r"(?:으로|에서|에게|까지|부터|은|는|이|가|을|를|의|와|과|로|에|도|만)"
)
KOREAN_COPULAR_ENDING_PATTERN = (
    r"(?:입니다|이에요|예요|임|"
    r"이(?:다|며|고|면|므로|라서|라고|라는|란|라면|었(?:다|습니다)?|겠(?:다|습니다)?))"
)
KOREAN_VALUE_END_PATTERN = (
    rf"(?=(?:(?:{KOREAN_POSTPOSITION_PATTERN}|{KOREAN_COPULAR_ENDING_PATTERN})"
    r"(?=[ \t\n.,!?]|$)|[^가-힣A-Za-z0-9-]|$))"
)


PATTERNS = {
    "regex:kr_driver_license": DRIVER_LICENSE_PATTERN,
    "keyword:driver_context": re.compile(r"운전면허|면허증|면허번호"),
    "regex:kr_vehicle_plate": VEHICLE_PLATE_PATTERN,
    "keyword:vehicle_context": re.compile(r"차량|차번호|번호판"),
    "regex:role_prefix_name": re.compile(r"(?:엔지니어|강사|요원|운전자|담당자|고객|신청인|소유자|원고|피고)\s*[가-힣]{2,6}"),
    "regex:honorific_name": re.compile(r"(?<![가-힣])[가-힣]{2,5}(?=\s*(?:은|는|이|가|을|를|의|님|씨|께|입니다|이며|에게))"),
    "regex:responsibility_name": re.compile(
        r"(?:(?<=책임자는 )|(?<=책임자는)|(?<=책임자 ))"
        r"[가-힣]{2,5}(?=\s*(?:이며|이고|이다|입니다|이었|으로))"
    ),
    "regex:mail_sender_name": re.compile(r"보낸\s*사람:\s*[가-힣]{2,5}"),
    "regex:speaker_name": re.compile(r"(?m)^[가-힣]{2,5}(?=:)") ,
    "regex:numbered_name": re.compile(r"(?m)^\s*\d+\.\s*[가-힣]{2,5}(?=\s*\()"),
    "keyword:name_context": re.compile(r"이름|성명"),
    "regex:kr_place_suffix": re.compile(r"(?<![가-힣A-Za-z0-9])[가-힣0-9]{2,30}(?:로\d+번길|로|길|동|리|면|읍|군|구|시|도)(?![가-힣A-Za-z0-9])"),
    "regex:kr_detailed_address_shape": re.compile(
        r"(?<![가-힣A-Za-z0-9])(?:"
        r"[가-힣][가-힣0-9]{0,19}(?:읍|면|동|리)[ \t]*(?:산[ \t]*)?"
        r"\d{1,5}(?:-\d{1,5})?(?:[ \t]*(?:번지|\d{1,4}동|\d{1,4}층|\d{1,4}호))*"
        r"|(?:[가-힣][가-힣0-9]{1,19}로[ \t]*\d{1,4}(?:번)?길|"
        r"[가-힣][가-힣0-9]{1,19}로\d+번길|"
        r"[가-힣][가-힣0-9]{1,29}(?:대로|로|길))[ \t]*"
        r"\d{1,5}(?:-\d{1,5})?(?:[ \t]*(?:\d{1,4}동|\d{1,4}층|\d{1,4}호))*"
        r"|\d{1,4}동[ \t]*(?:\d{1,4}층[ \t]*)?\d{1,4}호"
        r"|\d{1,4}층[ \t]*\d{1,4}호"
        rf"){KOREAN_VALUE_END_PATTERN}"
    ),
    "keyword:address_context": re.compile(r"주소|장소|소재지|부근|인근|지역"),
    "regex:account_shape": re.compile(r"(?<!\d)(?:\d[- ]?){9,15}\d(?!\d)"),
    "keyword:account_context": re.compile(r"계좌|은행|입금|송금|예금주"),
    "regex:passport_shape": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,2}\d{7,8}(?![A-Za-z0-9])"),
    "keyword:passport_context": re.compile(r"여권"),
}


def build_windows(text: str, frontend: list[Span], policy: Policy) -> dict[str, list[RoutedWindow]]:
    pending = defaultdict(list)
    for label, route in policy.types.items():
        if not route.enabled or route.expert_model is None:
            continue
        padding = route.context_chars
        for detector in route.candidate_detectors:
            if detector.startswith("frontend:"):
                source_label = detector.split(":", 1)[1]
                for span in frontend:
                    if span.label == source_label:
                        threshold = route.candidate_threshold
                        if threshold.enabled and (span.score is None or span.score < threshold.value):
                            continue
                        pending[route.expert_model].append((
                            max(0, span.start - padding), min(len(text), span.end + padding),
                            f"label:{label}:frontend:{source_label}", label,
                            span.start, span.end,
                        ))
                continue
            if detector not in PATTERNS:
                raise ValueError(f"unknown candidate detector: {detector}")
            for match in PATTERNS[detector].finditer(text):
                pending[route.expert_model].append((
                    max(0, match.start() - padding), min(len(text), match.end() + padding),
                    f"label:{label}:{detector}", label,
                    match.start(), match.end(),
                ))
    output = {}
    for model, items in pending.items():
        # Preserve one context slice per candidate.  The former interval-union
        # loop merged transitive overlaps without a length bound, so a chain of
        # +/-24-character candidates could turn into the entire document.
        # Exact duplicate windows for the same target label are still collapsed
        # to avoid identical inference calls while retaining all evidence.
        distinct: dict[tuple[int, int, str, int, int], set[str]] = {}
        for start, end, evidence, label, focus_start, focus_end in sorted(items):
            distinct.setdefault(
                (start, end, label, focus_start, focus_end), set()
            ).add(evidence)
        output[model] = [
            RoutedWindow(
                model=model,
                start=start,
                end=end,
                focus_start=focus_start,
                focus_end=focus_end,
                evidence=tuple(sorted(evidence)),
                allowed_labels=(label,),
            )
            for (start, end, label, focus_start, focus_end), evidence in sorted(distinct.items())
        ]
    return output


def precise_driver_spans(text: str) -> list[Span]:
    return [
        Span(label="KR_DRIVER_LICENSE", start=match.start(), end=match.end(),
             source="rule:kr_driver_license", score=1.0, native_label="KR_DRIVER_LICENSE")
        for match in PATTERNS["regex:kr_driver_license"].finditer(text)
    ]
