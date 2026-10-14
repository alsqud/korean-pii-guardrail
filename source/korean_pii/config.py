from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .errors import ConfigError


TOP_KEYS = {"schema_version", "policy_version", "description", "runtime", "models", "types", "direct", "mask", "unsupported"}
RUNTIME_KEYS = {"device_env", "device_default", "kiwi_site_packages_env", "fail_closed", "max_text_chars"}
MODEL_KEYS = {"model_id", "path", "path_env", "revision", "license", "max_length", "stride", "role"}
TYPE_KEYS = {"enabled", "candidate_detectors", "candidate_threshold", "expert_model", "expert_threshold", "context_chars", "allowed_output_labels", "precise_bypass", "threshold_evidence"}
THRESHOLD_KEYS = {"enabled", "value", "model", "model_id", "revision"}
THRESHOLD_EVIDENCE_KEYS = {"candidate", "expert"}
EVIDENCE_ITEM_KEYS = {"status", "basis", "evaluation_source"}
SUPPORTED_TYPES = {
    "PERSON", "KR_LOCATION", "KR_BANK_ACCOUNT", "KR_PASSPORT",
    "KR_DRIVER_LICENSE", "KR_VEHICLE_PLATE", "CREDIT_CARD",
    "DATE_OF_BIRTH", "USERNAME", "EMAIL_ADDRESS", "IP_ADDRESS",
    "KR_PHONE_NUMBER", "KR_RRN", "KR_NHIS",
}
DIRECT_KEYS = {"frame_labels", "ko_pii_labels", "presidio_labels", "enable_nhis_shape"}
MASK_KEYS = {"token_format", "overlap_priority"}


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    name: str
    model_id: str
    path: Path
    path_env: str
    revision: str
    license: str
    max_length: int
    stride: int
    role: str


@dataclass(frozen=True, slots=True)
class ThresholdPolicy:
    enabled: bool
    value: float | None
    model: str | None
    model_id: str | None
    revision: str | None


@dataclass(frozen=True, slots=True)
class TypePolicy:
    label: str
    enabled: bool
    candidate_detectors: tuple[str, ...]
    candidate_threshold: ThresholdPolicy
    expert_model: str | None
    expert_threshold: ThresholdPolicy
    context_chars: int
    allowed_output_labels: tuple[str, ...]
    precise_bypass: str | None
    threshold_evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Policy:
    schema_version: str
    policy_version: str
    description: str
    runtime: Mapping[str, Any]
    models: Mapping[str, ModelPolicy]
    types: Mapping[str, TypePolicy]
    direct: Mapping[str, Any]
    mask: Mapping[str, Any]
    unsupported: tuple[str, ...]
    sha256: str
    source: str


def _only(value: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{where} must be a list of non-empty strings")
    return tuple(value)


def _threshold(value: Any, where: str, models: Mapping[str, ModelPolicy]) -> ThresholdPolicy:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be an object")
    _only(value, THRESHOLD_KEYS, where)
    if set(value) != THRESHOLD_KEYS:
        raise ConfigError(f"{where}: missing keys {sorted(THRESHOLD_KEYS - set(value))}")
    enabled = value["enabled"]
    number = value["value"]
    model = value["model"]
    if not isinstance(enabled, bool):
        raise ConfigError(f"{where}.enabled must be boolean")
    if enabled and (isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 1):
        raise ConfigError(f"{where}.value must be within [0,1] when enabled")
    if not enabled and number is not None:
        raise ConfigError(f"{where}.value must be null when disabled; disabled is not threshold zero")
    if model is None:
        if any(value[key] is not None for key in ("model_id", "revision")):
            raise ConfigError(f"{where}: null model requires null model_id and revision")
        if enabled:
            raise ConfigError(f"{where}: a threshold cannot be enabled without a model")
    else:
        if model not in models:
            raise ConfigError(f"{where}.model is unknown")
        if value["model_id"] != models[model].model_id or value["revision"] != models[model].revision:
            raise ConfigError(f"{where}: model_id/revision do not match models.{model}")
    return ThresholdPolicy(
        enabled=enabled, value=None if number is None else float(number), model=model,
        model_id=value["model_id"], revision=value["revision"],
    )


def _threshold_evidence(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be an object")
    _only(value, THRESHOLD_EVIDENCE_KEYS, where)
    if set(value) != THRESHOLD_EVIDENCE_KEYS:
        raise ConfigError(f"{where}: missing keys {sorted(THRESHOLD_EVIDENCE_KEYS - set(value))}")
    output = {}
    for key in ("candidate", "expert"):
        item = value[key]
        if not isinstance(item, dict):
            raise ConfigError(f"{where}.{key} must be an object")
        _only(item, EVIDENCE_ITEM_KEYS, f"{where}.{key}")
        if set(item) != EVIDENCE_ITEM_KEYS:
            raise ConfigError(f"{where}.{key}: missing evidence fields")
        if item["status"] not in {"evaluated", "not_tuned", "not_applicable"}:
            raise ConfigError(f"{where}.{key}.status invalid")
        if not all(isinstance(item[field], str) and item[field] for field in EVIDENCE_ITEM_KEYS):
            raise ConfigError(f"{where}.{key}: evidence values must be non-empty strings")
        output[key] = MappingProxyType(dict(item))
    return MappingProxyType(output)


def load_policy_data(value: dict[str, Any], source: str = "<memory>", raw: bytes | None = None) -> Policy:
    if not isinstance(value, dict):
        raise ConfigError("policy must be an object")
    _only(value, TOP_KEYS, "policy")
    missing = TOP_KEYS - set(value)
    if missing:
        raise ConfigError(f"policy: missing keys {sorted(missing)}")
    if value["schema_version"] != "1.0":
        raise ConfigError("unsupported schema_version")
    if not isinstance(value["policy_version"], str) or not value["policy_version"]:
        raise ConfigError("policy_version must be non-empty")

    runtime = value["runtime"]
    if not isinstance(runtime, dict):
        raise ConfigError("runtime must be an object")
    _only(runtime, RUNTIME_KEYS, "runtime")
    if set(runtime) != RUNTIME_KEYS:
        raise ConfigError(f"runtime: missing keys {sorted(RUNTIME_KEYS - set(runtime))}")
    if runtime["fail_closed"] is not True:
        raise ConfigError("runtime.fail_closed must be true")
    if runtime["device_default"] not in {"cuda", "cpu"}:
        raise ConfigError("runtime.device_default must be cuda or cpu")
    if not isinstance(runtime["max_text_chars"], int) or runtime["max_text_chars"] <= 0:
        raise ConfigError("runtime.max_text_chars must be a positive integer")

    models_raw = value["models"]
    if not isinstance(models_raw, dict) or set(models_raw) != {"frame", "koredact", "atonlee", "seongyeon"}:
        raise ConfigError("models must define exactly frame, koredact, atonlee, seongyeon")
    models = {}
    for name, item in models_raw.items():
        if not isinstance(item, dict):
            raise ConfigError(f"models.{name} must be an object")
        _only(item, MODEL_KEYS, f"models.{name}")
        if set(item) != MODEL_KEYS:
            raise ConfigError(f"models.{name}: missing keys {sorted(MODEL_KEYS - set(item))}")
        if not isinstance(item["max_length"], int) or item["max_length"] < 32:
            raise ConfigError(f"models.{name}.max_length invalid")
        if not isinstance(item["stride"], int) or not 0 < item["stride"] < item["max_length"]:
            raise ConfigError(f"models.{name}.stride invalid")
        models[name] = ModelPolicy(
            name=name, model_id=str(item["model_id"]), path=Path(item["path"]), path_env=str(item["path_env"]),
            revision=str(item["revision"]),
            license=str(item["license"]), max_length=item["max_length"],
            stride=item["stride"], role=str(item["role"]),
        )

    types_raw = value["types"]
    if not isinstance(types_raw, dict) or not types_raw:
        raise ConfigError("types must be a non-empty object")
    if unknown_types := set(types_raw) - SUPPORTED_TYPES:
        raise ConfigError(f"types contains unsupported labels {sorted(unknown_types)}")
    if missing_types := SUPPORTED_TYPES - set(types_raw):
        raise ConfigError(f"types is missing supported labels {sorted(missing_types)}")
    types = {}
    for label, item in types_raw.items():
        if not isinstance(item, dict):
            raise ConfigError(f"types.{label} must be an object")
        _only(item, TYPE_KEYS, f"types.{label}")
        required = TYPE_KEYS - {"precise_bypass"}
        if missing := required - set(item):
            raise ConfigError(f"types.{label}: missing keys {sorted(missing)}")
        if not isinstance(item["enabled"], bool):
            raise ConfigError(f"types.{label}.enabled must be boolean")
        expert = item["expert_model"]
        if expert is not None and expert not in models:
            raise ConfigError(f"types.{label}.expert_model is unknown")
        candidate_threshold = _threshold(item["candidate_threshold"], f"types.{label}.candidate_threshold", models)
        expert_threshold = _threshold(item["expert_threshold"], f"types.{label}.expert_threshold", models)
        if any(detector.startswith("frontend:") for detector in item["candidate_detectors"]):
            if candidate_threshold.model != "frame":
                raise ConfigError(f"types.{label}.candidate_threshold must be owned by frame")
        elif candidate_threshold.model is not None:
            raise ConfigError(f"types.{label}.candidate_threshold model must be null without frontend candidates")
        if expert != expert_threshold.model:
            raise ConfigError(f"types.{label}.expert_threshold model must match expert_model")
        context = item["context_chars"]
        if isinstance(context, bool) or not isinstance(context, int) or context < 0:
            raise ConfigError(f"types.{label}.context_chars invalid")
        allowed = _strings(item["allowed_output_labels"], f"types.{label}.allowed_output_labels")
        if expert and label not in allowed:
            raise ConfigError(f"types.{label} must allow its own label")
        types[label] = TypePolicy(
            label=label, enabled=item["enabled"],
            candidate_detectors=_strings(item["candidate_detectors"], f"types.{label}.candidate_detectors"),
            candidate_threshold=candidate_threshold, expert_model=expert,
            expert_threshold=expert_threshold,
            context_chars=context, allowed_output_labels=allowed,
            precise_bypass=item.get("precise_bypass"),
            threshold_evidence=_threshold_evidence(item["threshold_evidence"], f"types.{label}.threshold_evidence"),
        )

    direct = value["direct"]
    if not isinstance(direct, dict):
        raise ConfigError("direct must be an object")
    _only(direct, DIRECT_KEYS, "direct")
    if set(direct) != DIRECT_KEYS:
        raise ConfigError(f"direct: missing keys {sorted(DIRECT_KEYS - set(direct))}")
    direct_frozen = {
        "frame_labels": _strings(direct["frame_labels"], "direct.frame_labels"),
        "ko_pii_labels": _strings(direct["ko_pii_labels"], "direct.ko_pii_labels"),
        "presidio_labels": _strings(direct["presidio_labels"], "direct.presidio_labels"),
        "enable_nhis_shape": bool(direct["enable_nhis_shape"]),
    }

    mask = value["mask"]
    if not isinstance(mask, dict):
        raise ConfigError("mask must be an object")
    _only(mask, MASK_KEYS, "mask")
    if set(mask) != MASK_KEYS or "{label}" not in mask["token_format"]:
        raise ConfigError("mask requires token_format containing {label} and overlap_priority")
    priority = _strings(mask["overlap_priority"], "mask.overlap_priority")
    unsupported = _strings(value["unsupported"], "unsupported")
    if "AGE" not in unsupported or "PATIENT_ID" not in unsupported:
        raise ConfigError("unsupported must explicitly contain AGE and PATIENT_ID")
    if "AGE" in types or "PATIENT_ID" in types:
        raise ConfigError("AGE and PATIENT_ID may not be configured as detected types")

    encoded = raw if raw is not None else (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return Policy(
        schema_version=value["schema_version"], policy_version=value["policy_version"],
        description=str(value["description"]), runtime=MappingProxyType(dict(runtime)),
        models=MappingProxyType(models), types=MappingProxyType(types),
        direct=MappingProxyType(direct_frozen),
        mask=MappingProxyType({"token_format": mask["token_format"], "overlap_priority": priority}),
        unsupported=unsupported, sha256=hashlib.sha256(encoded).hexdigest(), source=source,
    )


def load_policy(path: str | Path) -> Policy:
    source = Path(path)
    raw = source.read_bytes()
    return load_policy_data(json.loads(raw), str(source), raw)


def load_default_policy() -> Policy:
    resource = files("korean_pii").joinpath("default-policy.json")
    raw = resource.read_bytes()
    return load_policy_data(json.loads(raw), str(resource), raw)
