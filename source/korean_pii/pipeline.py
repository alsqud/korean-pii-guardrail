from __future__ import annotations

import os
from pathlib import Path

from .adapters import ModelRegistry
from .candidates import build_windows, precise_driver_spans
from .config import Policy, load_default_policy, load_policy
from .direct_rules import DirectRuleAdapter
from .errors import DetectionError, PIIError
from .kiwi import KiwiBoundaryNormalizer
from .merge import deduplicate, mask_text, outside_existing_mask_tokens
from .nhis_verifier import NHISCandidateVerifier
from .postprocess import apply_precision_policy
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
            frame_people = [span for span in normalized_frontend if span.label == "PERSON"]
            direct_frame = [span for span in normalized_frontend if span.label in set(self.policy.direct["frame_labels"])]

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
            spans = frame_people + direct_frame + filtered_experts + direct + bypass
            spans = self.kiwi.filter_people_context(text, spans)
            spans = outside_existing_mask_tokens(text, spans, self.policy)
            return tuple(deduplicate(apply_precision_policy(text, spans), self.policy))
        except DetectionError:
            raise
        except PIIError as exc:
            raise DetectionError(f"detection failed closed: {type(exc).__name__}") from exc
        except Exception as exc:
            # No input text is included in the error message.
            raise DetectionError(f"detection failed closed: {type(exc).__name__}") from exc

    def mask(self, text: str, spans: tuple[Span, ...] | list[Span] | None = None) -> str:
        detected = list(self.detect(text) if spans is None else spans)
        return mask_text(text, detected, self.policy)
