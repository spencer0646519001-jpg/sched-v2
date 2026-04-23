"""Small AI interfaces used by bounded scheduling workflows."""

from __future__ import annotations

from typing import Any, Protocol

StructuredJsonObject = dict[str, Any]


class ModelUnavailableError(RuntimeError):
    """Raised when a configured model path is not available for this request."""


class StructuredOutputModelClient(Protocol):
    """Minimal interface for bounded JSON-only model generation."""

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: StructuredJsonObject,
    ) -> StructuredJsonObject:
        """Return one JSON object that matches the provided schema."""


__all__ = [
    "ModelUnavailableError",
    "StructuredJsonObject",
    "StructuredOutputModelClient",
]
