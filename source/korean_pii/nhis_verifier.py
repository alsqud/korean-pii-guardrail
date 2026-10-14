from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from pathlib import Path

from .errors import DetectionError
from .types import Span


ADAPTER_SHA256 = "686c5301a2c446d187fdca12c117cf64cf4dce01fd7d10ff930b5b3b4c11c55e"
BASE_MODEL_ID = "seongyeon1/ko-pii-ner-roberta-base"
BASE_REVISION = "95a3af685dccf4bb3f7fff6fc81146fed71500bb"
THRESHOLD = 0.98
CONTEXT_CHARS = 24
MAX_LENGTH = 128
LINK_POLICY = "explicit-insurance-field-required"

_FIELD_LINKER = r"[ \t]*(?:은|는|이|가|을|를|의|로|으로)?[ \t]*(?::|：|=|\|)?[ \t]*"
_VALUE = r"(?P<value>(?<!\d)\d{11}(?!\d))"
_HEALTH_KIND = (
    r"(?:건보|건강[ \t]*보험|국민[ \t]*건강[ \t]*보험|"
    r"건강[ \t]*보장|의료[ \t]*보장)"
)
_HEALTH_DOCUMENT = r"(?:보험증|자격[ \t]*증서|자격증|증서|서류)"
_IDENTIFIER_FIELD = (
    r"(?:문서[ \t]*번호|증서[ \t]*번호|발행[ \t]*번호|"
    r"식별[ \t]*(?:번호|숫자)|번호)"
)
_NHIS_FIELD_VALUE_PATTERNS = (
    re.compile(
        rf"(?P<field>(?:건강[ \t]*보험증?|건보)(?:[ \t]*(?:자격|가입자))?"
        rf"[ \t]*(?:번호|식별[ \t]*번호))"
        rf"{_FIELD_LINKER}{_VALUE}"
    ),
    re.compile(
        rf"(?P<field>(?:문서[ \t]*[A-Za-z가-힣0-9]+[ \t]*)?보험증)"
        rf"{_FIELD_LINKER}{_VALUE}"
    ),
    # Explicit insurance document followed by its identifier field and value.
    # The bounded middle permits ordinary Korean particles/descriptions but
    # cannot cross a sentence or line.
    re.compile(
        rf"(?P<field>(?:{_HEALTH_KIND}[ \t]*{_HEALTH_DOCUMENT}|"
        rf"가입자[ \t]*보험증|(?:문서[ \t]*[A-Za-z가-힣0-9]+[ \t]*)?보험증)"
        rf"[^.!?\n]{{0,24}}?{_IDENTIFIER_FIELD})"
        rf"{_FIELD_LINKER}{_VALUE}"
    ),
    # Value-first records such as “...는 의료보장 자격증에 적힌 증서 번호”.
    re.compile(
        rf"{_VALUE}{_FIELD_LINKER}"
        rf"(?P<field>{_HEALTH_KIND}[ \t]*{_HEALTH_DOCUMENT}"
        rf"[^.!?\n]{{0,24}}?{_IDENTIFIER_FIELD})"
    ),
    # A generic record-number field is accepted only when the same bounded
    # record explicitly declares a national/health-insurance document kind.
    re.compile(
        rf"(?P<field>(?:자격[ \t]*확인[ \t]*)?문서[ \t]*번호|번호)"
        rf"{_FIELD_LINKER}{_VALUE}[^.!?\n]{{0,36}}?"
        rf"(?:서류|문서)[ \t]*종류(?:은|는)?[ \t]*(?::|：|=)?[ \t]*"
        rf"{_HEALTH_KIND}[ \t]*{_HEALTH_DOCUMENT}"
    ),
)
_NON_NHIS_FIELD_VALUE_PATTERNS = (
    re.compile(
        rf"(?P<field>(?:(?:택배|화물|배송|물류)[ \t]*)?(?:운송장|송장)"
        rf"[ \t]*(?:번호|추적[ \t]*번호)?|"
        rf"(?:주문|배송|화물)[ \t]*(?:번호|관리[ \t]*번호|추적[ \t]*번호))"
        rf"{_FIELD_LINKER}{_VALUE}"
    ),
    re.compile(
        rf"(?P<field>(?:(?:화물|택배|배송|물류|소포|반송)[ \t]*)?"
        rf"(?:위치[ \t]*키|배달[ \t]*조회[ \t]*값|라벨[ \t]*일련[ \t]*값|"
        rf"(?:상자|박스)[ \t]*(?:코드|번호|식별[ \t]*값)))"
        rf"{_FIELD_LINKER}{_VALUE}"
    ),
    re.compile(
        rf"{_VALUE}{_FIELD_LINKER}"
        rf"(?P<field>(?:(?:화물|택배|배송|물류|소포|반송)[ \t]*)?"
        rf"(?:위치[ \t]*키|배달[ \t]*조회[ \t]*값|라벨[ \t]*일련[ \t]*값|"
        rf"(?:상자|박스)[ \t]*(?:코드|번호|식별[ \t]*값)))"
    ),
)
_NON_NHIS_PATIENT_FIELD_VALUE_PATTERNS = (
    re.compile(
        rf"(?P<field>(?:환자|진료|차트|접수)[ \t]*"
        rf"(?:번호|식별[ \t]*번호|ID))"
        rf"{_FIELD_LINKER}{_VALUE}",
        re.IGNORECASE,
    ),
)


def _candidate_field_links(text: str) -> dict[tuple[int, int], dict]:
    """Return direct field-to-value links keyed by the exact 11-digit span.

    A nearby word is not enough.  The field phrase, optional grammatical
    linker, and value must be one contiguous match.  Under the precision-first
    policy, a direct non-NHIS field wins if a broader insurance expression
    also reaches the same value; remaining conflicting links are ambiguous.
    """

    found: dict[tuple[int, int], list[dict]] = {}
    groups = (
        ("nhis", _NHIS_FIELD_VALUE_PATTERNS),
        ("non_nhis_logistics", _NON_NHIS_FIELD_VALUE_PATTERNS),
        ("non_nhis_patient", _NON_NHIS_PATIENT_FIELD_VALUE_PATTERNS),
    )
    for kind, patterns in groups:
        for pattern in patterns:
            for match in pattern.finditer(text):
                key = match.span("value")
                found.setdefault(key, []).append({
                    "kind": kind,
                    "field_range": list(match.span("field")),
                    "field_text": match.group("field"),
                    "value_range": list(key),
                })
    output = {}
    for key, links in found.items():
        kinds = {item["kind"] for item in links}
        non_nhis = [item for item in links if item["kind"].startswith("non_nhis_")]
        if non_nhis:
            # Prefer the directly adjacent/specific non-NHIS field.  This is a
            # precision decision, not a numeric-value exception.
            output[key] = min(
                non_nhis,
                key=lambda item: (
                    key[0] - item["field_range"][1]
                    if item["field_range"][1] <= key[0]
                    else item["field_range"][0] - key[1],
                    item["field_range"][1] - item["field_range"][0],
                ),
            )
        elif len(kinds) == 1:
            output[key] = links[0]
        else:
            output[key] = {
                "kind": "ambiguous",
                "links": links,
                "value_range": list(key),
            }
    return output


class NHISCandidateVerifier:
    """Frozen candidate classifier for direct 11-digit KR_NHIS shape spans.

    This component never creates candidates. It only keeps or rejects spans
    already produced by ``rule:nhis-shape`` and preserves their original
    source offsets. Scores are raw sigmoid outputs, not calibrated
    probabilities.
    """

    def __init__(self, device: str):
        self.device = device
        model_value = os.getenv("KOREAN_PII_NHIS_VERIFIER_MODEL")
        adapter_value = os.getenv("KOREAN_PII_NHIS_VERIFIER_ADAPTER")
        self.model_path = Path(model_value) if model_value else None
        self.adapter_path = Path(adapter_value) if adapter_value else None
        self._tokenizer = None
        self._model = None
        self._lock = threading.RLock()
        self.last_trace: tuple[dict, ...] = ()
        self.last_inference_ms = 0.0

    @property
    def loaded(self) -> bool:
        return self._tokenizer is not None and self._model is not None

    @property
    def status(self) -> dict:
        return {
            "loaded": self.loaded,
            "threshold": THRESHOLD,
            "context_chars": CONTEXT_CHARS,
            "base_model_id": BASE_MODEL_ID,
            "base_revision": BASE_REVISION,
            "adapter_sha256": ADAPTER_SHA256,
            "score_semantics": "raw sigmoid; not calibrated probability",
            "link_policy": LINK_POLICY,
        }

    def load(self) -> None:
        with self._lock:
            if self.loaded:
                return
            if self.model_path is None or not self.model_path.is_dir():
                raise DetectionError("NHIS verifier local model path is missing")
            if self.adapter_path is None or not self.adapter_path.is_file():
                raise DetectionError("NHIS verifier adapter path is missing")
            actual = hashlib.sha256(self.adapter_path.read_bytes()).hexdigest()
            if actual != ADAPTER_SHA256:
                raise DetectionError("NHIS verifier adapter hash mismatch")
            try:
                import torch
                from safetensors.torch import load_file
                from torch import nn
                from transformers import AutoModel, AutoTokenizer

                class LoRALinear(nn.Module):
                    def __init__(self, base: nn.Linear, rank: int = 8, alpha: int = 16, dropout: float = 0.05):
                        super().__init__()
                        self.base = base
                        self.base.weight.requires_grad = False
                        if self.base.bias is not None:
                            self.base.bias.requires_grad = False
                        self.lora_a = nn.Linear(base.in_features, rank, bias=False)
                        self.lora_b = nn.Linear(rank, base.out_features, bias=False)
                        nn.init.kaiming_uniform_(self.lora_a.weight, a=math.sqrt(5))
                        nn.init.zeros_(self.lora_b.weight)
                        self.dropout = nn.Dropout(dropout)
                        self.scale = alpha / rank

                    def forward(self, value):
                        return self.base(value) + self.lora_b(self.lora_a(self.dropout(value))) * self.scale

                class FrozenVerifier(nn.Module):
                    def __init__(self, model_path: Path):
                        super().__init__()
                        self.base = AutoModel.from_pretrained(
                            model_path, local_files_only=True, trust_remote_code=False, use_safetensors=True,
                        )
                        for parameter in self.base.parameters():
                            parameter.requires_grad = False
                        targets = []
                        for name, module in list(self.base.named_modules()):
                            if not isinstance(module, nn.Linear):
                                continue
                            if not (name.endswith("attention.self.query") or name.endswith("attention.self.value")):
                                continue
                            parent_name, child_name = name.rsplit(".", 1)
                            parent = self.base.get_submodule(parent_name)
                            setattr(parent, child_name, LoRALinear(module))
                            targets.append(name)
                        if len(targets) != 24:
                            raise DetectionError("NHIS verifier expected 24 LoRA query/value targets")
                        self.classifier = nn.Sequential(nn.Dropout(0.1), nn.Linear(self.base.config.hidden_size, 1))

                    def forward(self, input_ids, attention_mask, token_type_ids=None):
                        kwargs = {"input_ids": input_ids, "attention_mask": attention_mask}
                        if token_type_ids is not None:
                            kwargs["token_type_ids"] = token_type_ids
                        hidden = self.base(**kwargs).last_hidden_state
                        mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
                        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)
                        return self.classifier(pooled).squeeze(-1)

                tokenizer = AutoTokenizer.from_pretrained(
                    self.model_path, local_files_only=True, trust_remote_code=False,
                )
                model = FrozenVerifier(self.model_path)
                state = load_file(str(self.adapter_path))
                missing, unexpected = model.load_state_dict(state, strict=False)
                expected_missing = sorted(name for name, _ in model.named_parameters() if not (
                    "classifier" in name or "lora_a" in name or "lora_b" in name
                ))
                if sorted(missing) != expected_missing or unexpected:
                    raise DetectionError("NHIS verifier adapter state does not match frozen architecture")
                model.to(torch.device(self.device))
                model.eval()
            except DetectionError:
                raise
            except Exception as exc:
                raise DetectionError(f"NHIS verifier initialization failed: {type(exc).__name__}") from exc
            self._tokenizer, self._model = tokenizer, model

    @staticmethod
    def _model_input(text: str, span: Span) -> tuple[str, int, int]:
        window_start = max(0, span.start - CONTEXT_CHARS)
        window_end = min(len(text), span.end + CONTEXT_CHARS)
        window = text[window_start:window_end]
        local_start = span.start - window_start
        local_end = span.end - window_start
        left, candidate, right = window[:local_start], window[local_start:local_end], window[local_end:]
        value = (
            f"검증유형: 건강보험증번호. 앞문맥: {left} "
            f"후보시작 {candidate} 후보끝. 뒷문맥: {right}"
        )
        return value, window_start, window_end

    def filter(self, text: str, spans: list[Span]) -> list[Span]:
        candidates = [span for span in spans if span.label == "KR_NHIS" and span.source == "rule:nhis-shape"]
        if not candidates:
            self.last_trace = ()
            self.last_inference_ms = 0.0
            return spans
        links = _candidate_field_links(text)
        # Precision-first policy: the frozen classifier may confirm an
        # explicitly linked insurance identifier, but it may not promote an
        # unlinked 11-digit number merely because insurance words occur nearby.
        model_candidates = [
            span for span in candidates
            if links.get((span.start, span.end), {}).get("kind") == "nhis"
        ]
        if not model_candidates:
            trace = []
            for span in candidates:
                link = links.get((span.start, span.end))
                kind = None if link is None else link.get("kind")
                if kind and kind.startswith("non_nhis_"):
                    decision = "rejected_direct_non_nhis_field_link"
                elif kind == "ambiguous":
                    decision = "rejected_ambiguous_field_link"
                else:
                    decision = "rejected_unlinked_precision_policy"
                trace.append({
                    "start": span.start,
                    "end": span.end,
                    "window_start": None,
                    "window_end": None,
                    "raw_score": None,
                    "threshold": THRESHOLD,
                    "accepted": False,
                    "decision": decision,
                    "field_link": link,
                })
            self.last_trace = tuple(trace)
            self.last_inference_ms = 0.0
            return [span for span in spans if span not in candidates]
        self.load()
        try:
            import torch

            prepared = [self._model_input(text, span) for span in model_candidates]
            encoded = self._tokenizer(
                [item[0] for item in prepared], max_length=MAX_LENGTH, truncation=True,
                padding=True, return_tensors="pt",
            )
            inputs = {key: value.to(self.device) for key, value in encoded.items()}
            if str(self.device).startswith("cuda"):
                torch.cuda.synchronize(torch.device(self.device))
            started = time.perf_counter()
            with self._lock, torch.inference_mode():
                scores = torch.sigmoid(self._model(**inputs)).detach().cpu().tolist()
            if str(self.device).startswith("cuda"):
                torch.cuda.synchronize(torch.device(self.device))
            elapsed_ms = (time.perf_counter() - started) * 1000
        except Exception as exc:
            raise DetectionError(f"NHIS verifier inference failed: {type(exc).__name__}") from exc

        accepted_by_key: dict[tuple[int, int], Span] = {}
        trace_by_key = {}
        for span, score, (_, window_start, window_end) in zip(model_candidates, scores, prepared):
            accepted = float(score) >= THRESHOLD
            link = links.get((span.start, span.end))
            trace_by_key[(span.start, span.end)] = {
                "start": span.start,
                "end": span.end,
                "window_start": window_start,
                "window_end": window_end,
                "raw_score": round(float(score), 7),
                "threshold": THRESHOLD,
                "accepted": accepted,
                "decision": "frozen_model_threshold",
                "field_link": link,
            }
            if accepted:
                metadata = dict(span.metadata)
                metadata.update({
                    "candidate_verifier": "seongyeon-roberta-lora-head",
                    "candidate_verifier_base_revision": BASE_REVISION,
                    "candidate_verifier_adapter_sha256": ADAPTER_SHA256,
                    "candidate_verifier_raw_score": round(float(score), 7),
                    "candidate_verifier_threshold": THRESHOLD,
                    "candidate_window": [window_start, window_end],
                    "candidate_windows_merged": False,
                    "score_semantics": "candidate verifier raw sigmoid; not calibrated probability",
                    "candidate_field_link": link,
                })
                accepted_by_key[(span.start, span.end)] = Span(
                    label=span.label,
                    start=span.start,
                    end=span.end,
                    source=span.source,
                    score=span.score,
                    native_label=span.native_label,
                    metadata=metadata,
                )
        for span in candidates:
            key = (span.start, span.end)
            if key not in trace_by_key:
                link = links.get(key)
                kind = None if link is None else link.get("kind")
                if kind and kind.startswith("non_nhis_"):
                    decision = "rejected_direct_non_nhis_field_link"
                elif kind == "ambiguous":
                    decision = "rejected_ambiguous_field_link"
                else:
                    decision = "rejected_unlinked_precision_policy"
                trace_by_key[key] = {
                    "start": span.start,
                    "end": span.end,
                    "window_start": None,
                    "window_end": None,
                    "raw_score": None,
                    "threshold": THRESHOLD,
                    "accepted": False,
                    "decision": decision,
                    "field_link": link,
                }
        self.last_trace = tuple(trace_by_key[(span.start, span.end)] for span in candidates)
        self.last_inference_ms = elapsed_ms
        output = []
        for span in spans:
            if span.label == "KR_NHIS" and span.source == "rule:nhis-shape":
                accepted = accepted_by_key.get((span.start, span.end))
                if accepted is not None:
                    output.append(accepted)
            else:
                output.append(span)
        return output
