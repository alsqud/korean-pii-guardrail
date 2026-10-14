from __future__ import annotations

import json
import sys

from .errors import DetectionError
from .pipeline import KoreanPII


def main() -> None:
    """Interactive/stdin smoke client; no HTTP server and no external transfer."""
    text = input("문장을 입력하세요: ") if sys.stdin.isatty() else sys.stdin.read().rstrip("\n")
    if not text:
        raise SystemExit("입력이 비어 있습니다.")
    detector = KoreanPII()
    try:
        spans = detector.detect(text)
        result = {
            "spans": [span.to_dict() for span in spans],
            "masked": detector.mask(text, spans),
            "policy_version": detector.policy.policy_version,
            "policy_sha256": detector.policy.sha256,
            "score_notice": "모델별 raw score이며 보정 확률이나 모델 간 비교값이 아닙니다.",
        }
    except DetectionError as exc:
        # The exception contract omits input text. Exit nonzero so callers do
        # not confuse a failure with successful no-PII detection.
        print(json.dumps({"status": "failed_closed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
