"""Production hybrid PII detector assembly."""

from __future__ import annotations

from .candidates import build_windows, precise_driver_spans
from .errors import DetectionError, PIIError
from .merge import deduplicate
from .pipeline import KoreanPII as BaseKoreanPII
from .postprocess import filter_official_place_person_homonyms
from .router import accept

from .precision_policy import apply_hybrid_precision_policy


def _overlaps(a: int, b: int, c: int, d: int) -> bool:
    return a < d and c < b


class KoreanPII(BaseKoreanPII):
    """Hybrid detector exposed through the normal library API."""

    @property
    def status(self) -> dict:
        value = dict(super().status)
        value["pipeline_profile"] = "hybrid-long-document-guardrails"
        return value

    def detect(self, text: str):
        if not isinstance(text, str):
            raise DetectionError("detect expects str input")
        if len(text) > self.policy.runtime["max_text_chars"]:
            raise DetectionError("input exceeds configured max_text_chars")
        try:
            frame = self.models.get("frame").predict(text)
            frame = self.kiwi.normalize_people(text, frame)
            frame = filter_official_place_person_homonyms(
                text, frame, self.address_gazetteer
            )
            frame_people = [span for span in frame if span.label == "PERSON"]
            frame_labels = set(self.policy.direct["frame_labels"]) | {"KR_BANK_ACCOUNT"}
            frame_direct = [span for span in frame if span.label in frame_labels]

            koredact = self.models.get("koredact").predict(text)
            atonlee = self.models.get("atonlee").predict(text)
            seongyeon = self.models.get("seongyeon").predict(text)
            assigned = [span for span in koredact if span.label == "KR_LOCATION"]
            assigned.extend(
                span for span in atonlee
                if (
                    span.label == "KR_BANK_ACCOUNT"
                    and span.score is not None and span.score >= 0.50
                ) or (
                    span.label == "KR_PASSPORT"
                    and span.score is not None and span.score >= 0.90
                )
            )
            assigned.extend(
                span for span in seongyeon
                if span.label in {"KR_DRIVER_LICENSE", "KR_VEHICLE_PLATE"}
            )
            full_people = [
                span for span in seongyeon
                if span.label == "PERSON"
                and span.score is not None and span.score >= 0.70
                and not any(
                    _overlaps(span.start, span.end, base.start, base.end)
                    for base in frame_people
                )
            ]

            passport_window = []
            windows = build_windows(text, frame, self.policy)
            for window in windows.get("atonlee", []):
                if "KR_PASSPORT" not in window.allowed_labels:
                    continue
                raw = self.models.get("atonlee").predict(
                    text[window.start:window.end], absolute_offset=window.start,
                )
                passport_window.extend(
                    span for span in raw
                    if span.label == "KR_PASSPORT" and accept(span, window, self.policy)
                )

            direct = self.nhis_verifier.filter(text, self.rules.detect(text))
            bypass = precise_driver_spans(text)
            fields = self._structured_field_specialists(text, frame)
            people = self._structured_person_specialists(
                text, frame_people + full_people
            )
            pre = (
                frame_people + frame_direct + assigned + full_people
                + passport_window + direct + bypass + fields + people
            )
            processed = apply_hybrid_precision_policy(self, text, pre)
            return tuple(deduplicate(processed, self.policy))
        except DetectionError:
            raise
        except PIIError as exc:
            raise DetectionError(
                f"detection failed closed: {type(exc).__name__}"
            ) from exc
        except Exception as exc:
            raise DetectionError(
                f"detection failed closed: {type(exc).__name__}"
            ) from exc
