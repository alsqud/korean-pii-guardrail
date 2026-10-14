from __future__ import annotations

import json
import tempfile
from importlib.resources import files
from pathlib import Path

from korean_pii import KoreanPII


def main() -> None:
    policy = json.loads(files("korean_pii").joinpath("default-policy.json").read_text())
    default_enabled = policy["types"]["KR_NHIS"]["enabled"]
    enabled_type_count = sum(bool(item["enabled"]) for item in policy["types"].values())

    default_pii = KoreanPII()
    default_text = "건강보험증 번호는 14253647586이고 이메일은 test@example.com입니다."
    default_spans = list(default_pii.detect(default_text))
    default_nhis = [span for span in default_spans if span.label == "KR_NHIS"]
    default_email = [span for span in default_spans if span.label == "EMAIL_ADDRESS"]

    policy["types"]["KR_NHIS"]["enabled"] = True
    with tempfile.TemporaryDirectory(prefix="korean-pii-config-off-") as directory:
        config = Path(directory) / "policy.json"
        config.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
        enabled_pii = KoreanPII(config_path=config)
        enabled_text = "택배 운송장 번호는 25364758697이고 건강보험증 번호는 36475869701입니다."
        enabled_spans = list(enabled_pii.detect(enabled_text))
    enabled_nhis = [span for span in enabled_spans if span.label == "KR_NHIS"]
    payload = {
        "default_nhis_enabled": default_enabled,
        "supported_type_count": len(policy["types"]),
        "default_enabled_type_count": enabled_type_count,
        "default_nhis_span_count": len(default_nhis),
        "default_other_type_email_detected": bool(default_email),
        "default_nhis_verifier_loaded": default_pii.nhis_verifier.loaded,
        "override_nhis_enabled": True,
        "override_nhis_span_count": len(enabled_nhis),
        "override_nhis_verifier_loaded": enabled_pii.nhis_verifier.loaded,
        "passed": (
            default_enabled is False
            and len(policy["types"]) == 14
            and enabled_type_count == 13
            and not default_nhis
            and bool(default_email)
            and not default_pii.nhis_verifier.loaded
            and len(enabled_nhis) == 1
            and enabled_pii.nhis_verifier.loaded
        ),
    }
    Path("results/v4-nhis-config-off.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
