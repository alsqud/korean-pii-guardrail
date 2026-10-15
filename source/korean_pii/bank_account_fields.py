#!/usr/bin/env python3
"""Bounded bank-account field extraction and catalog-assisted linkage."""

from __future__ import annotations

import re

from korean_pii.postprocess import linked_account_spans as legacy_linked_account_spans
from korean_pii.types import Span

from .bank_account_catalog import account_tokens, evidence_for_range


_ACCOUNT_DIGITS = r"(?:\d[ \t-]?){9,15}\d"
_VALUE_END = r"(?=$|[^가-힣A-Za-z0-9_-])"
_CUE = (
    r"(?:계좌[ \t]*번호|입금[ \t]*계좌|송금[ \t]*계좌|출금[ \t]*계좌|"
    r"환불[ \t]*계좌|이체[ \t]*계좌|지급[ \t]*계좌|통장[ \t]*번호|계좌|통장)"
)
_OPEN = r"(?:[\[\(\{〈<][ \t]*)?"
_CLOSE = r"(?:[ \t]*[\]\)\}〉>])?"
_PARTICLE = r"(?:에게는|에서는|으로는|에는|은|는|이|가|을|를|에|로|인)?"
_DELIMITER = r"(?:=>|[-–—][ \t]*>|[=:：|;/▶→–—-]{1,3})"
_ONE_LINE_BREAK = r"(?:\r?\n[ \t]*(?:값|기재값)?[ \t]*(?:[:：=|;]|::=|=>|▶|→)?[ \t]*)?"
_FIELD_GAP = rf"[ \t]*{_PARTICLE}[ \t]*(?:{_DELIMITER})?[ \t]*{_ONE_LINE_BREAK}"
_EXPANDED_FIELD = re.compile(
    rf"{_OPEN}(?P<cue>{_CUE}){_CLOSE}{_FIELD_GAP}"
    rf"(?:[가-힣A-Za-z]{{1,20}}(?:은행|뱅크|금고|신협|증권)[ \t]*)?"
    rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS}{_VALUE_END})",
    re.IGNORECASE,
)


def _overlaps(a: int, b: int, c: int, d: int) -> bool:
    return a < d and c < b


def expanded_account_field_ranges(text: str) -> list[tuple[int, int]]:
    """Return account values attached to explicit, bounded field cues."""

    return sorted({match.span("value") for match in _EXPANDED_FIELD.finditer(text)})


def _replace(span: Span, start: int, end: int, reason: str, extra: dict | None = None) -> Span:
    metadata = dict(span.metadata)
    metadata.update({"model_span": (span.start, span.end), "precision_boundary": reason})
    if extra:
        metadata.update(extra)
    return Span(
        label=span.label,
        start=start,
        end=end,
        source=span.source,
        score=span.score,
        native_label=span.native_label,
        metadata=metadata,
    )


def link_bank_account_spans_with_catalog(text: str, spans: list[Span]) -> list[Span]:
    """Keep model-positive accounts via legacy, expanded-field, or KFTC evidence.

    KFTC evidence never creates a span and never rejects a legacy-accepted span.
    A number unsupported by the catalog can still survive through the existing
    field policy, which prevents the official table from becoming a hard deny
    list.
    """

    legacy = legacy_linked_account_spans(text, spans)
    legacy_accounts = [span for span in legacy if span.label == "KR_BANK_ACCOUNT"]
    output = [span for span in legacy if span.label != "KR_BANK_ACCOUNT"]
    fields = expanded_account_field_ranges(text)
    tokens = account_tokens(text)

    for span in spans:
        if span.label != "KR_BANK_ACCOUNT":
            continue
        legacy_matches = [item for item in legacy_accounts if _overlaps(span.start, span.end, item.start, item.end)]
        field_matches = [(start, end) for start, end in fields if _overlaps(span.start, span.end, start, end)]
        bank_matches = []
        for start, end in tokens:
            if not _overlaps(span.start, span.end, start, end):
                continue
            evidence = evidence_for_range(text, start, end)
            if evidence:
                bank_matches.append((start, end, evidence))

        if field_matches:
            start, end = max(field_matches, key=lambda item: min(item[1], span.end) - max(item[0], span.start))
            evidence = evidence_for_range(text, start, end)
            output.append(_replace(
                span,
                start,
                end,
                "account-value-linked-to-expanded-field",
                {"kftc_cms_account_evidence": evidence} if evidence else None,
            ))
        elif bank_matches:
            start, end, evidence = max(
                bank_matches,
                key=lambda item: (
                    min(item[1], span.end) - max(item[0], span.start),
                    any(entry["matched_strength"] != "length" for entry in item[2]),
                ),
            )
            output.append(_replace(
                span,
                start,
                end,
                "model-positive-plus-kftc-institution-scheme",
                {"kftc_cms_account_evidence": evidence},
            ))
        elif legacy_matches:
            output.append(max(legacy_matches, key=lambda item: item.end - item.start))

    # Exact dedup here avoids duplicating a legacy span selected by two partial
    # model outputs.  The pipeline still performs its normal global dedup later.
    deduped = {}
    for span in output:
        key = (span.label, span.start, span.end, span.source)
        deduped[key] = span
    return list(deduped.values())
