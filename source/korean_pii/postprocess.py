from __future__ import annotations

import re

from .candidates import DRIVER_LICENSE_PATTERN, KOREAN_VALUE_END_PATTERN, VEHICLE_PLATE_PATTERN
from .gazetteer import AddressGazetteer
from .types import Span


_HSPACE = r"[ \t]*"
_FIELD_GAP = r"[ \t]*(?:\r?\n[ \t]*)?[\"'‘“]?[ \t]*"
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

# A single structural field grammar supplements the older phrase-specific
# patterns below.  It recognizes a field name, a bounded Korean particle /
# delimiter region, and a type-specific value shape.  The gap deliberately
# cannot contain arbitrary words, so a cue cannot leak to a later value.
_STRUCTURED_FIELD_CUES = {
    "DATE_OF_BIRTH": r"(?:생년[ \t]*월일|출생일|출생[ \t]*(?:날짜|한[ \t]*날)|태어난[ \t]*(?:날짜|날)|생일)",
    "KR_BANK_ACCOUNT": r"(?:계좌[ \t]*번호|입금[ \t]*계좌|송금[ \t]*계좌|출금[ \t]*계좌|환불[ \t]*계좌|통장[ \t]*번호|계좌|통장)",
    "USERNAME": r"(?:사용자명|로그인[ \t]*(?:아이디|ID|명)|계정명|사용자[ \t]*(?:아이디|ID|계정)|포털[ \t]*사용자명|username|user[ \t]*id|login[ \t]*id)",
}
_STRUCTURED_FIELD_VALUES = {
    "DATE_OF_BIRTH": _DATE_VALUE,
    "KR_BANK_ACCOUNT": _ACCOUNT_VALUE,
    "USERNAME": _USERNAME_VALUE,
}
_STRUCTURED_FIELD_GAP = (
    r"[ \t]*(?:에게는|에서는|으로는|에는|은|는|이|가|을|를|에|로|인)?"
    r"[ \t]*(?:(?::|：|=|\|)|(?:[-–—][ \t]*>))?[ \t]*"
    r"(?:[\(\[{'\"‘“][ \t]*)?"
)
_STRUCTURED_FIELD_PATTERNS = {
    label: re.compile(
        rf"(?P<cue>{cue}){_STRUCTURED_FIELD_GAP}(?P<value>{_STRUCTURED_FIELD_VALUES[label]})",
        re.IGNORECASE,
    )
    for label, cue in _STRUCTURED_FIELD_CUES.items()
}
_EXPLICIT_NON_PERSONAL_FIELD = re.compile(
    r"(?:제품|부품|장치|모델|운송장|물류|포장)[ \t]*(?:코드|번호|참조|계정|아이디|ID)?[ \t]*$",
    re.IGNORECASE,
)
_RECONFIRMATION_CUE = re.compile(
    r"(?:재확인(?:란)?(?:에도)?[ \t]*(?:앞과[ \t]*)?같은[ \t]*값|"
    r"동일(?:한)?[ \t]*(?:값|사용자명|계정|계좌)|같은[ \t]*(?:사용자명|계정|계좌))"
)
_REPEAT_NEGATIVE_CONTEXT = re.compile(r"제품|운송장|물류|포장|부품|모델")


# These patterns establish a direct relationship between the cue and the value.
# Horizontal whitespace is intentional: a cue in another line/field cannot leak
# into the candidate merely because it is nearby in character distance.
_DOB_VALUE_PATTERNS = (
    re.compile(
        rf"(?:본인(?:이|은|의)?[ \t]*)?(?:태어난|출생한)[ \t]*"
        rf"(?P<value>{_DATE_VALUE})[ \t]*(?:이라는|라는)[ \t]*"
        rf"(?:날짜|생년[ \t]*월일|출생일)"
    ),
    re.compile(
        rf"(?:생년[ \t]*월일|출생일|출생[ \t]*날짜|생일){_FIELD_GAP}"
        rf"(?:은|는|이|가)?{_HSPACE}(?::|：|=)?{_FIELD_GAP}"
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
    re.compile(
        rf"(?P<value>{_DATE_VALUE}){_HSPACE}(?:[—–-]{_HSPACE}|\r?\n[ \t]*)"
        rf"(?:(?![.!?\n]).){{0,64}}(?:생년[ \t]*월일|출생일|출생[ \t]*날짜|태어난[ \t]*날)"
        rf"(?:로[ \t]*(?:제출|기재|등록)|(?:이|입니)다)"
    ),
    re.compile(
        rf"(?:생년[ \t]*월일|출생일|출생[ \t]*날짜|생일)(?:(?![.!?\n]).){{0,32}}"
        rf"(?P<value>{_DATE_VALUE})(?=(?:은|는|이|가|을|를|로)?[ \t\n.,!?]|$)"
    ),
    re.compile(
        rf"(?P<value>{_DATE_VALUE})(?:은|는|이|가)?[ \t]*"
        rf"(?:(?![.!?\n]).){{0,24}}(?:제[ \t]*)?(?:태어난[ \t]*날|출생일|출생[ \t]*날짜)"
    ),
    re.compile(
        rf"(?:태어난[ \t]*날|출생[ \t]*날짜)(?:은|는|이|가)?[ \t]*"
        rf"(?P<value>{_DATE_VALUE})(?=(?:은|는|이|가|을|를|로|이고)?[ \t\n.,!?]|$)"
    ),
)

_ACCOUNT_VALUE_PATTERNS = (
    re.compile(
        rf"(?:계좌[ \t]*번호|입금[ \t]*계좌|송금[ \t]*계좌|출금[ \t]*계좌|"
        rf"환불[ \t]*계좌|계좌){_FIELD_GAP}(?:은|는|이|가)?{_HSPACE}"
        rf"(?::|：|=)?{_FIELD_GAP}(?:[가-힣A-Za-z]{{1,12}}은행{_HSPACE})?"
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
    re.compile(
        rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS}){_HSPACE}"
        rf"(?:[—–-]{_HSPACE}|\r?\n[ \t]*)"
        rf"(?:(?![.!?\n]).){{0,64}}(?:"
        rf"계좌[ \t]*번호(?:로[ \t]*(?:지정|등록|사용))|"
        rf"(?:본인[ \t]*)?계좌(?:로[ \t]*(?:받|보내|입금)|(?:이|입니)?다))"
    ),
    re.compile(
        rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS})"
        rf"(?:을|를)?[ \t]*(?:본인의?[ \t]*)?계좌[ \t]*번호(?:라고|라며|임을)"
    ),
    re.compile(
        rf"(?:계좌[ \t]*번호|환불[ \t]*계좌)(?:(?![.!?\n]).){{0,48}}"
        rf"(?:다음[ \t]*줄(?:(?![.!?\n]).){{0,24}})?적(?:었|어)[^\n.!?]*[.]?"
        rf"\r?\n[ \t]*(?P<value>{_ACCOUNT_VALUE})"
    ),
    re.compile(
        rf"(?:은행[ \t]*계좌|계좌[ \t]*번호|계좌|통장[ \t]*번호|통장)"
        rf"(?:은|는|이|가|인)?[ \t]*(?::|：|=|\|)?{_FIELD_GAP}"
        rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS})"
        rf"(?=(?:은|는|이|가|을|를|으로|로|도|이며|이고|였(?:다|습니다)|이라고|라고)?[ \t\n.,!?]|$)"
    ),
    re.compile(
        rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS})"
        rf"(?:은|는|이|가|을|를|이라고|라고)?[ \t]*(?:(?![.!?\n]).){{0,32}}"
        rf"(?:본인[ \t]*)?통장(?:[ \t]*번호)?(?:이|라고|입니다|임)?"
    ),
    re.compile(
        rf"(?:계좌|통장)(?:으로|로)[ \t]*(?:본인의?|자신의?)?[ \t]*"
        rf"(?P<value>(?<![가-힣A-Za-z0-9]){_ACCOUNT_DIGITS})"
        rf"(?:은|는|이|가|을|를)?[ \t]*(?:지정|등록|알려|적(?:었|어|은))"
    ),
)

_USERNAME_VALUE_PATTERNS = (
    re.compile(
        rf"(?:회원[ \t]*(?:이름|별칭)|내부[ \t]*(?:별칭|계정명)|"
        rf"(?:[가-힣A-Za-z0-9_-]{{1,20}}[ \t]+)?시스템[ \t]*로그인)"
        rf"(?:은|는|이|가)?{_HSPACE}(?::|：|=)?{_FIELD_GAP}"
        rf"(?P<value>{_USERNAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"본인[ \t]*로그인[ \t]*(?:값|계정)(?:은|는|이|가)?{_HSPACE}"
        rf"(?::|：|=)?{_FIELD_GAP}(?P<value>{_USERNAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:로그인[ \t]*(?:아이디|ID|명)|사용자[ \t]*(?:아이디|ID|명|이름)|"
        rf"계정[ \t]*(?:아이디|ID|명)|아이디|username|user[ \t]*id|login[ \t]*id)"
        rf"{_FIELD_GAP}(?:은|는|이|가)?{_HSPACE}(?::|：|=)?{_FIELD_GAP}"
        rf"(?P<value>{_USERNAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:사용자|계정)[ \t]+(?P<value>{_USERNAME_VALUE})"
        rf"(?=(?:으로|에게|은|는|이|가|을|를|의|로)?(?=[ \t\n.,!?]|$))"
    ),
    re.compile(rf"(?<![A-Za-z0-9._-])(?P<value>@[A-Za-z][A-Za-z0-9._-]{{2,31}})"),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE}){_HSPACE}"
        rf"(?:라는|이라고[ \t]*(?:하는|쓴|사용하는)?)[ \t]*(?:본인[ \t]*)?"
        rf"(?:로그인[ \t]*)?(?:아이디|ID|계정)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE}){_HSPACE}"
        rf"(?:[—–-]{_HSPACE}|\r?\n[ \t]*)"
        rf"(?:(?![.!?\n]).){{0,64}}(?:로그인[ \t]*)?(?:아이디|ID|계정)"
        rf"(?:를[ \t]*(?:사용|씀)|(?:이|입니)?다)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE})[ \t]*"
        rf"(?:이라는?[ \t]*)?(?:로그인[ \t]*)?(?:아이디|ID|사용자명|계정명)(?:으로|로|이다|입니다|임)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:사용자명|계정명|로그인[ \t]*아이디)(?:으로)?[ \t]*"
        rf"제시(?:했|하였)[^\n.!?]*[.]?\r?\n[ \t]*"
        rf"(?P<value>{_USERNAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"계정[ \t]*복구[ \t]*요청의[ \t]*대상은[ \t]*"
        rf"(?P<value>{_USERNAME_VALUE})(?=다(?:[ \t\n.,!?]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:사용자[ \t]*계정|사용자명|본인[ \t]*계정|계정)"
        rf"(?:은|는|이|가|인)?[ \t]*(?::|：|=|\|)?{_FIELD_GAP}"
        rf"(?P<value>{_USERNAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE})"
        rf"(?:으로|로)[ \t]*(?:접속|로그인|들어가|신청서(?:를[ \t]*)?작성)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE})[ \t]*"
        rf"(?:이라는|라는)[ \t]*(?:사용자명|계정명)(?:은|는|이|가)?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE})[ \t]*[—–-][ \t]*"
        rf"(?:(?![.!?\n]).){{0,64}}(?:본인[ \t]*)?계정명(?:이|입니)?다",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE})[ \t]*"
        rf"계정(?:으로|로)[ \t]*(?:접근|접속|로그인)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE})"
        rf"(?:에는|은|는|이|가)?[ \t]*(?:(?![.!?\n]).){{0,48}}"
        rf"(?:접속하는[ \t]*계정|사용하는[ \t]*(?:계정|이름)|계정명|사용자명)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<value>(?<![A-Za-z0-9._-]){_USERNAME_VALUE})(?:으로|로)[ \t]*"
        rf"(?:했|하였|신청했)(?:(?![.!?\n]).){{0,48}}"
        rf"(?:계정|사용자명|사용하는[ \t]*이름)",
        re.IGNORECASE,
    ),
)

_UNIT_DONG = r"(?:\d{1,4}|[A-Za-z가-힣])동"
_STRUCTURED_UNIT_START = rf"(?:지하[ \t]*\d{{1,3}}층|{_UNIT_DONG}|\d{{1,4}}층|\d{{1,4}}호)"
_ADDRESS_UNIT_SUFFIX = rf"(?:[ \t]*(?:{_UNIT_DONG}|\d{{1,4}}층|\d{{1,4}}호))*"
_NO_UNCONSUMED_ADDRESS_UNIT = r"(?![ \t]*\d{1,4}(?:동|층|호))"
_BUILDING_KIND = r"(?:아파트|빌라|오피스텔|타워|빌딩|센터|주택|주차동|상가|회관|관)"
_BUILDING_NAME = rf"(?:[ \t]+(?:[가-힣A-Za-z0-9·_-][가-힣A-Za-z0-9·_ -]{{0,29}}{_BUILDING_KIND}|[가-힣A-Za-z0-9·_-]{{2,30}}(?=[ \t]+{_STRUCTURED_UNIT_START})))?"
_EXTENDED_UNIT = rf"(?:[ \t]+(?:{_STRUCTURED_UNIT_START}|\d{{1,4}}번칸))+"
_ROOM_NAME = r"(?:[ \t]+[가-힣A-Za-z0-9·_-]{1,24}(?:실|창고|로비))?"
_ADDRESS_VALUE_END = rf"(?:{_VALUE_END}|(?=다(?=[ \t\n.,!?]|$)))"
_ROAD_BUILDING_NUMBER_MARKER = r"(?:[ \t]*(?:번지|번))?"
_LEGAL_DONG_COMPONENT = r"[가-힣][가-힣0-9]{0,19}(?:읍|면|리|동(?:\d+가)?|가)"
_FULL_ROAD_LOCATION_PATTERN = re.compile(
    rf"(?<![가-힣A-Za-z0-9])"
    rf"(?P<province>[가-힣]+(?:특별자치도|특별시|광역시|도))[ \t]+"
    rf"(?P<district>(?:[가-힣]+시[ \t]+[가-힣]+구|[가-힣]+(?:시|군|구)))[ \t]+"
    rf"(?P<dong>{_LEGAL_DONG_COMPONENT})[ \t]+"
    rf"(?P<anchor>(?:[가-힣][가-힣0-9]{{1,19}}로[ \t]*\d{{1,4}}(?:번)?길|"
    rf"[가-힣][가-힣0-9]{{1,19}}로\d+번길|"
    rf"[가-힣][가-힣0-9]{{1,29}}(?:대로|로|길)))"
    rf"[ \t]+\d{{1,5}}(?:-\d{{1,5}})?{_ROAD_BUILDING_NUMBER_MARKER}"
    rf"{_BUILDING_NAME}(?:{_EXTENDED_UNIT})?{_ROOM_NAME}{_ADDRESS_VALUE_END}"
)
# Longest-valid full-address grammar.  Detail components are classified by
# shape (building/unit/named place component), not by fixture phrases.  This
# prevents a sentence tail from being swallowed while allowing a final
# reception desk or named room that the older unit grammar truncated.
_ADDRESS_DETAIL_ATOM = (
    rf"(?:[가-힣A-Za-z0-9·_-]{{1,30}}{_BUILDING_KIND}|"
    rf"[가-힣A-Za-z][가-힣A-Za-z0-9·_-]{{1,29}}(?:동|층|호|실|창고|로비)|"
    rf"지하[ \t]*\d{{1,3}}층|{_UNIT_DONG}|\d{{1,4}}(?:층|호|번칸)|"
    rf"[가-힣A-Za-z0-9·_-]{{1,24}}(?:실|대|소|창고|로비))"
)
_LONGEST_FULL_ROAD_LOCATION_PATTERN = re.compile(
    rf"(?<![가-힣A-Za-z0-9])"
    rf"(?P<province>[가-힣]+(?:특별자치도|특별시|광역시|도))[ \t]+"
    rf"(?P<district>(?:[가-힣]+시[ \t]+[가-힣]+구|[가-힣]+(?:시|군|구)))[ \t]+"
    rf"(?P<dong>{_LEGAL_DONG_COMPONENT})[ \t]+"
    rf"(?P<anchor>(?:[가-힣][가-힣0-9]{{1,19}}로[ \t]*\d{{1,4}}(?:번)?길|"
    rf"[가-힣][가-힣0-9]{{1,19}}로\d+번길|"
    rf"[가-힣][가-힣0-9]{{1,29}}(?:대로|로|길)))"
    rf"[ \t]+\d{{1,5}}(?:-\d{{1,5}})?{_ROAD_BUILDING_NUMBER_MARKER}"
    rf"(?:[ \t]+{_ADDRESS_DETAIL_ATOM}){{1,5}}{_ADDRESS_VALUE_END}"
)
_PERSONAL_ADDRESS_CUE = re.compile(
    r"주소|거주지|배송지|수거지|수령지|보낼[ \t]*곳|받을[ \t]*곳|우편물|방문지"
)
_EXPLICIT_GENERAL_LOCATION = re.compile(
    r"공개[ \t]*행사|회의[ \t]*장소|교통[ \t]*통제|"
    r"공공[ \t]*(?:청사|시설|광장|주소[ \t]*표기[ \t]*예시)|개인[ \t]*주소가[ \t]*아니|"
    r"주소[ \t]*표기(?:(?![.!?\n]).){0,24}(?:예시|예로[ \t]*든)|"
    r"공공[ \t]*안내(?:(?![.!?\n]).){0,16}예시"
)
_EXPLICIT_PUBLIC_EVENT_TITLE = re.compile(
    r"(?:공개된|공공[ \t]*안내의?)[ \t]*(?:전시|행사)[ \t]*(?:이름|제목)"
    r"[ \t]*(?P<value>[^.!?\n]{1,48})"
)
_EXPLICIT_NON_USER_ID_CUE = re.compile(
    r"(?:제품|부품|장치|모델)[ \t]*(?:아이디|ID|번호)"
    r"(?:은|는|이|가)?[ \t]*[\"'‘“]?[ \t]*$",
    re.IGNORECASE,
)
_PERSON_IDENTITY_CUE = re.compile(
    r"이름|성명|신청인|고객|환자|담당자|소유자|운전자|대표|[가-힣]{2,5}(?:씨|님)"
)
_PERSON_FIELD_ROLE = (
    r"(?:신청인|담당자|책임자|소유자|운전자|고객|대표|검토자|접수자|승인자)"
)
_PERSON_FIELD_GAP = (
    r"[ \t]*(?:은|는|이|가|을|를|의)?[ \t]*"
    r"(?:(?::|：|=|\|)|(?:[-–—][ \t]*>))?[ \t]*"
    r"(?:[\(\[{'\"‘“][ \t]*)?"
    r"(?:\r?\n[ \t]*(?:값|기재값)[ \t]*(?::|：|=|\|)?[ \t]*)?"
)
_PERSON_NAMED_FIELD_GAP = (
    r"[ \t]*(?:은|는|이|가|을|를|의)?[ \t]*(?:"
    r"(?::|：|=|\|)[ \t]*(?:[\(\[{'\"‘“][ \t]*)?"
    r"|[\(\[{'\"‘“][ \t]*"
    r"|\r?\n[ \t]*(?:값|기재값)[ \t]*(?::|：|=|\|)?[ \t]*"
    r")"
)
_STRUCTURED_PERSON_PATTERNS = (
    re.compile(
        rf"(?P<cue>{_PERSON_FIELD_ROLE}[ \t]*(?:성명|이름))"
        rf"{_PERSON_NAMED_FIELD_GAP}(?P<value>[가-힣]{{2,6}}?){_VALUE_END}"
    ),
    re.compile(
        rf"(?P<cue>{_PERSON_FIELD_ROLE})[ \t]*(?::|：|=|\||\()[ \t]*"
        rf"(?:[\[{{'\"‘“][ \t]*)?(?P<value>[가-힣]{{2,6}}?){_VALUE_END}"
    ),
    re.compile(
        rf"(?P<cue>(?:개인[ \t]*기록(?:의)?[ \t]*)?(?:책임|담당)(?:을|지는)?[ \t]*"
        rf"(?:맡은|담당하는)[ \t]*사람){_PERSON_FIELD_GAP}"
        rf"(?P<value>[가-힣]{{2,6}}?){_VALUE_END}"
    ),
    re.compile(
        rf"(?P<value>(?<![가-힣])[가-힣]{{2,6}}?){_VALUE_END}"
        rf"[ \t]*(?:이라는|라는|이[ \t]*맡은)[ \t]*"
        rf"(?P<cue>{_PERSON_FIELD_ROLE}(?:[ \t]*(?:성명|이름))?)"
    ),
)
_STRICT_STRUCTURED_PERSON_PATTERNS = (
    _STRUCTURED_PERSON_PATTERNS[0],
    re.compile(
        rf"(?P<cue>{_PERSON_FIELD_ROLE})[ \t]*\([ \t]*"
        rf"(?P<value>[가-힣]{{2,6}}?){_VALUE_END}"
    ),
    re.compile(
        rf"(?P<cue>개인[ \t]*{_PERSON_FIELD_ROLE})[ \t]*(?::|：|=|\|)[ \t]*"
        rf"(?P<value>[가-힣]{{2,6}}?){_VALUE_END}"
    ),
)
_STRUCTURED_PERSON_NEGATIVE_LEFT = re.compile(
    r"(?:제품|부품|장치|모델|브랜드|프로그램|작품|공개[ \t]*행사|시설|조직|문서|표제)"
    r"(?:의|용|상)?[ \t]*(?:명|이름|제목)?[ \t]*(?::|：|=|\|)?[ \t]*$"
)
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
        rf"[ \t]*\d{{1,5}}(?:-\d{{1,5}})?{_ROAD_BUILDING_NUMBER_MARKER}{_ADDRESS_UNIT_SUFFIX}{_NO_UNCONSUMED_ADDRESS_UNIT}"
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

_EXTENDED_LOCATION_PATTERNS = (
    re.compile(
        rf"(?<![가-힣A-Za-z0-9])"
        rf"(?P<anchor>[가-힣][가-힣0-9]{{0,19}}(?:읍|면|동|리))"
        rf"[ \t]*(?:산[ \t]*)?\d{{1,5}}(?:-\d{{1,5}})?"
        rf"{_BUILDING_NAME}(?:{_EXTENDED_UNIT})?{_ROOM_NAME}{_ADDRESS_VALUE_END}"
    ),
    re.compile(
        rf"(?<![가-힣A-Za-z0-9])"
        rf"(?P<anchor>(?:[가-힣][가-힣0-9]{{1,19}}로[ \t]*\d{{1,4}}(?:번)?길|"
        rf"[가-힣][가-힣0-9]{{1,19}}로\d+번길|"
        rf"[가-힣][가-힣0-9]{{1,29}}(?:대로|로|길)))"
        rf"[ \t]*\d{{1,5}}(?:-\d{{1,5}})?{_ROAD_BUILDING_NUMBER_MARKER}"
        rf"{_BUILDING_NAME}(?:{_EXTENDED_UNIT})?{_ROOM_NAME}{_ADDRESS_VALUE_END}"
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


def structured_field_value_ranges(text: str) -> dict[str, list[tuple[int, int]]]:
    """Return exact, shape-valid values linked to bounded field names.

    The parser is intentionally relation-only: it does not itself create PII
    output.  A caller still needs overlapping model evidence or an explicitly
    gated field-window specialist.
    """

    output: dict[str, list[tuple[int, int]]] = {}
    for label, pattern in _STRUCTURED_FIELD_PATTERNS.items():
        ranges = set()
        for match in pattern.finditer(text):
            cue_start, _ = match.span("cue")
            if _EXPLICIT_NON_PERSONAL_FIELD.search(text[max(0, cue_start - 40):cue_start]):
                continue
            ranges.add(match.span("value"))
        output[label] = sorted(ranges)
    return output


def structured_person_value_ranges(text: str) -> list[tuple[int, int]]:
    """Return bounded Hangul values linked to an explicit personal role field.

    The relation parser never creates a PERSON span by itself. The pipeline
    requires overlapping evidence from a narrowly scoped specialist model.
    """

    ranges = set()
    for pattern in _STRUCTURED_PERSON_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span("value")
            cue_start, _ = match.span("cue")
            left = text[max(0, cue_start - 64):cue_start]
            if _STRUCTURED_PERSON_NEGATIVE_LEFT.search(left):
                continue
            ranges.add((start, end))
    return sorted(ranges)


def strict_structured_person_value_ranges(text: str) -> list[tuple[int, int]]:
    """Return only person fields strong enough for deterministic fallback."""

    ranges = set()
    for pattern in _STRICT_STRUCTURED_PERSON_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span("value")
            cue_start, _ = match.span("cue")
            left = text[max(0, cue_start - 64):cue_start]
            if _STRUCTURED_PERSON_NEGATIVE_LEFT.search(left):
                continue
            ranges.add((start, end))
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


def filter_official_place_person_homonyms(
    text: str,
    spans: list[Span],
    gazetteer: AddressGazetteer | None,
) -> list[Span]:
    """Reject a PERSON span that is an official place token in place context.

    This is deliberately narrow: the complete span must end in a Korean place
    suffix, exist in the configured official gazetteer, and lack a nearby person
    identity cue.  It does not alter PERSON predictions when no gazetteer is
    configured.
    """

    if gazetteer is None or not gazetteer.configured:
        return spans
    output = []
    for span in spans:
        if span.label != "PERSON":
            output.append(span)
            continue
        surface = text[span.start:span.end]
        if not surface.endswith(("로", "길", "동", "리", "읍", "면")):
            output.append(span)
            continue
        around = text[max(0, span.start - 32):min(len(text), span.end + 32)]
        if _PERSON_IDENTITY_CUE.search(around) or not gazetteer.contains(surface):
            output.append(span)
    return output


def filter_explicit_nonperson_titles(text: str, spans: list[Span]) -> list[Span]:
    """Reject PERSON spans inside explicitly public event/exhibit titles.

    This preserves the existing phone-number policy.  It changes only the
    semantic PERSON boundary: an event title is not a human name.
    """

    title_ranges = [
        match.span("value") for match in _EXPLICIT_PUBLIC_EVENT_TITLE.finditer(text)
    ]
    return [
        span for span in spans
        if not (
            span.label == "PERSON"
            and any(_overlaps(start, end, span) for start, end in title_ranges)
        )
    ]


def detailed_location_spans(
    text: str,
    spans: list[Span],
    gazetteer: AddressGazetteer | None = None,
) -> list[Span]:
    """Keep exact detailed-address shapes supported by a model span.

    This is deliberately not a nationwide legal-dong/road-name validator. It
    distinguishes a broad place from a location containing a lot/building/unit
    number, and never borrows a number from another model span or field.
    """

    detail_matches = []
    location_patterns = (
        _LONGEST_FULL_ROAD_LOCATION_PATTERN,
        _FULL_ROAD_LOCATION_PATTERN,
    ) + _EXTENDED_LOCATION_PATTERNS + _DETAILED_LOCATION_PATTERNS
    for pattern in location_patterns:
        for match in pattern.finditer(text):
            anchor_start, anchor_end = match.span("anchor")
            anchor = text[anchor_start:anchor_end].replace(" ", "")
            groups = match.groupdict()
            if groups.get("province"):
                dictionary_validated = bool(
                    gazetteer and gazetteer.configured
                    and gazetteer.contains_road_combination(
                        groups["province"], groups["district"], groups["dong"], anchor
                    )
                )
            else:
                dictionary_validated = bool(
                    gazetteer and gazetteer.configured and gazetteer.contains(anchor)
                )
            detail_matches.append((
                match.start(), match.end(), (anchor_start, anchor_end), dictionary_validated,
            ))

    output = [span for span in spans if span.label != "KR_LOCATION"]
    for span in spans:
        if span.label != "KR_LOCATION":
            continue
        around = text[max(0, span.start - 48):min(len(text), span.end + 48)]
        if _EXPLICIT_GENERAL_LOCATION.search(around):
            continue
        candidates = []
        for start, end, (anchor_start, anchor_end), dictionary_validated in detail_matches:
            # The model must cover the address/unit anchor itself.  Merely
            # finding a number elsewhere in the same sentence is insufficient.
            if not _overlaps(anchor_start, anchor_end, span):
                continue
            candidates.append((start, end, dictionary_validated))
        if candidates:
            start, end, dictionary_validated = max(
                candidates, key=lambda item: (item[1] - item[0], item[2])
            )
            metadata = dict(span.metadata)
            metadata.update({
                "location_model_span": (span.start, span.end),
                "location_boundary": "exact-detailed-address-shape",
                "location_detail_evidence": (start, end),
                "nationwide_dictionary_validated": dictionary_validated,
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

    # A nationwide-name match may add a detailed address only in an explicit
    # personal-address field.  Dictionary presence alone never masks a public
    # place, and dictionary absence never removes an existing model-positive.
    if gazetteer and gazetteer.configured:
        for start, end, (anchor_start, anchor_end), validated in detail_matches:
            if not validated or any(_overlaps(start, end, item) for item in output):
                continue
            around = text[max(0, start - 96):min(len(text), end + 96)]
            if _EXPLICIT_GENERAL_LOCATION.search(around):
                continue
            left = text[max(0, start - 64):start]
            if _PERSONAL_ADDRESS_CUE.search(left) is None:
                continue
            output.append(Span(
                label="KR_LOCATION", start=start, end=end,
                source="rule:official-address-gazetteer", score=1.0,
                native_label="KR_LOCATION",
                metadata={
                    "location_boundary": "official-name-plus-number-with-personal-cue",
                    "location_detail_evidence": (start, end),
                    "nationwide_dictionary_validated": True,
                },
            ))
    return output


def linked_date_of_birth_spans(text: str, spans: list[Span]) -> list[Span]:
    """Keep/expand Frame DOB spans only when tied to a DOB field or phrase."""

    values = sorted(set(
        _linked_value_ranges(text, _DOB_VALUE_PATTERNS)
        + structured_field_value_ranges(text)["DATE_OF_BIRTH"]
    ))
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

    values = sorted(set(
        _linked_value_ranges(text, _ACCOUNT_VALUE_PATTERNS)
        + structured_field_value_ranges(text)["KR_BANK_ACCOUNT"]
    ))
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

    values = [
        (start, end) for start, end in sorted(set(
            _linked_value_ranges(text, _USERNAME_VALUE_PATTERNS)
            + structured_field_value_ranges(text)["USERNAME"]
        ))
        if _EXPLICIT_NON_USER_ID_CUE.search(text[max(0, start - 32):start]) is None
    ]
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


def context_validated_repeated_identifier_spans(text: str, spans: list[Span]) -> list[Span]:
    """Propagate only to an occurrence with its own reconfirmation context.

    String equality alone is insufficient.  The source occurrence must already
    have survived the precision policy, the second occurrence must be preceded
    by a reconfirmation relation, and explicit product/logistics context blocks
    propagation.
    """

    output = list(spans)
    existing = {(span.label, span.start, span.end) for span in spans}
    for source in spans:
        if source.label not in {"USERNAME", "KR_BANK_ACCOUNT"}:
            continue
        value = text[source.start:source.end]
        if source.label == "USERNAME":
            if re.fullmatch(_USERNAME_VALUE, value, re.IGNORECASE) is None:
                continue
        elif re.fullmatch(_ACCOUNT_DIGITS, value) is None:
            continue
        for match in re.finditer(re.escape(value), text):
            key = (source.label, match.start(), match.end())
            if key in existing:
                continue
            left = text[max(0, match.start() - 72):match.start()]
            around = text[max(0, match.start() - 48):min(len(text), match.end() + 48)]
            if _RECONFIRMATION_CUE.search(left) is None or _REPEAT_NEGATIVE_CONTEXT.search(around):
                continue
            metadata = dict(source.metadata)
            metadata.update({
                "repeat_source_span": (source.start, source.end),
                "precision_boundary": "occurrence-specific-reconfirmation",
            })
            output.append(Span(
                label=source.label,
                start=match.start(),
                end=match.end(),
                source="rule:context-validated-repeat",
                score=source.score,
                native_label=source.native_label,
                metadata=metadata,
            ))
            existing.add(key)
    return output


def apply_precision_policy(
    text: str,
    spans: list[Span],
    gazetteer: AddressGazetteer | None = None,
) -> list[Span]:
    spans = filter_explicit_nonperson_titles(text, spans)
    spans = detailed_location_spans(text, spans, gazetteer)
    spans = linked_date_of_birth_spans(text, spans)
    spans = linked_account_spans(text, spans)
    spans = linked_username_spans(text, spans)
    spans = linked_driver_license_spans(text, spans)
    spans = linked_vehicle_plate_spans(text, spans)
    return context_validated_repeated_identifier_spans(text, spans)
