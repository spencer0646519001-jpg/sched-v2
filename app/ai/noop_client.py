"""No-op AI client used when no real model configuration is available."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.interfaces import (
    ModelUnavailableError,
    StructuredJsonObject,
)


@dataclass(slots=True)
class NoopStructuredOutputModelClient:
    """Always report that the model path is unavailable."""

    reason: str = "Structured model client is not configured."

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: StructuredJsonObject,
    ) -> StructuredJsonObject:
        raise ModelUnavailableError(self.reason)


__all__ = ["NoopStructuredOutputModelClient"]
