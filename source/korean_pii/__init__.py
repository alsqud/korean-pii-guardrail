from __future__ import annotations

import os
import threading

from .errors import ConfigError, DetectionError, ModelLoadError, PIIError
from .pipeline import KoreanPII
from .types import Span


__all__ = [
    "KoreanPII", "Span", "detect", "mask",
    "PIIError", "ConfigError", "ModelLoadError", "DetectionError",
]

_default = None
_lock = threading.RLock()


def _instance() -> KoreanPII:
    global _default
    with _lock:
        if _default is None:
            _default = KoreanPII(config_path=os.getenv("KOREAN_PII_CONFIG") or None)
        return _default


def detect(text: str) -> tuple[Span, ...]:
    """Detect PII with a process-wide lazy singleton."""
    return _instance().detect(text)


def mask(text: str) -> str:
    """Detect and mask PII; raises DetectionError instead of returning raw input on failure."""
    return _instance().mask(text)
