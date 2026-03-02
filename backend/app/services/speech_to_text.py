import logging

from google.cloud import speech_v1 as speech

logger = logging.getLogger(__name__)


class SpeechToTextService:
    def __init__(self, default_language_code: str = "en-US") -> None:
        self.default_language_code = default_language_code
        self._client: speech.SpeechClient | None = None

    @property
    def client(self) -> speech.SpeechClient:
        if self._client is None:
            self._client = speech.SpeechClient()
        return self._client

    def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
        language_code: str | None = None,
        sample_rate_hz: int | None = None,
    ) -> str:
        encoding = self._encoding_from_mime_type(mime_type)

        config_kwargs: dict = {
            "language_code": language_code or self.default_language_code,
            "enable_automatic_punctuation": True,
            "model": "latest_long",
        }

        if encoding is not None:
            config_kwargs["encoding"] = encoding

        if sample_rate_hz:
            config_kwargs["sample_rate_hertz"] = sample_rate_hz
        elif encoding == speech.RecognitionConfig.AudioEncoding.WEBM_OPUS:
            # MediaRecorder commonly emits 48 kHz WebM Opus.
            config_kwargs["sample_rate_hertz"] = 48000

        config = speech.RecognitionConfig(**config_kwargs)
        audio = speech.RecognitionAudio(content=audio_bytes)

        response = self.client.recognize(config=config, audio=audio)

        transcripts: list[str] = []
        for result in response.results:
            if result.alternatives:
                transcripts.append(result.alternatives[0].transcript.strip())

        transcript = " ".join(part for part in transcripts if part)
        logger.debug("Transcribed %d chars", len(transcript))
        return transcript

    def _encoding_from_mime_type(self, mime_type: str) -> speech.RecognitionConfig.AudioEncoding | None:
        normalized = (mime_type or "").lower()

        if "webm" in normalized:
            return speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
        if "ogg" in normalized:
            return speech.RecognitionConfig.AudioEncoding.OGG_OPUS
        if "wav" in normalized:
            return speech.RecognitionConfig.AudioEncoding.LINEAR16

        return None
