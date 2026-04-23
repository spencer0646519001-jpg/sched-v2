from __future__ import annotations

import json

from app.ai.interfaces import AudioTranscriptionRequest
from app.ai.noop_client import NoopAudioTranscriptionClient
from app.ai.openai_client import (
    OpenAIWhisperAudioTranscriptionClient,
    build_audio_transcription_client_from_env,
)


def test_openai_whisper_transcription_client_posts_multipart_and_parses_response(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeHttpResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        def read(self) -> bytes:
            return json.dumps(
                {
                    "text": "  请把 SPENCER 安排到 2026-04-01 的 EVE 在 GRILL  ",
                    "language": "zh",
                }
            ).encode("utf-8")

    def _fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        captured["method"] = http_request.get_method()
        captured["timeout"] = timeout
        captured["content_type"] = http_request.get_header("Content-type")
        captured["body"] = bytes(http_request.data or b"")
        return _FakeHttpResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    client = OpenAIWhisperAudioTranscriptionClient(
        api_key="test-key",
        model="whisper-1",
    )

    result = client.transcribe_audio(
        request=AudioTranscriptionRequest(
            filename="request.wav",
            content_type="audio/wav",
            audio_bytes=b"RIFFschedv2",
            prompt="Preserve dates and shift codes exactly.",
        )
    )

    body = captured["body"]
    assert captured["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 30.0
    assert isinstance(captured["content_type"], str)
    assert "multipart/form-data; boundary=" in str(captured["content_type"])
    assert b'name="model"' in body
    assert b"whisper-1" in body
    assert b'name="response_format"' in body
    assert b"verbose_json" in body
    assert b'name="prompt"' in body
    assert b"Preserve dates and shift codes exactly." in body
    assert b'name="file"; filename="request.wav"' in body
    assert b"Content-Type: audio/wav" in body
    assert b"RIFFschedv2" in body
    assert result.text == "请把 SPENCER 安排到 2026-04-01 的 EVE 在 GRILL"
    assert result.language == "zh"
    assert result.model == "whisper-1"
    assert result.provider == "openai"


def test_build_audio_transcription_client_from_env_returns_noop_when_api_key_missing(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = build_audio_transcription_client_from_env()

    assert isinstance(client, NoopAudioTranscriptionClient)
