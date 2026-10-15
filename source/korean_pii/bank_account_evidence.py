#!/usr/bin/env python3
"""KFTC account evidence bound to the candidate's physical line."""

from __future__ import annotations

import re

from .bank_account_catalog import (
    SOURCE_AS_OF,
    SOURCE_DOWNLOAD_URL,
    SOURCE_PUBLISHED,
    SOURCE_TITLE,
    SOURCE_URL,
    SCHEMES,
    SCHEME_BY_KEY,
    InstitutionScheme,
    PrefixRule,
    _ALIASES,
    account_tokens,
    catalog_summary as _catalog_summary,
    match_scheme,
    normalize_account,
    observed_groups,
)


def institution_mentions(text: str, start: int, end: int, radius: int = 72) -> list[InstitutionScheme]:
    """Find institution evidence on the candidate's own physical line only."""

    line_start = text.rfind("\n", 0, start) + 1
    next_break = text.find("\n", end)
    line_end = len(text) if next_break < 0 else next_break
    left = max(line_start, start - radius)
    right = min(line_end, end + radius)
    context = text[left:right]
    found: dict[str, InstitutionScheme] = {}
    for scheme, _alias, pattern in _ALIASES:
        if pattern.search(context):
            found[scheme.key] = scheme
    code_match = re.search(
        r"(?:금융[ \t]*기관|은행|기관)[ \t]*(?:대표[ \t]*)?코드"
        r"[ \t]*(?::|：|=|은|는)?[ \t]*(?P<code>\d{3})(?!\d)",
        context,
    )
    if code_match is not None:
        code = code_match.group("code")
        for scheme in SCHEMES:
            if code in scheme.codes:
                found[scheme.key] = scheme
    return list(found.values())


def evidence_for_range(text: str, start: int, end: int) -> list[dict]:
    surface = text[start:end]
    evidence = []
    for scheme in institution_mentions(text, start, end):
        matched = match_scheme(surface, scheme)
        if matched is not None:
            evidence.append(matched)
    order = {"subject_code": 0, "grouping": 1, "length": 2}
    return sorted(evidence, key=lambda item: (order[item["matched_strength"]], item["institution_key"]))


def catalog_summary() -> dict:
    summary = _catalog_summary()
    summary["institution_binding"] = "same physical line as candidate; radius <= 72"
    summary["cross_line_institution_borrowing"] = False
    return summary
