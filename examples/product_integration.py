"""Minimal process-scoped integration example; never logs source text."""

from __future__ import annotations

from dataclasses import dataclass

from korean_pii import DetectionError, KoreanPII


@dataclass(frozen=True)
class ProtectionResult:
    masked_text: str
    labels: tuple[str, ...]
    detected_items: int


class ProductPIIGuardrail:
    """Create one instance per service worker and reuse the loaded models."""

    def __init__(self) -> None:
        self._detector = KoreanPII()
        self._detector.address_gazetteer.load()

    @property
    def ready(self) -> bool:
        status = self._detector.status
        return bool(
            status["address_gazetteer"]["loaded"]
            and set(status["loaded_models"]) == set(self._detector.policy.models)
        )

    def protect(self, text: str) -> ProtectionResult:
        try:
            spans = self._detector.detect(text)
            masked = self._detector.mask(text, spans)
        except DetectionError:
            # Fail closed in the product layer. Do not return or log the source text.
            raise
        return ProtectionResult(
            masked_text=masked,
            labels=tuple(sorted({span.label for span in spans})),
            detected_items=len(spans),
        )


if __name__ == "__main__":
    guardrail = ProductPIIGuardrail()
    result = guardrail.protect("개인 담당자: 김민수, 연락처: 010-2345-6789")
    print(result)
