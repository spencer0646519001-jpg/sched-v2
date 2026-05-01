"""Small OpenAI structured-output client for bounded scheduling workflows."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from app.ai.interfaces import (
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    ModelUnavailableError,
    StructuredJsonObject,
)
from app.ai.noop_client import (
    NoopAudioTranscriptionClient,
    NoopStructuredOutputModelClient,
)

_DEFAULT_CHAT_COMPLETIONS_BASE_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_AUDIO_TRANSCRIPTIONS_BASE_URL = (
    "https://api.openai.com/v1/audio/transcriptions"
)
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_STRUCTURED_OUTPUT_SCHEMA_NAME = "sched_v2_day_explain"
_DEFAULT_TRANSCRIPTION_MODEL = "whisper-1"


@dataclass(slots=True)
class OpenAIChatCompletionsStructuredOutputClient:
    """Call the OpenAI Chat Completions API with a strict JSON schema."""

    api_key: str
    model: str = _DEFAULT_MODEL
    base_url: str = _DEFAULT_CHAT_COMPLETIONS_BASE_URL
    timeout_seconds: float = 20.0
    schema_name: str = _DEFAULT_STRUCTURED_OUTPUT_SCHEMA_NAME

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: StructuredJsonObject,
    ) -> StructuredJsonObject:
        request_body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": self.schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            },
        }
        encoded_body = json.dumps(request_body).encode("utf-8")
        http_request = urllib.request.Request(
            self.base_url,
            data=encoded_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelUnavailableError(
                f"OpenAI model request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ModelUnavailableError(
                f"OpenAI model request could not be completed: {exc.reason}"
            ) from exc

        content = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )
        content_text = _coerce_message_content(content)
        if not content_text:
            raise ModelUnavailableError("OpenAI model returned empty content.")

        try:
            decoded_payload = json.loads(content_text)
        except json.JSONDecodeError as exc:
            raise ModelUnavailableError(
                "OpenAI model returned non-JSON content for structured output."
            ) from exc
        if not isinstance(decoded_payload, dict):
            raise ModelUnavailableError(
                "OpenAI model returned a non-object structured response."
            )
        return decoded_payload


@dataclass(slots=True)
class OpenAIWhisperAudioTranscriptionClient:
    """Call the OpenAI audio transcription API for one bounded upload."""

    api_key: str
    model: str = _DEFAULT_TRANSCRIPTION_MODEL
    base_url: str = _DEFAULT_AUDIO_TRANSCRIPTIONS_BASE_URL
    timeout_seconds: float = 30.0

    def transcribe_audio(
        self,
        *,
        request: AudioTranscriptionRequest,
    ) -> AudioTranscriptionResult:
        if not request.audio_bytes:
            raise ValueError("Audio transcription request must contain bytes.")

        boundary = f"----schedv2-{uuid.uuid4().hex}"
        encoded_body = _encode_multipart_form_data(
            boundary=boundary,
            fields=[
                ("model", self.model),
                ("response_format", "verbose_json"),
                ("file", request.filename, request.content_type, request.audio_bytes),
                *(
                    [("prompt", request.prompt)]
                    if request.prompt is not None and request.prompt.strip()
                    else []
                ),
            ],
        )
        http_request = urllib.request.Request(
            self.base_url,
            data=encoded_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": (
                    f"multipart/form-data; boundary={boundary}"
                ),
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelUnavailableError(
                f"OpenAI transcription request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ModelUnavailableError(
                f"OpenAI transcription request could not be completed: {exc.reason}"
            ) from exc

        text = str(payload.get("text") or "").strip()
        if not text:
            raise ModelUnavailableError(
                "OpenAI transcription returned empty text."
            )

        language = payload.get("language")
        return AudioTranscriptionResult(
            text=text,
            language=str(language).strip() if language is not None else None,
            model=self.model,
            provider="openai",
        )


def build_structured_output_model_client_from_env(
    *,
    model_env_names: tuple[str, ...] = (
        "SCHED_V2_EXPLAIN_MODEL",
        "OPENAI_EXPLAIN_MODEL",
    ),
    schema_name: str = _DEFAULT_STRUCTURED_OUTPUT_SCHEMA_NAME,
):
    """Create the default structured-output model client."""

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return NoopStructuredOutputModelClient()

    return OpenAIChatCompletionsStructuredOutputClient(
        api_key=api_key,
        model=_first_configured_env(model_env_names) or _DEFAULT_MODEL,
        base_url=(
            os.getenv("OPENAI_BASE_URL", "").strip()
            or _DEFAULT_CHAT_COMPLETIONS_BASE_URL
        ),
        schema_name=schema_name,
    )


def build_explain_model_client_from_env():
    """Create the structured-output model client for explain flows."""

    return build_structured_output_model_client_from_env(
        model_env_names=("SCHED_V2_EXPLAIN_MODEL", "OPENAI_EXPLAIN_MODEL"),
        schema_name="sched_v2_day_explain",
    )


def build_refine_model_client_from_env():
    """Create the structured-output model client for refine intent parsing."""

    return build_structured_output_model_client_from_env(
        model_env_names=("OPENAI_REFINE_MODEL", "SCHED_V2_REFINE_MODEL"),
        schema_name="sched_v2_refine_intent",
    )


def build_audio_transcription_client_from_env():
    """Create the default bounded transcription client for voice inputs."""

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return NoopAudioTranscriptionClient()

    return OpenAIWhisperAudioTranscriptionClient(
        api_key=api_key,
        model=(
            os.getenv("SCHED_V2_TRANSCRIPTION_MODEL", "").strip()
            or _DEFAULT_TRANSCRIPTION_MODEL
        ),
        base_url=(
            os.getenv("OPENAI_AUDIO_TRANSCRIPTIONS_BASE_URL", "").strip()
            or _DEFAULT_AUDIO_TRANSCRIPTIONS_BASE_URL
        ),
    )


def _first_configured_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _coerce_message_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        return "".join(text_parts)
    return ""


def _encode_multipart_form_data(
    *,
    boundary: str,
    fields: list[tuple[object, ...]],
) -> bytes:
    body = bytearray()
    boundary_bytes = boundary.encode("ascii")
    for field in fields:
        if len(field) == 2:
            name, value = field
            body.extend(b"--" + boundary_bytes + b"\r\n")
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(
                    "utf-8"
                )
            )
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
            continue

        if len(field) != 4:
            raise ValueError("Unsupported multipart field shape.")

        name, filename, content_type, data = field
        body.extend(b"--" + boundary_bytes + b"\r\n")
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        body.extend(
            f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n".encode(
                "utf-8"
            )
        )
        body.extend(bytes(data))
        body.extend(b"\r\n")

    body.extend(b"--" + boundary_bytes + b"--\r\n")
    return bytes(body)


__all__ = [
    "OpenAIChatCompletionsStructuredOutputClient",
    "OpenAIWhisperAudioTranscriptionClient",
    "build_audio_transcription_client_from_env",
    "build_explain_model_client_from_env",
    "build_refine_model_client_from_env",
    "build_structured_output_model_client_from_env",
]
