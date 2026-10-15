from __future__ import annotations

import os
import re
import sys
import threading

from .config import Policy
from .errors import ModelLoadError
from .types import Span


_COMMON_SINGLE_SYLLABLE_SURNAMES = frozenset(
    "김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하"
    "곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표"
    "명기반라왕금옥육인맹제모탁국어은편용"
)
_METALINGUISTIC_NAME_CUE = re.compile(
    r"(?:사람[ \t]*이름|인명|이름|성명)(?:과|와|을|를|처럼)?[ \t]*"
    r"(?:비슷(?:한|하게)?|닮은|같은|처럼[ \t]*보이는|같아[ \t]*보이는)[ \t]*$"
)
_PERSON_ROLE_NOUNS = frozenset({
    "님", "씨", "선생", "선생님", "교수", "교수님", "의사", "간호사", "환자",
    "담당자", "신청인", "고객", "직원", "기사", "운전자", "소유자", "대표",
    "팀장", "부장", "과장", "매니저", "원고", "피고",
})
_PERSON_TRAILING_PARTICLES = frozenset({
    "은", "는", "이", "가", "을", "를", "의", "와", "과", "에게", "께", "도", "만",
})
_QUOTATIVE_SELF_INTRO = re.compile(
    r"^(?:이?라고)[ \t]*(?:합니다|해요|했습니다|소개(?:합니다|했습니다)|말(?:합니다|했습니다))"
)
_PERSON_LEFT_CUE = re.compile(
    r"(?:담당자|신청인|고객|환자|직원|기사|운전자|소유자|대표|팀장|부장|"
    r"과장|매니저|원고|피고|성명|이름)[ 	]*$"
)
_PERSON_CONTEXT_CUE = re.compile(
    r"(?:담당자|신청인|고객|환자|직원|기사|운전자|소유자|대표|팀장|부장|"
    r"과장|매니저|원고|피고|성명|이름)"
)
_NON_PERSON_NAME_FIELD_CUE = re.compile(
    r"(?:제품[ \t]*명|제품[ \t]*이름|프로그램[ \t]*(?:명|이름|제목)|"
    r"작품[ \t]*(?:명|제목)|행사[ \t]*프로그램[ \t]*(?:명|이름|제목)|"
    r"상표|브랜드[ \t]*(?:명|이름))"
    r"[ \t]*(?:은|는|이|가)?[ \t]*$"
)
_EXPLICIT_NON_PERSON_RIGHT_CUE = re.compile(
    r"^(?:은|는|이|가|을|를|이며|이고|이다|입니다)?[ \t,]*"
    r"(?:(?![.!?\n]).){0,32}"
    r"(?:사람[ \t]*이름이[ \t]*아니라|개인을?[ \t]*지칭하지[ \t]*않는|"
    r"담당[ \t]*인명이[ \t]*아니다|사람[ \t]*이름으로[ \t]*쓰인[ \t]*것이[ \t]*아니다|"
    r"소유자[ \t]*성명이[ \t]*아니다|개인[ \t]*이름이[ \t]*아니다)"
)
_DOCUMENT_META_NOUNS = frozenset({
    "문서", "자료", "주석", "본문", "기록", "서류", "메모", "표", "항목",
})
_GIM_FOOD_PREDICATE = re.compile(
    r"^(?:은|는|이|가|을|를)[ 	]*"
    r"(?:(?:도시락|식사|음식|요리|김밥)[ 	]*)?"
    r"(?:반찬|재료|식재료|해조류|식품|음식)"
    r"(?:"
    r"(?:이(?:고|다|며|거나)|입니다|이에요|예요|임)(?=[ 	\n.,!?]|$)"
    r"|(?:으)?로[ 	]*(?:먹|사용|활용|준비|보관)"
    r")"
)


def _is_hangul(char: str) -> bool:
    return "가" <= char <= "힣"


def _is_proper_noun_range(tokens, start: int, end: int) -> bool:
    selected = sorted(
        (token for token in tokens if start <= token.start and token.start + token.len <= end),
        key=lambda token: token.start,
    )
    if not selected or selected[0].start != start:
        return False
    cursor = start
    for token in selected:
        if token.start != cursor or token.tag != "NNP":
            return False
        cursor = token.start + token.len
    return cursor == end


def _has_non_person_derivational_tail(tokens, start: int, end: int) -> bool:
    trailing = [token for token in tokens if token.start >= start and token.start + token.len == end]
    if not trailing:
        return False
    token = trailing[-1]
    # XSN and NNB are respectively nominal derivational suffixes and dependent
    # nouns.  Require a preceding two-syllable base so a one-token proper name
    # ending in the same surface syllable is not rejected.
    derivational = token.tag in {"XSN", "NNB"}
    return derivational and token.start - start >= 2


def _has_person_boundary_token(tokens, offset: int) -> bool:
    for token in tokens:
        if token.start != offset:
            continue
        if token.tag.startswith("J") or token.tag == "VCP":
            return True
        if token.form in {"님", "씨"} and token.tag in {"XSN", "NNB", "NNG"}:
            return True
    return False


def _is_metalinguistic_object_name(text: str, tokens, start: int, end: int) -> bool:
    """Identify a name-like token used as the modifier of a non-person noun.

    The cue is semantic ("name-like" or "looks like a name"), while Kiwi must
    confirm that the following token is a noun rather than a case particle,
    honorific, or person-role noun.  The rule therefore generalizes across
    names and object nouns without a literal test-string exception.
    """

    if not re.fullmatch(r"[가-힣]{2,6}", text[start:end]):
        return False
    left = text[max(0, start - 32):start]
    if _METALINGUISTIC_NAME_CUE.search(left) is None:
        return False
    if _has_person_boundary_token(tokens, end):
        return False
    following = sorted(
        (token for token in tokens if token.start >= end),
        key=lambda token: token.start,
    )
    if not following:
        return False
    token = following[0]
    if text[end:token.start].strip():
        return False
    if token.form in _PERSON_ROLE_NOUNS:
        return False
    return token.tag.startswith("N")


def _is_non_person_homonym(text: str, start: int, end: int) -> bool:
    """Reject a one-syllable surname prediction in a clear non-person sense.

    ``김`` is both a common surname and the ordinary food noun for dried
    seaweed.  Model window order can flip the same food occurrence between
    PERSON and non-PERSON.  This rule requires an explicit food predicate and
    yields to a directly preceding person-role/name field, so a bare surname
    or a person preparing food is not suppressed.
    """

    if text[start:end] != "김":
        return False
    left = text[max(0, start - 16):start]
    if _PERSON_LEFT_CUE.search(left):
        return False
    right = text[end:min(len(text), end + 40)]
    return _GIM_FOOD_PREDICATE.search(right) is not None


def _is_document_meta_noun(text: str, tokens, start: int, end: int) -> bool:
    """Reject a small semantic class of document nouns mislabeled as people.

    The surface must be a known document-structure noun, Kiwi must analyze the
    exact range entirely as common nouns, and no nearby person identity cue may
    be present.  This avoids a global confidence or PERSON threshold change.
    """

    if text[start:end] not in _DOCUMENT_META_NOUNS:
        return False
    context = text[max(0, start - 32):min(len(text), end + 32)]
    if _PERSON_CONTEXT_CUE.search(context):
        return False
    selected = sorted(
        (token for token in tokens if start <= token.start and token.start + token.len <= end),
        key=lambda token: token.start,
    )
    if not selected or selected[0].start != start:
        return False
    cursor = start
    for token in selected:
        if token.start != cursor or token.tag != "NNG":
            return False
        cursor = token.start + token.len
    return cursor == end


def _has_explicit_non_person_right_cue(text: str, end: int) -> bool:
    """Honor an explicit local statement that the candidate is not a person."""

    return _EXPLICIT_NON_PERSON_RIGHT_CUE.search(text[end:min(len(text), end + 72)]) is not None


class KiwiBoundaryNormalizer:
    def __init__(self, policy: Policy):
        self.policy = policy
        self._kiwi = None
        self._lock = threading.RLock()

    @property
    def loaded(self) -> bool:
        return self._kiwi is not None

    def load(self) -> None:
        with self._lock:
            if self._kiwi is not None:
                return
            optional_path = os.getenv(self.policy.runtime["kiwi_site_packages_env"])
            if optional_path and optional_path not in sys.path:
                # Current-server compatibility only. Normal installs should put
                # kiwipiepy in the same environment and leave this unset.
                sys.path.append(optional_path)
            try:
                from kiwipiepy import Kiwi
                self._kiwi = Kiwi()
            except Exception as exc:
                raise ModelLoadError(f"Kiwi initialization failed: {type(exc).__name__}") from exc

    def normalize_people(self, text: str, spans: list[Span]) -> list[Span]:
        self.load()
        with self._lock:
            tokens = self._kiwi.tokenize(text)
        output = []
        for span in spans:
            if span.label != "PERSON" or span.source != "model:frame":
                output.append(span)
                continue
            end = span.end
            while True:
                trailing = [token for token in tokens if token.start >= span.start and token.start + token.len == end]
                if not trailing:
                    break
                token = trailing[-1]
                particle = token.tag.startswith("J") and token.form in _PERSON_TRAILING_PARTICLES
                honorific = token.form in {"님", "씨"} and token.tag in {"XSN", "NNB", "NNG"}
                if not (particle or honorific) or token.start - span.start < 2:
                    break
                end = token.start
            start = span.start
            metadata = dict(span.metadata)
            changes = []
            if end != span.end:
                changes.append("trailing particle or honorific trimmed")

            # A Frame PERSON covering only part of a larger Hangul token is not
            # independently maskable.  The sole conservative expansion below
            # requires a three-syllable token, a recognized one-syllable family
            # name, clean token boundaries, and Kiwi proper-noun analysis.
            left_hangul = start > 0 and _is_hangul(text[start - 1])
            right_hangul = end < len(text) and _is_hangul(text[end])
            quotative_boundary = _QUOTATIVE_SELF_INTRO.search(text[end:min(len(text), end + 24)]) is not None
            right_is_boundary = not right_hangul or _has_person_boundary_token(tokens, end) or quotative_boundary
            # Some synthetic or user-entered Korean attaches a nominative
            # particle that Kiwi does not split (for example, a 받침-ending
            # name followed by "가"). Preserve only a complete 2--4 syllable,
            # high-confidence Frame span with an explicit nearby person cue.
            context = text[max(0, start - 32):min(len(text), end + 32)]
            conservative_particle_fallback = (
                right_hangul
                and text[end:end + 1] in _PERSON_TRAILING_PARTICLES
                and 2 <= end - start <= 4
                and span.score >= 0.99
                and _PERSON_CONTEXT_CUE.search(context) is not None
            )
            if conservative_particle_fallback:
                right_is_boundary = True
                changes.append("explicit person cue plus particle fallback")
            if left_hangul:
                candidate_start = start - 1
                bounded_left = candidate_start == 0 or not _is_hangul(text[candidate_start - 1])
                can_expand = (
                    end - start == 2
                    and right_is_boundary
                    and bounded_left
                    and text[candidate_start] in _COMMON_SINGLE_SYLLABLE_SURNAMES
                    and _is_proper_noun_range(tokens, candidate_start, end)
                )
                if not can_expand:
                    continue
                start = candidate_start
                changes.append("leading surname restored from proper-noun token")
            elif not right_is_boundary:
                continue

            explicit_identity_boundary = (
                2 <= end - start <= 4
                and span.score >= 0.99
                and _PERSON_CONTEXT_CUE.search(context) is not None
                and _has_person_boundary_token(tokens, end)
            )
            if _has_non_person_derivational_tail(tokens, start, end) and not explicit_identity_boundary:
                continue

            if changes:
                metadata["kiwi_normalization"] = "; ".join(changes)
            output.append(Span(
                label=span.label, start=start, end=end, source=span.source,
                score=span.score, native_label=span.native_label, metadata=metadata,
            ))
        return output

    def filter_people_context(self, text: str, spans: list[Span]) -> list[Span]:
        """Remove PERSON spans that are name-like object modifiers.

        This runs after expert routing so a span rejected from Frame cannot be
        reintroduced by a specialist model using the same metalinguistic cue.
        """

        self.load()
        with self._lock:
            tokens = self._kiwi.tokenize(text)
        return [
            span for span in spans
            if not (
                span.label == "PERSON"
                and (
                    _is_metalinguistic_object_name(text, tokens, span.start, span.end)
                    or _is_non_person_homonym(text, span.start, span.end)
                    or _is_document_meta_noun(text, tokens, span.start, span.end)
                    or _has_explicit_non_person_right_cue(text, span.end)
                    or _NON_PERSON_NAME_FIELD_CUE.search(
                        text[max(0, span.start - 48):span.start]
                    ) is not None
                )
            )
        ]
