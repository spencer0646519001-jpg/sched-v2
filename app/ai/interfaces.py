"""Small AI interfaces used by bounded scheduling workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

StructuredJsonObject = dict[str, Any]


class ModelUnavailableError(RuntimeError):
    """Raised when a configured model path is not available for this request."""


@dataclass(slots=True)
class AudioTranscriptionRequest:
    """One bounded audio transcription request."""

    filename: str
    audio_bytes: bytes
    content_type: str | None = None
    prompt: str | None = None


@dataclass(slots=True)
class AudioTranscriptionResult:
    """Small speech-to-text result routed into existing text flows."""

    text: str
    model: str
    provider: str
    language: str | None = None


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


class AudioTranscriptionClient(Protocol):
    """Minimal interface for bounded audio-to-text transcription."""

    def transcribe_audio(
        self,
        *,
        request: AudioTranscriptionRequest,
    ) -> AudioTranscriptionResult:
        """Return one transcription result for the supplied audio bytes."""


__all__ = [
    "AudioTranscriptionClient",
    "AudioTranscriptionRequest",
    "AudioTranscriptionResult",
    "ModelUnavailableError",
    "StructuredJsonObject",
    "StructuredOutputModelClient",
]
