#!/usr/bin/env python3
"""Bank-aware account-number evidence derived from the official KFTC CMS table.

This is experimental evidence, not a bank-account validity oracle.  The KFTC
document describes account-number *schemes* accepted by CMS as of 2026-05-08;
it does not publish every check-digit algorithm.  Consequently this module:

* never claims that a number is an open/real account;
* never rejects an existing model-positive solely because no scheme matches;
* treats an institution-name + official length/grouping match as supporting
  evidence only; and
* records the source page and the exact rule that matched.

Official source:
https://www.cmsedi.or.kr/cms/board/workdata/view/1031
"""

from __future__ import annotations

from dataclasses import dataclass
import re


SOURCE_TITLE = "참가기관별 CMS 계좌번호체계"
SOURCE_AS_OF = "2026-05-08"
SOURCE_PUBLISHED = "2026-09-29"
SOURCE_URL = "https://www.cmsedi.or.kr/cms/board/workdata/view/1031"
SOURCE_DOWNLOAD_URL = "https://www.cmsedi.or.kr/cms/board/workdata/download/1031"


@dataclass(frozen=True)
class PrefixRule:
    digits: int
    values: tuple[str, ...] = ()
    ranges: tuple[tuple[int, int], ...] = ()

    def matches(self, normalized: str) -> bool:
        if len(normalized) < self.digits:
            return False
        prefix = normalized[: self.digits]
        if prefix in self.values:
            return True
        number = int(prefix)
        return any(start <= number <= end for start, end in self.ranges)


@dataclass(frozen=True)
class InstitutionScheme:
    key: str
    name: str
    aliases: tuple[str, ...]
    codes: tuple[str, ...]
    kind: str
    page: int
    groups: tuple[tuple[int, ...], ...]
    prefix_rules: tuple[PrefixRule, ...] = ()

    @property
    def lengths(self) -> tuple[int, ...]:
        return tuple(sorted({sum(groups) for groups in self.groups}))


def _s(
    key: str,
    name: str,
    aliases: tuple[str, ...],
    codes: tuple[str, ...],
    kind: str,
    page: int,
    *groups: tuple[int, ...],
    prefix_rules: tuple[PrefixRule, ...] = (),
) -> InstitutionScheme:
    return InstitutionScheme(
        key=key,
        name=name,
        aliases=aliases,
        codes=codes,
        kind=kind,
        page=page,
        groups=groups,
        prefix_rules=prefix_rules,
    )


# Group lengths follow the hyphenated layouts printed on pages 1-19.  A single
# group means the official table prints the value without an internal hyphen.
# Historical layouts remain because the source explicitly retains them.
SCHEMES: tuple[InstitutionScheme, ...] = (
    _s("kdb", "산업은행", ("산업은행", "한국산업은행", "KDB산업은행", "KDB"), ("002",), "bank", 1,
       (3, 2, 5, 1), (3, 7, 1, 3), (3, 8, 3)),
    _s("ibk", "기업은행", ("기업은행", "IBK기업은행", "IBK"), ("003", "043"), "bank", 1,
       (8, 2), (3, 8), (3, 2, 6, 1), (3, 6, 2, 2, 1)),
    _s("kb", "국민은행", ("국민은행", "KB국민은행", "KB은행"), ("004", "006", "019", "029", "079", "078"), "bank", 1,
       (3, 3, 4), (3, 4, 4), (11,), (3, 2, 4, 2, 1), (4, 2, 7, 1), (4, 2, 5, 1),
       prefix_rules=(PrefixRule(1, values=("9",)),)),
    _s("hana_legacy", "구 하나은행", ("구하나은행", "구 하나은행"), ("005",), "bank", 2,
       (3, 2, 5, 1), (3, 6, 3)),
    _s("suhyup", "수협은행·수협중앙회", ("수협은행", "수협중앙회", "수협"), ("007", "009", "030", "069", "070"), "cooperative", 3,
       (3, 2, 6), (3, 9), (1, 11), (3, 11)),
    _s("nh_bank", "농협은행", ("농협은행", "NH농협은행", "NH은행"), ("010", "011", "016"), "bank", 4,
       (3, 2, 5, 1), (4, 2, 5, 1), (3, 4, 4, 1, 1), (6, 2, 5, 1), (3, 4, 4, 2, 1)),
    _s("nh_central", "농협중앙회", ("농협중앙회", "지역농협", "단위농협"), ("012", "013", "014", "015", "017", "018"), "cooperative", 4,
       (3, 4, 4, 1, 1), (6, 2, 5, 1), (3, 4, 4, 2, 1)),
    _s("woori", "우리은행", ("우리은행", "통합우리은행"), ("020", "022", "024", "083", "084"), "bank", 5,
       (4, 3, 6), (3, 6, 2, 2, 1), (3, 2, 5, 1), (3, 2, 6, 1)),
    _s("sc", "SC제일은행", ("SC제일은행", "SC은행", "제일은행"), ("023",), "bank", 5,
       (3, 2, 6), (15,), (3, 2, 9), (16,)),
    _s("citi", "한국씨티은행", ("한국씨티은행", "씨티은행", "CITI은행"), ("027", "036", "053"), "bank", 6,
       (3, 5, 2, 1, 2), (1, 6, 1, 2, 2), (3, 5, 2, 1), (1, 6, 2, 1), (2, 2, 5, 1)),
    _s("imbank", "아이엠뱅크", ("아이엠뱅크", "iM뱅크", "IM뱅크", "대구은행"), ("031",), "bank", 7,
       (7,), (8,), (9,), (10,), (11,), (2, 11), (3, 2, 6, 1), (3, 2, 6, 3), (3, 10, 1)),
    _s("busan", "부산은행", ("부산은행", "BNK부산은행"), ("032",), "bank", 7,
       (3, 2, 6, 1), (3, 4, 4, 2)),
    _s("gwangju", "광주은행", ("광주은행", "KJ광주은행"), ("034",), "bank", 8,
       (3, 3, 5, 1), (3, 3, 6), (1, 3, 9)),
    _s("jeju", "제주은행", ("제주은행",), ("035",), "bank", 8,
       (2, 2, 6), (3, 9)),
    _s("jeonbuk", "전북은행", ("전북은행", "JB전북은행"), ("037",), "bank", 8,
       (3, 2, 7), (1, 3, 2, 7)),
    _s("kyongnam", "경남은행", ("경남은행", "BNK경남은행"), ("039",), "bank", 8,
       (3, 2, 7), (3, 9, 1)),
    _s("kfcc", "새마을금고", ("새마을금고", "새마을금고중앙회", "MG새마을금고"), ("045", "046", "085", "086", "087"), "cooperative", 9,
       (4, 2, 6, 1), (4, 8, 1)),
    _s("cu", "신협중앙회", ("신협", "신협중앙회", "신용협동조합"), ("047", "048", "049"), "cooperative", 9,
       (5, 2, 5, 1), (5, 2, 6, 1), (3, 3, 4), (3, 4, 4), (3, 3, 5, 1)),
    _s("savings", "상호저축은행", ("상호저축은행", "저축은행"), ("050",), "savings_bank", 9,
       (3, 2, 2, 6, 1)),
    _s("hsbc", "HSBC은행", ("HSBC은행", "HSBC"), ("054",), "foreign_bank", 10,
       (3, 5, 1, 3)),
    _s("deutsche", "도이치은행", ("도이치은행", "DEUTSCHE BANK"), ("055",), "foreign_bank", 10,
       (10,)),
    _s("jpm", "제이피모간체이스은행", ("제이피모간체이스은행", "JP모간은행", "JPMORGAN"), ("057",), "foreign_bank", 10,
       (10,)),
    _s("boa", "BOA은행", ("BOA은행", "뱅크오브아메리카", "BANK OF AMERICA"), ("060",), "foreign_bank", 10,
       (4, 5, 2, 1), (4, 10)),
    _s("bnp", "비엔피파리바은행", ("비엔피파리바은행", "BNP파리바은행", "BNP PARIBAS"), ("061",), "foreign_bank", 10,
       (5, 6, 3)),
    _s("forestry", "산림조합중앙회", ("산림조합", "산림조합중앙회"), ("064",), "cooperative", 11,
       (5, 2, 6)),
    _s("post", "우체국", ("우체국", "우체국예금", "우정사업본부"), ("071", "072", "073", "074", "075"), "postal", 11,
       (3, 8, 1), (1, 11, 1), (6, 6, 1), (6, 2, 6),
       prefix_rules=(PrefixRule(3, values=("100", "530", "190", "110", "120")), PrefixRule(1, values=("8", "9")))),
    _s("hana", "하나은행", ("하나은행", "KEB하나은행"), ("005", "025", "033", "080", "081", "082"), "bank", 11,
       (3, 9, 2)),
    _s("shinhan", "신한은행", ("신한은행", "통합신한은행"), ("021", "026", "028", "088"), "bank", 12,
       (3, 8, 1), (3, 3, 7, 1), (3, 2, 5, 1), (3, 2, 7, 1), (3, 2, 8),
       prefix_rules=(PrefixRule(3, values=("160", "161", "268", "269", "298", "560", "561", "562"), ranges=((100, 159),)),)),
    _s("kbank", "케이뱅크", ("케이뱅크", "K뱅크", "Kbank"), ("089",), "internet_bank", 13,
       (1, 9), (3, 3, 6), (2, 3, 4, 4), (3, 4, 3, 4),
       prefix_rules=(PrefixRule(1, values=("7", "9")),)),
    _s("kakao_bank", "카카오뱅크", ("카카오뱅크", "카뱅"), ("090",), "internet_bank", 13,
       (4, 2, 7)),
    _s("toss_bank", "토스뱅크", ("토스뱅크",), ("092",), "internet_bank", 13,
       (3, 8, 1), (2, 10),
       prefix_rules=(PrefixRule(3, values=("100", "150")), PrefixRule(2, values=("17", "19")))),
    _s("yuanta", "유안타증권", ("유안타증권",), ("209",), "broker", 14,
       (3, 2, 6), (4, 4, 4)),
    _s("kb_sec", "KB증권", ("KB증권", "국민증권"), ("218", "226"), "broker", 14,
       (3, 2, 6), (3, 3, 3, 2), (3, 3, 3)),
    _s("mirae", "미래에셋증권", ("미래에셋증권", "미래에셋대우"), ("230", "238"), "broker", 15,
       (8,), (9,), (10,), (11,), (12,), (13,), (14,), (3, 2, 6), (3, 2, 7)),
    _s("samsung_sec", "삼성증권", ("삼성증권",), ("240",), "broker", 15,
       (8,), (10,), (12,), (1, 5, 8)),
    _s("korea_invest", "한국투자증권", ("한국투자증권", "한투증권"), ("243",), "broker", 16,
       (8, 2), (8, 4), (8, 2, 4)),
    _s("nh_invest", "NH투자증권", ("NH투자증권", "우리투자증권", "NH농협증권"), ("247", "289"), "broker", 16,
       (11,)),
    _s("kyobo", "교보증권", ("교보증권",), ("261",), "broker", 16,
       (3, 2, 6), (4, 4, 1, 2)),
    _s("im_sec", "아이엠증권", ("아이엠증권", "iM증권", "하이투자증권"), ("262",), "broker", 16,
       (4, 4, 2)),
    _s("hyundai_motor_sec", "현대차증권", ("현대차증권", "현대차투자증권"), ("263",), "broker", 16,
       (8,)),
    _s("kiwoom", "키움증권", ("키움증권",), ("264",), "broker", 16,
       (4, 4, 2), (4, 4)),
    _s("ls_sec", "엘에스증권", ("엘에스증권", "LS증권", "이베스트투자증권"), ("265",), "broker", 17,
       (3, 2, 6), (9,), (11,)),
    _s("sk_sec", "SK증권", ("SK증권",), ("266",), "broker", 17,
       (9,), (11,)),
    _s("daishin", "대신증권", ("대신증권",), ("267",), "broker", 17,
       (3, 6), (3, 6, 2)),
    _s("hanwha", "한화투자증권", ("한화투자증권", "한화증권"), ("269",), "broker", 17,
       (10,), (3, 8), (13,), (3, 11)),
    _s("hana_sec", "하나증권", ("하나증권", "하나금융투자"), ("270",), "broker", 17,
       (7, 1), (7, 1, 2), (8, 3), (8, 3, 3)),
    _s("shinhan_sec", "신한투자증권", ("신한투자증권", "신한금융투자"), ("278",), "broker", 18,
       (3, 2, 6)),
    _s("db_financial", "DB금융투자", ("DB금융투자", "동부증권"), ("279",), "broker", 18,
       (3, 2, 4), (3, 2, 4, 2)),
    _s("eugene", "유진투자증권", ("유진투자증권",), ("280",), "broker", 18,
       (11,)),
    _s("meritz", "메리츠증권", ("메리츠증권", "메리츠종금증권"), ("287", "268"), "broker", 18,
       (4, 4, 2), (3, 2, 6)),
    _s("kakao_pay_sec", "카카오페이증권", ("카카오페이증권",), ("288",), "broker", 18,
       (11,)),
    _s("bookook", "부국증권", ("부국증권",), ("290",), "broker", 19,
       (3, 2, 6)),
    _s("shinyoung", "신영증권", ("신영증권",), ("291",), "broker", 19,
       (9,), (12,)),
    _s("cape", "케이프투자증권", ("케이프투자증권", "LIG투자증권"), ("292",), "broker", 19,
       (3, 2, 6), (3, 2, 6, 3)),
    _s("woori_sec", "우리투자증권", ("우리투자증권", "한국포스증권"), ("294",), "broker", 19,
       (3, 2, 6)),
)


SCHEME_BY_KEY = {scheme.key: scheme for scheme in SCHEMES}
_DIGIT_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:\d[ \t-]?){6,15}\d(?![A-Za-z0-9])")


def normalize_account(surface: str) -> str:
    return "".join(character for character in surface if character.isdigit())


def observed_groups(surface: str) -> tuple[int, ...]:
    return tuple(len(group) for group in re.findall(r"\d+", surface))


def match_scheme(surface: str, scheme: InstitutionScheme) -> dict | None:
    normalized = normalize_account(surface)
    groups = observed_groups(surface)
    length_match = len(normalized) in scheme.lengths
    if not length_match:
        return None
    has_separator = bool(re.search(r"[ \t-]", surface))
    grouping_match = has_separator and groups in scheme.groups
    prefix_match = any(rule.matches(normalized) for rule in scheme.prefix_rules)
    # Unformatted numbers cannot demonstrate grouping, but the official total
    # length still provides weak evidence when an institution name is explicit.
    strength = "subject_code" if prefix_match else "grouping" if grouping_match else "length"
    return {
        "institution_key": scheme.key,
        "institution_name": scheme.name,
        "institution_codes": list(scheme.codes),
        "institution_kind": scheme.kind,
        "source_page": scheme.page,
        "source_as_of": SOURCE_AS_OF,
        "normalized_digits": len(normalized),
        "observed_groups": list(groups),
        "matched_strength": strength,
        "grouping_match": grouping_match,
        "prefix_or_subject_match": prefix_match,
    }


def _alias_pattern(alias: str) -> re.Pattern[str]:
    # Korean names need no \b boundary; ASCII aliases do.  Optional horizontal
    # whitespace tolerates forms such as "KB 국민은행" without crossing lines.
    escaped = re.escape(alias).replace(r"\ ", r"[ \t]*")
    if alias.isascii():
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


_ALIASES = tuple(
    (scheme, alias, _alias_pattern(alias))
    for scheme in SCHEMES
    for alias in sorted(scheme.aliases, key=len, reverse=True)
)


def institution_mentions(text: str, start: int, end: int, radius: int = 72) -> list[InstitutionScheme]:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    context = text[left:right]
    found: dict[str, InstitutionScheme] = {}
    for scheme, _alias, pattern in _ALIASES:
        if pattern.search(context):
            found[scheme.key] = scheme
    # A bare three-digit sequence is far too ambiguous.  Codes count only when
    # an explicit institution-code field labels them.  The official code table
    # is page 22 of the same KFTC document.
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


def account_tokens(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _DIGIT_TOKEN.finditer(text)]


def catalog_summary() -> dict:
    return {
        "source_title": SOURCE_TITLE,
        "source_as_of": SOURCE_AS_OF,
        "source_url": SOURCE_URL,
        "institutions": len(SCHEMES),
        "by_kind": {
            kind: sum(scheme.kind == kind for scheme in SCHEMES)
            for kind in sorted({scheme.kind for scheme in SCHEMES})
        },
        "pages_covered": sorted({scheme.page for scheme in SCHEMES}),
    }
