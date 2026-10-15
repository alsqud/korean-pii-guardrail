#!/usr/bin/env python3
"""Regression tests for same-line institution binding."""

from __future__ import annotations

from korean_pii.types import Span

from korean_pii.bank_account_evidence import catalog_summary, evidence_for_range
from korean_pii.bank_account_linking import link_bank_account_spans


def span(text: str, surface: str) -> Span:
    start = text.index(surface)
    return Span(
        label="KR_BANK_ACCOUNT", start=start, end=start + len(surface),
        source="model:atonlee", score=0.89, native_label="ACCOUNT_NUMBER", metadata={},
    )


def main() -> None:
    summary = catalog_summary()
    assert summary["institutions"] == 55
    assert summary["cross_line_institution_borrowing"] is False

    # A correct account field is followed by a model-positive
    # driver number.  The second line must not borrow the bank name.
    text = "[환불 계좌] | 신한은행 110-25670164-9\n운전면허번호 11-21-410173-31"
    account = "110-25670164-9"
    driver = "11-21-410173-31"
    selected = link_bank_account_spans(text, [span(text, account), span(text, driver)])
    accounts = [text[item.start:item.end] for item in selected if item.label == "KR_BANK_ACCOUNT"]
    assert accounts == [account], accounts
    driver_start = text.index(driver)
    assert evidence_for_range(text, driver_start, driver_start + len(driver)) == []

    # Same-line bank evidence remains available without an account cue.
    direct = "송금 대상은 신한은행 110-436-387740입니다."
    value = "110-436-387740"
    direct_selected = link_bank_account_spans(direct, [span(direct, value)])
    assert [direct[item.start:item.end] for item in direct_selected] == [value]

    # A bounded field remains non-denying even if the number is absent from the
    # catalog.  The official table is supporting evidence, never a deny list.
    unsupported = "계좌번호::=211-4401-720001"
    kept = link_bank_account_spans(unsupported, [span(unsupported, "211-4401-720001")])
    assert [unsupported[item.start:item.end] for item in kept] == ["211-4401-720001"]

    # Institution evidence never creates a span without model evidence.
    assert link_bank_account_spans("국민은행 123-01-4567-89-0", []) == []
    print({"status": "PASS", **summary, "cross_line_regression": True})


if __name__ == "__main__":
    main()
