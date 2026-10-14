class PIIError(RuntimeError):
    """Base package error."""


class ConfigError(PIIError, ValueError):
    """Raised before inference when policy configuration is invalid."""


class ModelLoadError(PIIError):
    """Raised when an approved local model snapshot cannot be loaded safely."""


class DetectionError(PIIError):
    """Fail-closed detection failure; callers must not return unmasked input."""
