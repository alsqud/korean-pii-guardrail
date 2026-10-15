"""Deployment readiness check for the installed hybrid pipeline."""

from __future__ import annotations

import json

from .errors import PIIError
from .hybrid_pipeline import KoreanPII


SMOKE_TEXT = (
    "개인 담당자: 김민수 | 개인 휴대전화: 010-2345-6789 | "
    "개인 이메일: minsu@example.invalid"
)
EXPECTED_LABELS = {"PERSON", "KR_PHONE_NUMBER", "EMAIL_ADDRESS"}


def readiness() -> dict:
    try:
        detector = KoreanPII()
        detector.address_gazetteer.load()
        spans = detector.detect(SMOKE_TEXT)
        labels = {span.label for span in spans}
        missing = sorted(EXPECTED_LABELS - labels)
        status = detector.status
        loaded_models = sorted(status["loaded_models"])
        required_models = sorted(detector.policy.models)
        ready = (
            not missing
            and loaded_models == required_models
            and status["address_gazetteer"]["configured"]
            and status["address_gazetteer"]["loaded"]
        )
        return {
            "status": "ready" if ready else "not_ready",
            "pipeline_profile": status.get("pipeline_profile"),
            "policy_version": status["policy_version"],
            "policy_sha256": status["policy_sha256"],
            "loaded_models": loaded_models,
            "required_models": required_models,
            "address_index": {
                "configured": status["address_gazetteer"]["configured"],
                "loaded": status["address_gazetteer"]["loaded"],
                "index_sha256": status["address_gazetteer"].get("index_sha256"),
            },
            "smoke_expected_labels": sorted(EXPECTED_LABELS),
            "smoke_missing_labels": missing,
        }
    except (PIIError, OSError, ValueError) as exc:
        return {
            "status": "not_ready",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }


def main() -> None:
    result = readiness()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "ready" else 2)


if __name__ == "__main__":
    main()
