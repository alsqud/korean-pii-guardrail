from __future__ import annotations

import os
from pathlib import Path

from .adapters import ModelRegistry
from .candidates import build_windows, precise_driver_spans
from .config import Policy, load_default_policy, load_policy
from .direct_rules import DirectRuleAdapter
from .errors import DetectionError, PIIError
from .gazetteer import AddressGazetteer
from .kiwi import KiwiBoundaryNormalizer
from .merge import deduplicate, mask_text, outside_existing_mask_tokens
from .nhis_verifier import NHISCandidateVerifier
from .postprocess import (
    apply_precision_policy,
    filter_official_place_person_homonyms,
    strict_structured_person_value_ranges,
    structured_field_value_ranges,
    structured_person_value_ranges,
)
from .router import route_expert_predictions
from .types import Span


class KoreanPII:
    """Reusable, fail-closed Korean PII detector.

    Construction is cheap. Models, Kiwi, ko-pii, and Presidio initialize on the
    first detect call and remain cached on this instance.
    """

    def __init__(self, config_path: str | Path | None = None):
        selected_config = config_path or os.getenv("KOREAN_PII_CONFIG")
        self.policy: Policy = load_policy(selected_config) if selected_config else load_default_policy()
        device = os.getenv(self.policy.runtime["device_env"], self.policy.runtime["device_default"])
        if not (device in {"cpu", "cuda"} or device.startswith("cuda:")):
            raise DetectionError("invalid device selection; use cpu, cuda, or cuda:<index>")
        self.device = device
        self.models = ModelRegistry(self.policy, device)
        self.kiwi = KiwiBoundaryNormalizer(self.policy)
        self.rules = DirectRuleAdapter(self.policy)
        self.nhis_verifier = NHISCandidateVerifier(device)
        self.address_gazetteer = AddressGazetteer.from_environment()

    @property
    def status(self) -> dict:
        return {
            "policy_version": self.policy.policy_version,
            "policy_sha256": self.policy.sha256,
            "device": self.device,
            "loaded_models": self.models.loaded_models,
            "kiwi_loaded": self.kiwi.loaded,
            "direct_rules_loaded": self.rules.loaded,
            "nhis_candidate_verifier": self.nhis_verifier.status,
            "address_gazetteer": self.address_gazetteer.status,
            "unsupported": self.policy.unsupported,
        }

    def detect(self, text: str) -> tuple[Span, ...]:
        if not isinstance(text, str):
            raise DetectionError("detect expects str input")
        if len(text) > self.policy.runtime["max_text_chars"]:
            raise DetectionError("input exceeds configured max_text_chars")
        try:
            # Frontend spans are retained for routing. Kiwi changes only PERSON
            # boundaries in the returned base-person spans; source text is never changed.
            frontend = self.models.get("frame").predict(text)
            normalized_frontend = self.kiwi.normalize_people(text, frontend)
            normalized_frontend = filter_official_place_person_homonyms(
                text, normalized_frontend, self.address_gazetteer
            )
            frame_people = [span for span in normalized_frontend if span.label == "PERSON"]
            # Frame account predictions are retained only as precision-policy
            # candidates. They must still overlap a tightly linked account
            # value pattern before they can reach the final output.
            precision_frontend_labels = set(self.policy.direct["frame_labels"]) | {"KR_BANK_ACCOUNT"}
            direct_frame = [span for span in normalized_frontend if span.label in precision_frontend_labels]

            # Build expert windows from the normalized frontend so a rejected
            # partial Hangul PERSON cannot be reintroduced by the expert model.
            windows = build_windows(text, normalized_frontend, self.policy)
            experts = route_expert_predictions(text, windows, self.policy, self.models)
            # Seongyeon is augmentation-only for names already covered by Frame+Kiwi.
            filtered_experts = []
            for span in experts:
                if span.label == "PERSON" and any(span.start < base.end and base.start < span.end for base in frame_people):
                    continue
                filtered_experts.append(span)

            direct = self.nhis_verifier.filter(text, self.rules.detect(text))
            bypass = precise_driver_spans(text)
            field_specialists = self._structured_field_specialists(
                text, normalized_frontend
            )
            person_specialists = self._structured_person_specialists(
                text, frame_people + filtered_experts
            )
            spans = (
                frame_people + direct_frame + filtered_experts + direct + bypass
                + field_specialists + person_specialists
            )
            spans = self.kiwi.filter_people_context(text, spans)
            spans = outside_existing_mask_tokens(text, spans, self.policy)
            return tuple(deduplicate(
                apply_precision_policy(text, spans, self.address_gazetteer), self.policy
            ))
        except DetectionError:
            raise
        except PIIError as exc:
            raise DetectionError(f"detection failed closed: {type(exc).__name__}") from exc
        except Exception as exc:
            # No input text is included in the error message.
            raise DetectionError(f"detection failed closed: {type(exc).__name__}") from exc

    def _structured_field_specialists(
        self,
        text: str,
        frontend: list[Span],
    ) -> list[Span]:
        """Run a specialist only inside an explicit, shape-valid field window."""

        links = structured_field_value_ranges(text)
        model_by_label = {
            "DATE_OF_BIRTH": "seongyeon",
            "USERNAME": "atonlee",
        }
        output = []
        for label, model_name in model_by_label.items():
            for start, end in links[label]:
                if any(
                    span.label == label and span.start < end and start < span.end
                    for span in frontend
                ):
                    continue
                window_start = max(0, start - 48)
                window_end = min(len(text), end + 48)
                predictions = self.models.get(model_name).predict(
                    text[window_start:window_end], absolute_offset=window_start
                )
                agreeing = [
                    span for span in predictions
                    if span.label == label and span.start < end and start < span.end
                ]
                if not agreeing:
                    continue
                best = max(
                    agreeing,
                    key=lambda span: (
                        min(span.end, end) - max(span.start, start),
                        span.score if span.score is not None else -1.0,
                    ),
                )
                metadata = dict(best.metadata)
                metadata.update({
                    "specialist_model_span": (best.start, best.end),
                    "structured_field_value": (start, end),
                    "specialist_scope": "explicit-shape-valid-field-window",
                })
                output.append(Span(
                    label=label,
                    start=start,
                    end=end,
                    source=f"model:{model_name}:structured-field-window",
                    score=best.score,
                    native_label=best.native_label,
                    metadata=metadata,
                ))
        return output

    def _structured_person_specialists(
        self,
        text: str,
        existing_people: list[Span],
    ) -> list[Span]:
        """Recover an explicit personal-role value with local model evidence."""

        output = []
        strict_ranges = set(strict_structured_person_value_ranges(text))
        for start, end in structured_person_value_ranges(text):
            if any(
                span.label == "PERSON" and span.start == start and span.end == end
                for span in existing_people
            ):
                continue
            window_start = max(0, start - 128)
            window_end = min(len(text), end + 128)
            predictions = self.models.get("atonlee").predict(
                text[window_start:window_end], absolute_offset=window_start
            )
            agreeing = [
                span for span in predictions
                if span.label == "PERSON" and span.start < end and start < span.end
            ]
            if agreeing:
                best = max(
                    agreeing,
                    key=lambda span: (
                        min(span.end, end) - max(span.start, start),
                        span.score if span.score is not None else -1.0,
                    ),
                )
                metadata = dict(best.metadata)
                metadata.update({
                    "specialist_model_span": (best.start, best.end),
                    "structured_person_value": (start, end),
                    "specialist_scope": "explicit-person-role-field-window",
                })
                output.append(Span(
                    label="PERSON",
                    start=start,
                    end=end,
                    source="model:atonlee:structured-person-window",
                    score=best.score,
                    native_label=best.native_label,
                    metadata=metadata,
                ))
            elif (start, end) in strict_ranges:
                output.append(Span(
                    label="PERSON",
                    start=start,
                    end=end,
                    source="rule:explicit-person-role-field",
                    score=1.0,
                    native_label="PERSON",
                    metadata={
                        "structured_person_value": (start, end),
                        "specialist_scope": "strict-explicit-person-role-field",
                    },
                ))
        return output

    def mask(self, text: str, spans: tuple[Span, ...] | list[Span] | None = None) -> str:
        detected = list(self.detect(text) if spans is None else spans)
        return mask_text(text, detected, self.policy)
