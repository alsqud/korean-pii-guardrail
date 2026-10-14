from __future__ import annotations

from .config import Policy
from .types import RoutedWindow, Span


def accept(span: Span, window: RoutedWindow, policy: Policy) -> bool:
    route = policy.types.get(span.label)
    if route is None or not route.enabled:
        return False
    if route.expert_model != window.model or span.label not in route.allowed_output_labels:
        return False
    if span.label not in window.allowed_labels:
        return False
    threshold = route.expert_threshold
    if threshold.enabled and (span.score is None or span.score < threshold.value):
        return False
    return True


def route_expert_predictions(text: str, windows: dict[str, list[RoutedWindow]], policy: Policy, registry) -> list[Span]:
    output = []
    for model_name, model_windows in windows.items():
        adapter = registry.get(model_name)
        for window in model_windows:
            predicted = adapter.predict(text[window.start:window.end], absolute_offset=window.start)
            for span in predicted:
                if accept(span, window, policy):
                    focus_overlap = (
                        span.start < window.focus_end
                        and window.focus_start < span.end
                    )
                    if focus_overlap:
                        focus_distance = 0
                    elif span.end <= window.focus_start:
                        focus_distance = window.focus_start - span.end
                    else:
                        focus_distance = span.start - window.focus_end
                    metadata = dict(span.metadata)
                    metadata.update({
                        "route_evidence": window.evidence,
                        "allowed_labels": window.allowed_labels,
                        "candidate_focus": (window.focus_start, window.focus_end),
                        "candidate_focus_overlap": focus_overlap,
                        "candidate_focus_distance_chars": focus_distance,
                    })
                    output.append(Span(
                        label=span.label, start=span.start, end=span.end, source=span.source,
                        score=span.score, native_label=span.native_label, metadata=metadata,
                    ))
    return output
