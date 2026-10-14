from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from .config import ModelPolicy, Policy
from .errors import ModelLoadError
from .types import Span


LABEL_MAP = {
    "RRN": "KR_RRN", "PASSPORT": "KR_PASSPORT", "DRIVER_LICENSE": "KR_DRIVER_LICENSE",
    "CARD_NUMBER": "CREDIT_CARD", "CARD": "CREDIT_CARD", "ACCOUNT_NUMBER": "KR_BANK_ACCOUNT",
    "ACCOUNT": "KR_BANK_ACCOUNT", "NAME": "PERSON", "NICKNAME": "PERSON",
    "PHONE": "KR_PHONE_NUMBER", "EMAIL": "EMAIL_ADDRESS", "ADDRESS": "KR_LOCATION",
    "CITY": "KR_LOCATION", "BIRTHDATE": "DATE_OF_BIRTH", "USER_ID": "USERNAME",
    "VEHICLE_NUMBER": "KR_VEHICLE_PLATE", "IP_ADDRESS": "IP_ADDRESS", "URL": "URL",
    "PASSPORT_NUM": "KR_PASSPORT", "PASSPORTNUM": "KR_PASSPORT",
    "DRIVER_LICENSE_NUM": "KR_DRIVER_LICENSE", "PERSON_NAME": "PERSON",
    "PHONE_NUM": "KR_PHONE_NUMBER", "ACCOUNT_NUM": "KR_BANK_ACCOUNT",
    "CARD_NUM": "CREDIT_CARD", "URL_PERSONAL": "URL", "PLATE_NUM": "KR_VEHICLE_PLATE",
    "DOB": "DATE_OF_BIRTH", "AFFILIATION": "ORGANIZATION",
    "private_person": "PERSON", "personal_handle": "USERNAME",
    "private_phone": "KR_PHONE_NUMBER", "private_email": "EMAIL_ADDRESS",
    "private_address": "KR_LOCATION", "private_date": "DATE_OF_BIRTH",
    "private_url": "URL", "ip_address": "IP_ADDRESS",
}
FRAME_JOSA = (
    "이에요", "이라고", "입니다", "이야", "이랑", "한테", "에게", "으로", "이가", "이는",
    "에서", "이고", "예요", "씨", "님", "이", "가", "은", "는", "을", "를", "야", "아", "에", "의", "랑", "께", "고",
)
NUMERIC_JOSA = ("으로", "에서", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "와", "과", "로", "도", "만")
FRAME_DATE_END = re.compile(r".*(?:일|[0-9])", re.S)


def _strip_bio(label: str) -> tuple[str, str]:
    if label == "O":
        return "O", "O"
    if len(label) > 2 and label[1] == "-" and label[0] in "BIES":
        return label[0], label[2:]
    return "I", label


def _decode(labels, scores, offsets) -> list[dict]:
    found, current = [], None

    def close():
        nonlocal current
        if current is not None and current["end"] > current["start"]:
            current["score"] = sum(current.pop("scores")) / current.pop("count")
            found.append(current)
        current = None

    for label, score, offset in zip(labels, scores, offsets):
        start, end = int(offset[0]), int(offset[1])
        if start == end:
            continue
        prefix, native = _strip_bio(label)
        if prefix == "O":
            close()
        elif prefix == "S":
            close()
            found.append({"native": native, "start": start, "end": end, "score": float(score)})
        elif prefix == "B":
            close()
            current = {"native": native, "start": start, "end": end, "scores": [float(score)], "count": 1}
        elif current is None or current["native"] != native:
            close()
            current = {"native": native, "start": start, "end": end, "scores": [float(score)], "count": 1}
        else:
            current["end"] = end
            current["scores"].append(float(score))
            current["count"] += 1
        if prefix == "E":
            close()
    close()
    return found


def _dedup(spans: list[dict]) -> list[dict]:
    exact = {}
    for span in spans:
        key = span["native"], span["start"], span["end"]
        if key not in exact or span["score"] > exact[key]["score"]:
            exact[key] = span
    ordered = sorted(exact.values(), key=lambda item: (item["start"], item["end"], item["native"]))
    output = []
    for span in ordered:
        replaced = False
        for index, prior in enumerate(output):
            if prior["native"] != span["native"]:
                continue
            overlap = max(0, min(prior["end"], span["end"]) - max(prior["start"], span["start"]))
            shorter = max(1, min(prior["end"] - prior["start"], span["end"] - span["start"]))
            if overlap / shorter >= 0.8:
                output[index] = max((prior, span), key=lambda item: (item["end"] - item["start"], item["score"]))
                replaced = True
                break
        if not replaced:
            output.append(span)
    return sorted(output, key=lambda item: (item["start"], item["end"], item["native"]))


def _luhn(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 12 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def _frame_account(surface: str) -> str:
    compact = surface.strip()
    digits = re.sub(r"\D", "", compact)
    if re.fullmatch(r"\d{6}[- ]?[1-8]\d{6}", compact):
        return "KR_RRN"
    if re.fullmatch(r"[A-Z]{1,2}\d{7,8}", compact):
        return "KR_PASSPORT"
    if len(digits) in {15, 16, 19} and _luhn(compact):
        return "CREDIT_CARD"
    return "KR_BANK_ACCOUNT"


def _normalize(model: str, native: str, text: str, start: int, end: int) -> tuple[int, int, tuple[str, ...]]:
    changes = []
    if model == "frame":
        original = start, end
        while start < end and text[start] in " .,\t\n":
            start += 1
        while end > start and text[end - 1] in " .,\t\n":
            end -= 1
        if native == "private_date":
            match = FRAME_DATE_END.match(text[start:end])
            if match:
                end = start + match.end()
        elif native in {"private_person", "personal_handle", "private_address"}:
            for _ in range(2):
                segment = text[start:end]
                for particle in FRAME_JOSA:
                    if segment.endswith(particle) and end - start - len(particle) >= 2:
                        end -= len(particle)
                        break
                else:
                    break
        if (start, end) != original:
            changes.append("frame-card-normalization")
    segment = text[start:end]
    for particle in NUMERIC_JOSA:
        if segment.endswith(particle) and len(segment) > len(particle) and segment[-len(particle) - 1].isdigit():
            end -= len(particle)
            changes.append("trimmed-numeric-josa")
            break
    return start, end, tuple(changes)


class TokenClassificationAdapter:
    def __init__(self, config: ModelPolicy, device: str):
        self.config = config
        self.device = device
        self._lock = threading.RLock()
        self._tokenizer = None
        self._model = None
        self._id2label = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self.loaded:
                return
            path = Path(os.getenv(self.config.path_env, str(self.config.path))).expanduser()
            required = (path / "config.json", path / "model.safetensors")
            if not all(item.is_file() for item in required):
                raise ModelLoadError(
                    f"{self.config.name}: approved local safetensors snapshot is incomplete at {path}; "
                    f"prepare {self.config.model_id}@{self.config.revision} explicitly before startup"
                )
            raw_config = json.loads((path / "config.json").read_text(encoding="utf-8"))
            if raw_config.get("auto_map"):
                raise ModelLoadError(f"{self.config.name}: custom auto_map is not permitted")
            try:
                import torch
                from transformers import AutoModelForTokenClassification, AutoTokenizer
                if self.device.startswith("cuda") and not torch.cuda.is_available():
                    raise ModelLoadError("CUDA was requested but is unavailable; no silent CPU fallback")
                tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
                model = AutoModelForTokenClassification.from_pretrained(
                    path, local_files_only=True, trust_remote_code=False,
                    use_safetensors=True, dtype="auto",
                ).to(self.device).eval()
            except ModelLoadError:
                raise
            except Exception as exc:
                raise ModelLoadError(f"{self.config.name}: {type(exc).__name__}") from exc
            self._tokenizer = tokenizer
            self._model = model
            self._id2label = {int(key): value for key, value in model.config.id2label.items()}

    def predict(self, text: str, *, absolute_offset: int = 0) -> list[Span]:
        self.load()
        import torch
        if not text:
            return []
        native = []
        with self._lock, torch.inference_mode():
            def append_predictions(
                encoded, offsets, *, shift: int,
                min_end_exclusive: int | None = None,
            ) -> None:
                encoded.pop("overflow_to_sample_mapping", None)
                if (
                    "token_type_ids" in encoded
                    and "token_type_ids" not in self._tokenizer.model_input_names
                ):
                    encoded.pop("token_type_ids")
                model_inputs = {
                    key: value.to(self.device)
                    for key, value in encoded.items()
                    if key in self._tokenizer.model_input_names
                }
                logits = self._model(**model_inputs).logits
                probability = torch.softmax(logits.float(), dim=-1)
                confidence, predicted = probability.max(dim=-1)
                offset_rows = offsets.tolist()
                for index in range(predicted.shape[0]):
                    labels = [
                        self._id2label[int(item)]
                        for item in predicted[index].detach().cpu().tolist()
                    ]
                    scores = confidence[index].detach().cpu().tolist()
                    absolute_offsets = [
                        (start + shift, end + shift)
                        if start != end else (0, 0)
                        for start, end in offset_rows[index]
                    ]
                    decoded = _decode(labels, scores, absolute_offsets)
                    if min_end_exclusive is not None:
                        decoded = [
                            item for item in decoded
                            if item["end"] > min_end_exclusive
                        ]
                    native.extend(decoded)

            initial = self._tokenizer(
                text,
                return_tensors="pt",
                return_offsets_mapping=True,
                return_overflowing_tokens=True,
                truncation=True,
                max_length=self.config.max_length,
                stride=self.config.stride,
                padding=True,
            )
            initial_offsets = initial.pop("offset_mapping")
            covered_end = max(
                (
                    int(end)
                    for row in initial_offsets.tolist()
                    for start, end in row
                    if start != end
                ),
                default=0,
            )
            required_end = len(text.rstrip())
            # Always preserve the existing batched results. The fallback below
            # contributes only spans reaching beyond its observed coverage.
            append_predictions(initial, initial_offsets, shift=0)
            if covered_end < required_end:
                # Some fast-tokenizer snapshots contain backend truncation.
                # In the affected path, the wrapper returns the first chunk
                # plus only a shallow overflow and silently loses the tail.
                last_content = [
                    (int(start), int(end))
                    for start, end in initial_offsets[-1].tolist()
                    if start != end
                ]
                cursor = min((start for start, _ in last_content), default=0)
                while cursor < len(text):
                    encoded = self._tokenizer(
                        text[cursor:],
                        return_tensors="pt",
                        return_offsets_mapping=True,
                        return_overflowing_tokens=False,
                        truncation=True,
                        max_length=self.config.max_length,
                        padding=True,
                    )
                    offsets = encoded.pop("offset_mapping")
                    offset_row = offsets[0].tolist()
                    append_predictions(
                        encoded, offsets, shift=cursor,
                        min_end_exclusive=covered_end,
                    )

                    content_offsets = [
                        (start, end) for start, end in offset_row if start != end
                    ]
                    if not content_offsets:
                        if not text[cursor:].strip():
                            break
                        raise ModelLoadError(
                            f"{self.config.name}: tokenizer produced no text offsets"
                        )
                    consumed = max(end for _, end in content_offsets)
                    if consumed >= len(text) - cursor:
                        break
                    if len(content_offsets) > self.config.stride:
                        advance = content_offsets[-self.config.stride][0]
                    else:
                        advance = consumed
                    if advance <= 0:
                        advance = consumed
                    if advance <= 0:
                        raise ModelLoadError(
                            f"{self.config.name}: tokenizer made no forward progress"
                        )
                    cursor += advance
        output = []
        for item in _dedup(native):
            surface = text[item["start"]:item["end"]]
            label = _frame_account(surface) if self.config.name == "frame" and item["native"] == "account_number" else LABEL_MAP.get(item["native"])
            if label is None:
                continue
            start, end, changes = _normalize(self.config.name, item["native"], text, item["start"], item["end"])
            if end <= start:
                continue
            output.append(Span(
                label=label, start=absolute_offset + start, end=absolute_offset + end,
                source=f"model:{self.config.name}", score=round(float(item["score"]), 7),
                native_label=item["native"],
                metadata={"normalizations": changes, "score_semantics": "mean raw token softmax; not calibrated probability"},
            ))
        return output


class ModelRegistry:
    def __init__(self, policy: Policy, device: str):
        self.policy = policy
        self.device = device
        self._adapters: dict[str, TokenClassificationAdapter] = {}
        self._lock = threading.RLock()

    def get(self, name: str) -> TokenClassificationAdapter:
        if name not in self.policy.models:
            raise ModelLoadError(f"unknown configured model: {name}")
        with self._lock:
            if name not in self._adapters:
                self._adapters[name] = TokenClassificationAdapter(self.policy.models[name], self.device)
            return self._adapters[name]

    @property
    def loaded_models(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, adapter in self._adapters.items() if adapter.loaded))
