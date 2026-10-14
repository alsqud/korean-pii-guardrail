from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Span:
    label: str
    start: int
    end: int
    source: str
    score: float | None = None
    native_label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label or not self.source:
            raise ValueError("Span label and source must be non-empty")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Span offsets must satisfy 0 <= start < end")
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise ValueError("Span score must be within [0,1]")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "source": self.source,
            "score": self.score,
            "native_label": self.native_label,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RoutedWindow:
    model: str
    start: int
    end: int
    focus_start: int
    focus_end: int
    evidence: tuple[str, ...]
    allowed_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("RoutedWindow offsets must satisfy 0 <= start < end")
        if not self.start <= self.focus_start < self.focus_end <= self.end:
            raise ValueError("RoutedWindow focus must be non-empty and contained in the window")
