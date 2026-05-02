from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud import texttospeech

from backend.app.models.schemas import TextToSpeechVoice, TextToSpeechVoiceList


class TextToSpeechService:
    def __init__(self) -> None:
        self._client: "texttospeech.TextToSpeechClient | None" = None

    @property
    def client(self) -> "texttospeech.TextToSpeechClient":
        from google.cloud import texttospeech

        if self._client is None:
            self._client = texttospeech.TextToSpeechClient()
        return self._client

    def list_voices(self, language_code: str | None = None) -> TextToSpeechVoiceList:
        from google.cloud import texttospeech

        response = self.client.list_voices(language_code=language_code or None)
        voices = [
            TextToSpeechVoice(
                name=voice.name,
                language_codes=list(voice.language_codes),
                ssml_gender=texttospeech.SsmlVoiceGender(voice.ssml_gender).name,
                natural_sample_rate_hertz=voice.natural_sample_rate_hertz,
                voice_type=_infer_voice_type(voice.name),
            )
            for voice in response.voices
        ]
        return TextToSpeechVoiceList(total_voices=len(voices), voices=voices)


def _infer_voice_type(name: str) -> str | None:
    normalized = name.lower()
    known_types = (
        ("chirp3-hd", "Chirp3-HD"),
        ("chirp-hd", "Chirp-HD"),
        ("studio", "Studio"),
        ("neural2", "Neural2"),
        ("wavenet", "Wavenet"),
        ("standard", "Standard"),
    )
    for marker, label in known_types:
        if marker in normalized:
            return label

    parts = name.split("-")
    if len(parts) >= 3 and parts[-2].isalpha():
        return parts[-2]
    return None
