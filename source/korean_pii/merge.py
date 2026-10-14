from __future__ import annotations

from .config import Policy
from .errors import DetectionError
from .types import Span


SOURCE_PRIORITY = {
    "rule:kr_driver_license": 6,
    "rule:presidio": 6,
    "rule:ko-pii": 5,
    "rule:ipv4-strict": 5,
    "rule:nhis-shape": 5,
    "model:frame": 3,
    "model:koredact": 4,
    "model:atonlee": 4,
    "model:seongyeon": 4,
}


def outside_existing_mask_tokens(text: str, spans: list[Span], policy: Policy) -> list[Span]:
    """Drop detections inside tokens produced by this policy's masker."""

    ranges = []
    for label, route in policy.types.items():
        if not route.enabled:
            continue
        token = policy.mask["token_format"].format(label=label)
        cursor = 0
        while True:
            start = text.find(token, cursor)
            if start < 0:
                break
            end = start + len(token)
            ranges.append((start, end))
            cursor = end
    if not ranges:
        return spans
    return [
        span for span in spans
        if not any(start < span.end and span.start < end for start, end in ranges)
    ]


def deduplicate(spans: list[Span], policy: Policy) -> list[Span]:
    exact: dict[tuple[str, int, int], Span] = {}
    for span in spans:
        route = policy.types.get(span.label)
        if route is None or not route.enabled:
            continue
        key = span.label, span.start, span.end
        current = exact.get(key)
        if current is None or (SOURCE_PRIORITY.get(span.source, 0), span.score or 0.0) > (SOURCE_PRIORITY.get(current.source, 0), current.score or 0.0):
            exact[key] = span
    return sorted(exact.values(), key=lambda item: (item.start, item.end, item.label, item.source))


def non_overlapping_for_mask(spans: list[Span], policy: Policy) -> list[Span]:
    priority = {label: len(policy.mask["overlap_priority"]) - index for index, label in enumerate(policy.mask["overlap_priority"])}
    selected = []
    for span in sorted(spans, key=lambda item: (-priority.get(item.label, 0), -(item.end - item.start), item.start, item.label)):
        if any(span.start < prior.end and prior.start < span.end for prior in selected):
            continue
        selected.append(span)
    return sorted(selected, key=lambda item: (item.start, item.end))


def mask_text(text: str, spans: list[Span], policy: Policy) -> str:
    for span in spans:
        if span.end > len(text):
            raise DetectionError("mask input contains an out-of-bounds span")
        if span.label not in policy.types or not policy.types[span.label].enabled:
            raise DetectionError("mask input contains a disabled or unknown label")
    output = text
    for span in reversed(non_overlapping_for_mask(spans, policy)):
        token = policy.mask["token_format"].format(label=span.label)
        output = output[:span.start] + token + output[span.end:]
    return output
