from __future__ import annotations

import re
import threading

from .config import Policy
from .errors import DetectionError
from .types import Span


KO_MAP = {
    "PHONE": "KR_PHONE_NUMBER", "EMAIL": "EMAIL_ADDRESS", "IP": "IP_ADDRESS",
}
IPV4_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![A-Za-z0-9.])"
)
ASCII_IDENTIFIER_PREFIX = re.compile(
    r"(?<![A-Za-z0-9_])(?P<prefix>[A-Za-z][A-Za-z0-9_]{1,31})-$"
)
EXPLICIT_RRN_CONTEXT = re.compile(
    r"(?:주민[ \t]*등록[ \t]*번호|주민[ \t]*번호|주민[ \t]*등록|외국인[ \t]*등록[ \t]*번호|RRN)",
    re.IGNORECASE,
)
EXPLICIT_RRN_LINKER = re.compile(
    r"[ \t]*(?:은|는|이|가)?[ \t]*(?::|：|=)?[ \t]*$"
)


def _rrn_is_embedded_ascii_identifier(text: str, start: int) -> bool:
    """Reject an RRN shape embedded in a generic ASCII identifier.

    Presidio intentionally recognizes the numeric RRN shape inside values such
    as ``ORDER-900101-1234568``.  A directly attached ASCII identifier prefix
    makes that substring non-standalone, unless the same field explicitly says
    it is an RRN.  This is a boundary/context rule; it does not depend on a
    particular order-code literal.
    """

    left = text[max(0, start - 64):start]
    prefix = ASCII_IDENTIFIER_PREFIX.search(left)
    if prefix is None:
        return False
    before_prefix = left[:prefix.start()]
    cues = list(EXPLICIT_RRN_CONTEXT.finditer(before_prefix))
    if not cues:
        return True
    # A cue from an earlier field must not leak across intervening values or
    # field names.  Only a direct grammatical linker to the ASCII prefix is
    # treated as explicit RRN context.
    return EXPLICIT_RRN_LINKER.fullmatch(before_prefix[cues[-1].end():]) is None


def _strict_ipv4_spans(text: str) -> list[Span]:
    output = []
    for match in IPV4_CANDIDATE.finditer(text):
        if all(int(part) <= 255 for part in match.group().split(".")):
            output.append(Span(
                label="IP_ADDRESS", start=match.start(), end=match.end(),
                source="rule:ipv4-strict", score=1.0, native_label="IPV4",
                metadata={"validation": "four decimal octets, each 0..255"},
            ))
    return output


class DirectRuleAdapter:
    def __init__(self, policy: Policy):
        self.policy = policy
        self._ko = None
        self._presidio = None
        self._lock = threading.RLock()

    @property
    def loaded(self) -> bool:
        return self._ko is not None and self._presidio is not None

    def load(self) -> None:
        with self._lock:
            if self.loaded:
                return
            try:
                from ko_pii import Anonymizer, ProcessingMode
                from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
                from presidio_analyzer.nlp_engine import NoOpNlpEngine
                from presidio_analyzer.predefined_recognizers import KrRrnRecognizer
                ko = Anonymizer(mode=ProcessingMode.AUDIT)
                nlp = NoOpNlpEngine(models=[{"lang_code": "ko", "model_name": "none"}])
                registry = RecognizerRegistry(supported_languages=["ko"])
                registry.add_recognizer(KrRrnRecognizer(supported_language="ko"))
                presidio = AnalyzerEngine(registry=registry, nlp_engine=nlp, supported_languages=["ko"])
            except Exception as exc:
                raise DetectionError(f"direct rule initialization failed: {type(exc).__name__}") from exc
            self._ko, self._presidio = ko, presidio

    def detect(self, text: str) -> list[Span]:
        self.load()
        output = []
        allowed_ko = set(self.policy.direct["ko_pii_labels"])
        allowed_presidio = set(self.policy.direct["presidio_labels"])
        try:
            with self._lock:
                ko_items = self._ko.process(text).detections
                rrn_items = self._presidio.analyze(text=text, language="ko", entities=["KR_RRN"], score_threshold=0.0)
            for item in ko_items:
                detection = item.detection
                label = KO_MAP.get(detection.label)
                if label in allowed_ko:
                    output.append(Span(
                        label=label, start=int(detection.start), end=int(detection.end),
                        source="rule:ko-pii", score=float(detection.confidence),
                        native_label=detection.label,
                        metadata={"score_semantics": "detector raw score; not calibrated"},
                    ))
            for item in rrn_items:
                if item.entity_type in allowed_presidio:
                    start, end = int(item.start), int(item.end)
                    if _rrn_is_embedded_ascii_identifier(text, start):
                        continue
                    output.append(Span(
                        label=item.entity_type, start=start, end=end,
                        source="rule:presidio", score=float(item.score), native_label=item.entity_type,
                        metadata={"score_semantics": "detector raw score; not calibrated"},
                    ))
            # The package keeps NHIS enabled by default, while a deployment
            # may exclude it through the ordinary per-type policy switch.
            # The direct candidate generator must honor that switch; otherwise
            # types.KR_NHIS.enabled=false would be misleading.
            nhis_policy = self.policy.types.get("KR_NHIS")
            if self.policy.direct["enable_nhis_shape"] and nhis_policy is not None and nhis_policy.enabled:
                for match in re.finditer(r"(?<!\d)\d{11}(?!\d)", text):
                    output.append(Span(
                        label="KR_NHIS", start=match.start(), end=match.end(),
                        source="rule:nhis-shape", score=1.0, native_label="KR_NHIS",
                    ))
            if "IP_ADDRESS" in allowed_ko:
                output.extend(_strict_ipv4_spans(text))
        except DetectionError:
            raise
        except Exception as exc:
            raise DetectionError(f"direct rule detection failed: {type(exc).__name__}") from exc
        return output
