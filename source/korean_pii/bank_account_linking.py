#!/usr/bin/env python3
"""Bank-account linkage with same-line KFTC institution evidence."""

from __future__ import annotations

from korean_pii.postprocess import linked_account_spans as legacy_linked_account_spans

from .bank_account_evidence import account_tokens, evidence_for_range
from .bank_account_fields import _overlaps, _replace, expanded_account_field_ranges


def link_bank_account_spans(text: str, spans: list) -> list:
    """Keep model accounts via legacy, expanded field, or same-line KFTC evidence."""

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
                span, start, end, "account-value-linked-to-expanded-field",
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
                span, start, end, "model-positive-plus-same-line-kftc-institution-scheme",
                {"kftc_cms_account_evidence": evidence},
            ))
        elif legacy_matches:
            output.append(max(legacy_matches, key=lambda item: item.end - item.start))
    deduped = {}
    for span in output:
        deduped[(span.label, span.start, span.end, span.source)] = span
    return list(deduped.values())
