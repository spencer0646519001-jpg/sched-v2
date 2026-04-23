"""Small OpenAI structured-output client for bounded scheduling workflows."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.ai.interfaces import (
    ModelUnavailableError,
    StructuredJsonObject,
)
from app.ai.noop_client import NoopStructuredOutputModelClient

_DEFAULT_BASE_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4o-mini"


@dataclass(slots=True)
class OpenAIChatCompletionsStructuredOutputClient:
    """Call the OpenAI Chat Completions API with a strict JSON schema."""

    api_key: str
    model: str = _DEFAULT_MODEL
    base_url: str = _DEFAULT_BASE_URL
    timeout_seconds: float = 20.0

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
                    "name": "sched_v2_day_explain",
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


def build_structured_output_model_client_from_env():
    """Create the default structured-output model client for explain flows."""

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return NoopStructuredOutputModelClient()

    return OpenAIChatCompletionsStructuredOutputClient(
        api_key=api_key,
        model=os.getenv("SCHED_V2_EXPLAIN_MODEL", "").strip() or _DEFAULT_MODEL,
        base_url=os.getenv("OPENAI_BASE_URL", "").strip() or _DEFAULT_BASE_URL,
    )


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


__all__ = [
    "OpenAIChatCompletionsStructuredOutputClient",
    "build_structured_output_model_client_from_env",
]
